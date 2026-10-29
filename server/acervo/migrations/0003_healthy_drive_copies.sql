-- Version 3: a drive copy only counts as a safe copy while it is healthy.
-- A copy that failed a later health check (last_check_ok = 0) or lives on a
-- drive flagged 'problem' no longer allows the server copy to be dropped.

DROP TRIGGER files_guard_server_delete;
CREATE TRIGGER files_guard_server_delete
BEFORE UPDATE OF rel_path ON files
WHEN OLD.rel_path IS NOT NULL AND NEW.rel_path IS NULL
 AND (SELECT state FROM items WHERE id = OLD.item_id) <> 'purged'
 AND NOT EXISTS (
        SELECT 1 FROM volume_copies vc JOIN volumes v ON v.id = vc.volume_id
        WHERE vc.file_id = OLD.id AND vc.verified_at IS NOT NULL
          AND coalesce(vc.last_check_ok, 1) = 1 AND v.status <> 'problem'
     )
BEGIN
    SELECT RAISE(ABORT, 'file has no verified copy on a drive; refusing to drop server copy');
END;

DROP TRIGGER items_archive_needs_verified_copies;
CREATE TRIGGER items_archive_needs_verified_copies
BEFORE UPDATE OF state ON items
WHEN NEW.state = 'archived' AND OLD.state <> 'archived'
 AND EXISTS (
        SELECT 1 FROM files f
        WHERE f.item_id = NEW.id
          AND NOT EXISTS (
                SELECT 1 FROM volume_copies vc JOIN volumes v ON v.id = vc.volume_id
                WHERE vc.file_id = f.id AND vc.volume_id = NEW.volume_id
                  AND vc.verified_at IS NOT NULL AND coalesce(vc.last_check_ok, 1) = 1
                  AND v.status <> 'problem'
          )
     )
BEGIN
    SELECT RAISE(ABORT, 'item has files without a verified copy on this volume');
END;
