-- Acervo — catalog schema, version 1.
--
-- Conventions
--   * Every table is STRICT (SQLite >= 3.37) so wrong types fail loudly.
--   * Timestamps written by the server are UTC ISO-8601: 'YYYY-MM-DDTHH:MM:SS.sssZ'.
--   * items.captured_at is the LOCAL wall-clock time of capture ('YYYY-MM-DDTHH:MM:SS'),
--     because that is what the timeline shows; the offset lives in captured_tz.
--   * Paths are relative: files.rel_path to the server data dir,
--     volume_copies.rel_path to the root of the external drive.
--   * Rows in items are never deleted. A discarded item becomes 'purged': its bytes
--     are gone but its hash stays, so the daily backup never re-uploads it.

-- ---------------------------------------------------------------------------
-- External drives (VOLUME-001, VOLUME-002, …)
-- ---------------------------------------------------------------------------
CREATE TABLE volumes (
    id                  TEXT PRIMARY KEY,               -- UUID, also in .acervo/volume.json
    name                TEXT NOT NULL UNIQUE,           -- 'VOLUME-001'
    capacity_bytes      INTEGER NOT NULL CHECK (capacity_bytes > 0),
    used_bytes          INTEGER NOT NULL DEFAULT 0 CHECK (used_bytes >= 0),
    filesystem          TEXT NOT NULL DEFAULT 'exfat',
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'full', 'retired', 'problem')),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at        TEXT,
    last_full_check_at  TEXT,
    notes               TEXT,
    CHECK (name GLOB 'VOLUME-[0-9][0-9][0-9]*')
) STRICT;

-- ---------------------------------------------------------------------------
-- Upload sessions: one per "send" from a client; feeds the end-of-upload report
-- ("X novos · Y já existiam · Z quase-duplicados") and the "seguro apagar do
-- iPhone" confirmation (received_verified_count == expected_count).
-- ---------------------------------------------------------------------------
CREATE TABLE upload_sessions (
    id                       INTEGER PRIMARY KEY,
    source                   TEXT NOT NULL
                             CHECK (source IN ('iphone-daily', 'iphone-manual', 'iphone-empty',
                                               'mac', 'web', 'webdav')),
    client_label             TEXT,                       -- e.g. 'iPhone do Quevin'
    status                   TEXT NOT NULL DEFAULT 'open'
                             CHECK (status IN ('open', 'finished', 'abandoned')),
    started_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at              TEXT,
    expected_count           INTEGER CHECK (expected_count >= 0),
    received_verified_count  INTEGER NOT NULL DEFAULT 0,
    new_count                INTEGER NOT NULL DEFAULT 0,
    existing_count           INTEGER NOT NULL DEFAULT 0,
    near_dup_count           INTEGER NOT NULL DEFAULT 0,
    failed_count             INTEGER NOT NULL DEFAULT 0,
    bytes_received           INTEGER NOT NULL DEFAULT 0,
    CHECK ((status = 'open') = (finished_at IS NULL))
) STRICT;

