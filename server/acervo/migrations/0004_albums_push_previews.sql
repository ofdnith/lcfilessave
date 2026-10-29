-- Version 4: medium previews kept forever, albums, Web Push subscriptions.

-- 1024 px WebP preview, kept even after the original goes to a drive.
ALTER TABLE items ADD COLUMN medium_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (medium_status IN ('pending', 'ok', 'failed', 'none'));
UPDATE items SET medium_status = 'none' WHERE kind NOT IN ('photo', 'video') OR state = 'purged';

-- Albums only group items; deleting an album never touches the items.
CREATE TABLE albums (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
    cover_item_id   INTEGER REFERENCES items(id),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE album_items (
    album_id  INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    item_id   INTEGER NOT NULL REFERENCES items(id),
    added_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (album_id, item_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX album_items_item ON album_items (item_id);

-- Browsers (iPhone PWA) that asked for notifications.
CREATE TABLE push_subscriptions (
    id           INTEGER PRIMARY KEY,
    endpoint     TEXT NOT NULL UNIQUE,
    p256dh       TEXT NOT NULL,
    auth         TEXT NOT NULL,
    topics       TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(topics)),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_ok_at   TEXT,
    failures     INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE INDEX items_place ON items (place) WHERE place IS NOT NULL;
CREATE INDEX items_month_day ON items (substr(captured_at, 6, 5));
