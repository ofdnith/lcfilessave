-- Version 5: a dedicated, short-lived token kind for moving the Acervo to
-- another machine. Only 'migration' tokens open /api/migration/*, and they
-- open nothing else (an iPhone Shortcut token must never be able to download
-- the certificate keys or the whole catalog).

CREATE TABLE auth_tokens_new (
    id            INTEGER PRIMARY KEY,
    token_hash    TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
    kind          TEXT NOT NULL CHECK (kind IN ('session', 'api', 'migration')),
    label         TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_used_at  TEXT,
    expires_at    TEXT,
    revoked_at    TEXT
) STRICT;

INSERT INTO auth_tokens_new (id, token_hash, kind, label, created_at, last_used_at, expires_at, revoked_at)
SELECT id, token_hash, kind, label, created_at, last_used_at, expires_at, revoked_at FROM auth_tokens;

DROP TABLE auth_tokens;
ALTER TABLE auth_tokens_new RENAME TO auth_tokens;