-- ---------------------------------------------------------------------------
-- Items: what the user sees (a photo, a video, a document, a Live Photo…).
-- ---------------------------------------------------------------------------
CREATE TABLE items (
    id                  INTEGER PRIMARY KEY,
    sha256              TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),  -- of the primary file
    phash               INTEGER,                         -- 64-bit perceptual hash (photos)
    kind                TEXT NOT NULL
                        CHECK (kind IN ('photo', 'video', 'document', 'audio', 'other')),
    is_live_photo       INTEGER NOT NULL DEFAULT 0 CHECK (is_live_photo IN (0, 1)),
    live_photo_id       TEXT,                            -- Apple ContentIdentifier, pairs HEIC+MOV
    mime                TEXT,
    size_bytes          INTEGER NOT NULL CHECK (size_bytes >= 0),   -- sum of all files

    captured_at         TEXT NOT NULL,                   -- local time 'YYYY-MM-DDTHH:MM:SS'
    captured_tz         TEXT,                            -- '-03:00' when known
    date_source         TEXT NOT NULL
                        CHECK (date_source IN ('exif', 'metadata', 'mtime', 'upload')),
                        -- 'upload' means "data incerta" in the UI
    uploaded_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    source              TEXT NOT NULL
                        CHECK (source IN ('iphone-daily', 'iphone-manual', 'iphone-empty',
                                          'mac', 'web', 'webdav')),
    upload_session_id   INTEGER REFERENCES upload_sessions(id) ON DELETE SET NULL,

    original_name       TEXT NOT NULL,
    standard_name       TEXT,                            -- 'AAAA-MM-DD_HHMM_<original>.<ext>'

    state               TEXT NOT NULL DEFAULT 'inbox'
                        CHECK (state IN ('inbox', 'library', 'trash', 'archived', 'purged')),
    state_before_trash  TEXT CHECK (state_before_trash IN ('inbox', 'library')),
    trashed_at          TEXT,
    purged_at           TEXT,
    volume_id           TEXT REFERENCES volumes(id),     -- where the original lives once archived
    important           INTEGER NOT NULL DEFAULT 0 CHECK (important IN (0, 1)),

    width               INTEGER CHECK (width > 0),
    height              INTEGER CHECK (height > 0),
    duration_ms         INTEGER CHECK (duration_ms >= 0),
    gps_lat             REAL CHECK (gps_lat BETWEEN -90 AND 90),
    gps_lon             REAL CHECK (gps_lon BETWEEN -180 AND 180),
    place               TEXT,                            -- 'São Paulo, SP' (phase 6)
    camera_make         TEXT,
    camera_model        TEXT,

    -- triage hints (phase 2)
    is_screenshot       INTEGER NOT NULL DEFAULT 0 CHECK (is_screenshot IN (0, 1)),
    burst_id            TEXT,
    origin_app          TEXT,                            -- e.g. 'whatsapp'

    -- background processing
    meta_status         TEXT NOT NULL DEFAULT 'pending'
                        CHECK (meta_status IN ('pending', 'ok', 'failed')),
    thumb_status        TEXT NOT NULL DEFAULT 'pending'
                        CHECK (thumb_status IN ('pending', 'ok', 'failed', 'none')),

    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    CHECK ((state = 'trash') = (trashed_at IS NOT NULL)),
    CHECK ((state = 'trash') = (state_before_trash IS NOT NULL)),
    CHECK ((state = 'purged') = (purged_at IS NOT NULL)),
    CHECK (state <> 'archived' OR volume_id IS NOT NULL),
    CHECK ((gps_lat IS NULL) = (gps_lon IS NULL))
) STRICT;

CREATE INDEX items_timeline       ON items (state, captured_at DESC);
CREATE INDEX items_kind_timeline  ON items (kind, state, captured_at DESC);
CREATE INDEX items_trash          ON items (trashed_at) WHERE state = 'trash';
CREATE INDEX items_volume         ON items (volume_id) WHERE volume_id IS NOT NULL;
CREATE INDEX items_phash          ON items (phash) WHERE phash IS NOT NULL;
CREATE INDEX items_live_photo     ON items (live_photo_id) WHERE live_photo_id IS NOT NULL;
CREATE INDEX items_session        ON items (upload_session_id);
CREATE INDEX items_important      ON items (captured_at DESC) WHERE important = 1;

-- Only these state changes are legal. Anything else is a bug and must not
-- reach the disk. ('purged' and 'archived' are where originals leave the server.)
CREATE TRIGGER items_state_transition
BEFORE UPDATE OF state ON items
WHEN OLD.state <> NEW.state AND NOT (
       (OLD.state = 'inbox'    AND NEW.state IN ('library', 'trash'))
    OR (OLD.state = 'library'  AND NEW.state IN ('trash', 'archived'))
    OR (OLD.state = 'trash'    AND NEW.state IN ('inbox', 'library', 'purged'))
    OR (OLD.state = 'archived' AND NEW.state = 'library')
)
BEGIN
    SELECT RAISE(ABORT, 'invalid item state transition');
END;

CREATE TRIGGER items_touch_updated_at
AFTER UPDATE ON items
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE items SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id;
END;

CREATE TRIGGER items_never_deleted
BEFORE DELETE ON items
BEGIN
    SELECT RAISE(ABORT, 'items are never deleted; use state = purged');
END;

-- ---------------------------------------------------------------------------
-- Files: the actual bytes. One item has 1 file, or 2 for a Live Photo.
-- sha256 is UNIQUE across the whole catalog: identical content is stored once.
-- ---------------------------------------------------------------------------
CREATE TABLE files (
    id          INTEGER PRIMARY KEY,
    item_id     INTEGER NOT NULL REFERENCES items(id),
    role        TEXT NOT NULL CHECK (role IN ('original', 'live-video')),
    sha256      TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
    size_bytes  INTEGER NOT NULL CHECK (size_bytes >= 0),
    mime        TEXT,
    ext         TEXT NOT NULL,                     -- lowercase, without the dot
    rel_path    TEXT UNIQUE,                       -- NULL once the bytes left the server
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (item_id, role)
) STRICT;

