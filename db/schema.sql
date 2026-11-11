-- Users must be defined first: fetches, api_keys, sessions, and document_owners
-- all carry a user_id foreign key pointing at this table.
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT,
    role            TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'pending', 'disabled')),
    plan            TEXT NOT NULL DEFAULT 'free',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_login_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY,
    url             TEXT NOT NULL,
    canonical_url   TEXT,
    title           TEXT,
    description     TEXT,
    author          TEXT,
    site_name       TEXT,
    hostname        TEXT NOT NULL,
    language        TEXT,
    pagetype        TEXT,
    published_at    TEXT,
    content         TEXT NOT NULL,
    content_hash    TEXT NOT NULL UNIQUE,
    tags_json       TEXT NOT NULL DEFAULT '[]',
    metadata_json   TEXT NOT NULL,
    raw_json        TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Ownerless documents (imported before user accounts existed) keep user_id NULL and
-- are only visible to administrators. New rows are always scoped to a user.
CREATE INDEX IF NOT EXISTS idx_documents_hostname ON documents(hostname);
CREATE INDEX IF NOT EXISTS idx_documents_published_at ON documents(published_at);
CREATE INDEX IF NOT EXISTS idx_documents_canonical_url ON documents(canonical_url);
CREATE INDEX IF NOT EXISTS idx_documents_site_name ON documents(site_name);

CREATE TABLE IF NOT EXISTS fetches (
    id              INTEGER PRIMARY KEY,
    document_id     INTEGER NOT NULL,
    user_id         INTEGER,
    requested_url   TEXT NOT NULL,
    final_url       TEXT,
    strategy        TEXT NOT NULL,
    status_code     INTEGER,
    content_type    TEXT,
    attempts_json   TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_fetches_document ON fetches(document_id);
CREATE INDEX IF NOT EXISTS idx_fetches_fetched_at ON fetches(fetched_at);
CREATE INDEX IF NOT EXISTS idx_fetches_user ON fetches(user_id);

CREATE TABLE IF NOT EXISTS api_keys (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER,
    name            TEXT NOT NULL,
    key_prefix      TEXT NOT NULL UNIQUE,
    key_suffix      TEXT,
    secret_hmac     TEXT NOT NULL UNIQUE,
    scopes_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    expires_at      TEXT,
    revoked_at      TEXT,
    last_used_at    TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(revoked_at, expires_at);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY,
    token_hash      TEXT NOT NULL UNIQUE,
    user_id         INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    revoked_at      TEXT,
    user_agent      TEXT,
    ip_address      TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS document_owners (
    id              INTEGER PRIMARY KEY,
    document_id     INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    first_seen_at   TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (document_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_document_owners_user ON document_owners(user_id);

CREATE TABLE IF NOT EXISTS fetch_routes (
    hostname            TEXT NOT NULL,
    target_kind         TEXT NOT NULL,
    strategy            TEXT NOT NULL,
    extraction_method   TEXT NOT NULL,
    success_count       INTEGER NOT NULL DEFAULT 1,
    failure_count       INTEGER NOT NULL DEFAULT 0,
    last_success_at     TEXT NOT NULL,
    last_failure_at     TEXT,
    expires_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    PRIMARY KEY (hostname, target_kind)
);

CREATE INDEX IF NOT EXISTS idx_fetch_routes_expires_at ON fetch_routes(expires_at);

CREATE TABLE IF NOT EXISTS app_settings (
    name        TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_search (
    document_id          INTEGER PRIMARY KEY,
    title_tokens         TEXT NOT NULL,
    description_tokens   TEXT NOT NULL,
    tags_tokens          TEXT NOT NULL,
    content_tokens       TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title_tokens,
    description_tokens,
    tags_tokens,
    content_tokens,
    content='document_search',
    content_rowid='document_id'
);

CREATE TRIGGER IF NOT EXISTS document_search_ai
AFTER INSERT ON document_search BEGIN
    INSERT INTO documents_fts(rowid, title_tokens, description_tokens, tags_tokens, content_tokens)
    VALUES (new.document_id, new.title_tokens, new.description_tokens, new.tags_tokens, new.content_tokens);
END;

CREATE TRIGGER IF NOT EXISTS document_search_au
AFTER UPDATE ON document_search BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title_tokens, description_tokens, tags_tokens, content_tokens)
    VALUES ('delete', old.document_id, old.title_tokens, old.description_tokens, old.tags_tokens, old.content_tokens);
    INSERT INTO documents_fts(rowid, title_tokens, description_tokens, tags_tokens, content_tokens)
    VALUES (new.document_id, new.title_tokens, new.description_tokens, new.tags_tokens, new.content_tokens);
END;

CREATE TRIGGER IF NOT EXISTS document_search_ad
AFTER DELETE ON document_search BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title_tokens, description_tokens, tags_tokens, content_tokens)
    VALUES ('delete', old.document_id, old.title_tokens, old.description_tokens, old.tags_tokens, old.content_tokens);
END;
