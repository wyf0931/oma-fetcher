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

-- ---------------------------------------------------------------------------
-- Billing: SKU -> order -> payment -> credit ledger
--
-- Domain model for pay-as-you-go credit packs. A purchase flow is:
--   sku  ->  order (pending)  ->  payment (alipay page.pay)  ->  paid
--        ->  credit_ledger grant (+units), then fetches decrement via ledger entries.
-- Amounts are stored in cents (INTEGER) to avoid float drift; the Alipay API
-- takes yuan with two decimals, converted at the boundary.
-- ---------------------------------------------------------------------------

-- SKU catalog. Only one pay-as-you-go pack is seeded today, but the table keeps
-- the catalog extensible (tiered packs, different unit prices) without a migration.
CREATE TABLE IF NOT EXISTS skus (
    id              INTEGER PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    unit            TEXT NOT NULL DEFAULT 'fetch',
    units           INTEGER NOT NULL CHECK (units > 0),
    price_cents     INTEGER NOT NULL CHECK (price_cents > 0),
    currency        TEXT NOT NULL DEFAULT 'CNY',
    payment_provider TEXT NOT NULL DEFAULT 'alipay',
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Orders. One order = one intent to buy a SKU quantity. An idempotency key lets
-- the client retry order creation safely; the out_trade_no we send to Alipay is
-- derived from the order and globally unique per merchant.
CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    sku_id          INTEGER NOT NULL,
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents > 0),
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    currency        TEXT NOT NULL DEFAULT 'CNY',
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'closed', 'refunded', 'failed')),
    out_trade_no    TEXT NOT NULL UNIQUE,
    idempotency_key TEXT,
    credits_granted INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    paid_at         TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(sku_id) REFERENCES skus(id)
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_out_trade_no ON orders(out_trade_no);
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_user_idem ON orders(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

-- Payment attempts / provider transactions for an order. Alipay may deliver
-- multiple async notifies for the same trade; each is recorded once keyed by
-- (provider, alipay trade_no, notify_id) so replays are idempotent.
CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL,
    provider        TEXT NOT NULL DEFAULT 'alipay',
    provider_trade_no TEXT,
    notify_id       TEXT,
    trade_status    TEXT,
    amount_cents    INTEGER NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'CNY',
    raw_json        TEXT NOT NULL,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    created_at      TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
);

-- A given provider trade should only ever drive one transition per notify id.
CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_provider_notify ON payments(provider, provider_trade_no, notify_id) WHERE notify_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);

-- Append-only credit ledger: +units granted on a paid order, -units consumed by
-- a fetch. The user balance is SUM(delta); the ledger doubles as the audit log.
CREATE TABLE IF NOT EXISTS credit_ledger (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    delta           INTEGER NOT NULL CHECK (delta != 0),
    reason          TEXT NOT NULL CHECK (reason IN ('grant', 'consume', 'refund', 'adjustment')),
    order_id        INTEGER,
    fetch_id        INTEGER,
    idempotency_key TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE SET NULL,
    FOREIGN KEY(fetch_id) REFERENCES fetches(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_credit_ledger_user ON credit_ledger(user_id);
CREATE INDEX IF NOT EXISTS idx_credit_ledger_order ON credit_ledger(order_id);
-- One grant per paid order; one consumption per fetch.
CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_ledger_grant ON credit_ledger(order_id, reason) WHERE reason = 'grant' AND order_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_ledger_consume ON credit_ledger(fetch_id, reason) WHERE reason = 'consume' AND fetch_id IS NOT NULL;

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
