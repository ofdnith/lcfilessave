-- Version 5: health checks of the files kept on the server (mainly the microSD),
-- and two new push-notification topics.

-- Last time this copy was re-read and its SHA-256 compared with the catalog.
-- check_ok = 0: the copy is damaged or missing; it no longer counts as "stored
-- safely", so the daily backup sends it again and the upload repairs it.
ALTER TABLE files ADD COLUMN checked_at TEXT;
ALTER TABLE files ADD COLUMN check_ok INTEGER CHECK (check_ok IN (0, 1));

CREATE INDEX files_check_order ON files (root, checked_at) WHERE rel_path IS NOT NULL;

-- New topics start switched on for everyone who already gets notifications.
UPDATE push_subscriptions
   SET topics = json_insert(topics, '$[#]', 'entrada', '$[#]', 'cartao');