CREATE INDEX files_item ON files (item_id);

-- ---------------------------------------------------------------------------
-- Copies on external drives. verified_at is set only after the copy on the
-- drive was re-read and its SHA-256 matched files.sha256.
-- ---------------------------------------------------------------------------
CREATE TABLE volume_copies (
    id             INTEGER PRIMARY KEY,
    file_id        INTEGER NOT NULL REFERENCES files(id),
    volume_id      TEXT NOT NULL REFERENCES volumes(id),
    rel_path       TEXT NOT NULL,                  -- 'AAAA/MM/fotos/2024-05-01_1012_IMG_1234.HEIC'
    copied_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    verified_at    TEXT,
    last_check_at  TEXT,
    last_check_ok  INTEGER CHECK (last_check_ok IN (0, 1)),
    UNIQUE (file_id, volume_id),
    UNIQUE (volume_id, rel_path)
) STRICT;

CREATE INDEX volume_copies_volume ON volume_copies (volume_id);

-- Inviolable rule 3, enforced by the database itself: the server copy of a
-- file can only be dropped (rel_path -> NULL) if a verified copy exists on a
-- drive, or if the item was purged after its 30 days in the trash.
CREATE TRIGGER files_guard_server_delete
BEFORE UPDATE OF rel_path ON files
WHEN OLD.rel_path IS NOT NULL AND NEW.rel_path IS NULL
 AND (SELECT state FROM items WHERE id = OLD.item_id) <> 'purged'
 AND NOT EXISTS (
        SELECT 1 FROM volume_copies vc
        WHERE vc.file_id = OLD.id AND vc.verified_at IS NOT NULL
     )
BEGIN
    SELECT RAISE(ABORT, 'file has no verified copy on a drive; refusing to drop server copy');
END;

CREATE TRIGGER files_never_deleted
BEFORE DELETE ON files
BEGIN
    SELECT RAISE(ABORT, 'file rows are never deleted');
END;

-- Archiving needs every file of the item verified on that volume.
CREATE TRIGGER items_archive_needs_verified_copies
BEFORE UPDATE OF state ON items
WHEN NEW.state = 'archived' AND OLD.state <> 'archived'
 AND EXISTS (
        SELECT 1 FROM files f
        WHERE f.item_id = NEW.id
          AND NOT EXISTS (
                SELECT 1 FROM volume_copies vc
                WHERE vc.file_id = f.id AND vc.volume_id = NEW.volume_id
                  AND vc.verified_at IS NOT NULL
          )
     )
BEGIN
    SELECT RAISE(ABORT, 'item has files without a verified copy on this volume');
END;

