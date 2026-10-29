-- Version 2: resumable uploads, per-session file tracking, login sessions and
-- API tokens, storage roots (microSD), suggestion grouping.

-- Resumable uploads (tus). The bytes live in tmp/uploads/<id>.part; the file
-- size on disk is the source of truth for the offset, so a killed process
-- resumes exactly where the disk says it stopped.
CREATE TABLE uploads (
    id               TEXT PRIMARY KEY,                  -- random hex
    length           INTEGER NOT NULL CHECK (length >= 0),
    filename         TEXT NOT NULL,
    mime             TEXT,
    client_modified  TEXT,                              -- ISO, from lastModified
    client_sha256    TEXT CHECK (client_sha256 IS NULL OR length(client_sha256) = 64),
    source           TEXT NOT NULL,
    session_id       INTEGER REFERENCES upload_sessions(id) ON DELETE SET NULL,
    status           TEXT NOT NULL DEFAULT 'receiving'
                     CHECK (status IN ('receiving', 'processing', 'done', 'failed', 'cancelled')),
    result           TEXT CHECK (result IS NULL OR json_valid(result)),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX uploads_status ON uploads (status, updated_at);

-- Which client files a session has confirmed by hash, so retries never count
-- twice towards "1.243 de 1.243 recebidos e verificados". client_key is the
-- client's own identifier of the file (its path), defaulting to the hash; two
-- identical photos on the iPhone are two client files with the same hash.
CREATE TABLE session_files (
    session_id  INTEGER NOT NULL REFERENCES upload_sessions(id) ON DELETE CASCADE,
    client_key  TEXT NOT NULL,
    sha256      TEXT NOT NULL CHECK (length(sha256) = 64),
    outcome     TEXT NOT NULL CHECK (outcome IN ('new', 'existing', 'attached')),
    at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (session_id, client_key)
) STRICT, WITHOUT ROWID;

-- Login sessions (browser cookie) and long-lived API tokens (iPhone
-- Shortcuts, Mac app). Only the SHA-256 of the token is stored.
CREATE TABLE auth_tokens (
    id            INTEGER PRIMARY KEY,
    token_hash    TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
    kind          TEXT NOT NULL CHECK (kind IN ('session', 'api')),
    label         TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_used_at  TEXT,
    expires_at    TEXT,
    revoked_at    TEXT
) STRICT;

-- Where on the server a file lives: 'main' = data dir, 'sd' = microSD card.
ALTER TABLE files ADD COLUMN root TEXT NOT NULL DEFAULT 'main' CHECK (root IN ('main', 'sd'));

-- One open suggestion per (kind, group): all screenshots together, one group
-- per burst, one per near-duplicate cluster.
ALTER TABLE suggestions ADD COLUMN group_key TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX suggestions_open_group ON suggestions (kind, group_key) WHERE status = 'open';
