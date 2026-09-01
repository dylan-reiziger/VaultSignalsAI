-- Authentication and account schema used by VaultSignalsAI.
-- The application auto-migrates these tables at runtime in app.py.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    zipcode TEXT NOT NULL,
    address TEXT NOT NULL,
    discord_username TEXT,
    discord_tag TEXT,
    verified INTEGER NOT NULL DEFAULT 1,
    is_admin INTEGER NOT NULL DEFAULT 0,
    data_consent_accepted INTEGER NOT NULL DEFAULT 0,
    data_consent_accepted_at TIMESTAMP,
    verification_token TEXT,
    verification_token_hash TEXT,
    verification_token_created_at TIMESTAMP,
    full_name_enc TEXT,
    zipcode_enc TEXT,
    address_enc TEXT,
    discord_username_enc TEXT,
    preferred_currency_code TEXT,
    preferred_view_mode TEXT NOT NULL DEFAULT 'normal',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS account_security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER,
    event_type TEXT NOT NULL,
    event_status TEXT NOT NULL,
    ip_hash TEXT,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS auth_rate_limits (
    client_key_hash TEXT PRIMARY KEY,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    user_agent TEXT,
    expires_at TIMESTAMP NOT NULL,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS discord_member_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_username TEXT NOT NULL UNIQUE,
    discord_tag TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS account_discord_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL UNIQUE,
    discord_username TEXT,
    verification_status TEXT NOT NULL DEFAULT 'pending',
    verified_tag TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL DEFAULT 'system_registry',
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS account_custom_badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    short_label TEXT NOT NULL,
    icon TEXT,
    tone TEXT NOT NULL DEFAULT 'royal',
    achievement TEXT,
    badge_group TEXT NOT NULL DEFAULT 'custom',
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, code),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email);
CREATE INDEX IF NOT EXISTS idx_accounts_token_hash ON accounts(verification_token_hash);
CREATE INDEX IF NOT EXISTS idx_security_events_account_id ON account_security_events(account_id);
CREATE INDEX IF NOT EXISTS idx_auth_rate_limits_updated_at ON auth_rate_limits(updated_at);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_account_id ON auth_tokens(account_id);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires_at ON auth_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_discord_registry_username ON discord_member_registry(discord_username);
CREATE INDEX IF NOT EXISTS idx_discord_verifications_account ON account_discord_verifications(account_id);
CREATE INDEX IF NOT EXISTS idx_account_custom_badges_account ON account_custom_badges(account_id);