-- ---------------------------------------------------------------------------
-- Health checks of drives ("última verificação completa há 8 meses · 0 problemas")
-- ---------------------------------------------------------------------------
CREATE TABLE volume_checks (
    id             INTEGER PRIMARY KEY,
    volume_id      TEXT NOT NULL REFERENCES volumes(id),
    kind           TEXT NOT NULL CHECK (kind IN ('partial', 'full')),
    started_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at    TEXT,
    files_checked  INTEGER NOT NULL DEFAULT 0,
    problems       INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE INDEX volume_checks_volume ON volume_checks (volume_id, started_at DESC);

-- ---------------------------------------------------------------------------
-- Dedup layer 1: (original name, client creation date, size) -> item.
-- Used only to skip obvious re-sends in the daily backup; never as proof
-- that something is safe to delete from the iPhone (that needs the hash).
-- ---------------------------------------------------------------------------
CREATE TABLE fingerprints (
    original_name      TEXT NOT NULL,
    client_created_at  TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL,
    item_id            INTEGER NOT NULL REFERENCES items(id),
    PRIMARY KEY (original_name, client_created_at, size_bytes)
) STRICT, WITHOUT ROWID;

CREATE INDEX fingerprints_item ON fingerprints (item_id);

-- Every time something sent already existed, at which layer it was caught.
CREATE TABLE dedupe_hits (
    id             INTEGER PRIMARY KEY,
    session_id     INTEGER REFERENCES upload_sessions(id) ON DELETE SET NULL,
    item_id        INTEGER NOT NULL REFERENCES items(id),
    layer          INTEGER NOT NULL CHECK (layer BETWEEN 1 AND 4),
    original_name  TEXT,
    at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX dedupe_hits_session ON dedupe_hits (session_id);

-- ---------------------------------------------------------------------------
-- Triage suggestions (phase 2): near-duplicates, screenshots, bursts, WhatsApp
-- media, large videos. Suggestions never discard anything by themselves.
-- ---------------------------------------------------------------------------
CREATE TABLE suggestions (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL
                 CHECK (kind IN ('near-duplicate', 'screenshot', 'burst', 'whatsapp', 'large-video')),
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at  TEXT
) STRICT;

CREATE TABLE suggestion_items (
    suggestion_id  INTEGER NOT NULL REFERENCES suggestions(id) ON DELETE CASCADE,
    item_id        INTEGER NOT NULL REFERENCES items(id),
    PRIMARY KEY (suggestion_id, item_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX suggestion_items_item ON suggestion_items (item_id);

-- ---------------------------------------------------------------------------
-- Event log: every destructive or moving operation. Append-only.
-- ---------------------------------------------------------------------------
CREATE TABLE events (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    actor       TEXT NOT NULL,          -- 'server', 'web', 'mac-app', 'iphone-shortcut'
    action      TEXT NOT NULL,          -- 'move', 'trash', 'restore', 'purge', 'archive-copy', …
    item_id     INTEGER,
    file_id     INTEGER,
    volume_id   TEXT,
    sha256      TEXT,
    from_path   TEXT,
    to_path     TEXT,
    details     TEXT CHECK (details IS NULL OR json_valid(details))
) STRICT;

CREATE INDEX events_at   ON events (at);
CREATE INDEX events_item ON events (item_id) WHERE item_id IS NOT NULL;

CREATE TRIGGER events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;

CREATE TRIGGER events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;

-- ---------------------------------------------------------------------------
-- Persistent job queue for heavy work (thumbnails, metadata, OCR…).
-- Survives the process being killed by Android: 'running' jobs older than a
-- lease are put back to 'pending' on startup.
-- ---------------------------------------------------------------------------
CREATE TABLE jobs (
    id                  INTEGER PRIMARY KEY,
    kind                TEXT NOT NULL
                        CHECK (kind IN ('metadata', 'thumbnail', 'phash', 'text', 'ocr',
                                        'place', 'embedding')),
    item_id             INTEGER NOT NULL REFERENCES items(id),
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'done', 'failed')),
    priority            INTEGER NOT NULL DEFAULT 100,      -- lower runs first
    attempts            INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    only_when_charging  INTEGER NOT NULL DEFAULT 0 CHECK (only_when_charging IN (0, 1)),
    run_after           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at          TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (kind, item_id)
) STRICT;

CREATE INDEX jobs_queue ON jobs (status, priority, run_after);

-- ---------------------------------------------------------------------------
-- Small key/value store (last daily backup time, etc.)
-- ---------------------------------------------------------------------------
CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT, WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- Full-text search. rowid = items.id. Accent-insensitive ("sao" finds "São"),
-- with prefix indexes for search-as-you-type. 'body' is filled in phase 6
-- (document text, OCR).
-- ---------------------------------------------------------------------------
CREATE VIRTUAL TABLE search_fts USING fts5(
    name,
    place,
    camera,
    body,
    tokenize = 'unicode61 remove_diacritics 2',
    prefix = '2 3'
);

CREATE TRIGGER items_fts_insert
AFTER INSERT ON items
BEGIN
    INSERT INTO search_fts (rowid, name, place, camera, body)
    VALUES (
        NEW.id,
        trim(NEW.original_name || ' ' || coalesce(NEW.standard_name, '')),
        coalesce(NEW.place, ''),
        trim(coalesce(NEW.camera_make, '') || ' ' || coalesce(NEW.camera_model, '')),
        ''
    );
END;

CREATE TRIGGER items_fts_update
AFTER UPDATE OF original_name, standard_name, place, camera_make, camera_model ON items
BEGIN
    UPDATE search_fts SET
        name   = trim(NEW.original_name || ' ' || coalesce(NEW.standard_name, '')),
        place  = coalesce(NEW.place, ''),
        camera = trim(coalesce(NEW.camera_make, '') || ' ' || coalesce(NEW.camera_model, ''))
    WHERE rowid = NEW.id;
END;
