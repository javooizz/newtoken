CREATE TABLE IF NOT EXISTS admins (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    email VARCHAR(190) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'owner',
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    last_login_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uq_admins_username (username),
    UNIQUE KEY uq_admins_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    oidc_subject VARCHAR(64) NOT NULL,
    email VARCHAR(190) NOT NULL,
    email_domain VARCHAR(128) NOT NULL,
    full_name VARCHAR(190) NOT NULL,
    given_name VARCHAR(100) NULL,
    family_name VARCHAR(100) NULL,
    password_hash VARCHAR(255) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    activated_by_card_id BIGINT UNSIGNED NULL,
    origin_client_id VARCHAR(128) NULL,
    activated_at DATETIME NULL,
    last_login_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uq_users_subject (oidc_subject),
    UNIQUE KEY uq_users_email (email),
    KEY idx_users_domain (email_domain),
    KEY idx_users_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS card_keys (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    batch_no VARCHAR(64) NOT NULL,
    card_prefix VARCHAR(8) NOT NULL,
    card_suffix VARCHAR(8) NOT NULL,
    card_hash CHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'unused',
    expires_at DATETIME NULL,
    used_by_user_id BIGINT UNSIGNED NULL,
    used_at DATETIME NULL,
    exported_at DATETIME NULL,
    note VARCHAR(255) NULL,
    created_by_admin_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uq_card_hash (card_hash),
    KEY idx_cards_batch (batch_no),
    KEY idx_cards_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auth_codes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    client_id VARCHAR(128) NOT NULL,
    code_hash CHAR(64) NOT NULL,
    redirect_uri VARCHAR(500) NOT NULL,
    scope VARCHAR(255) NOT NULL,
    nonce VARCHAR(255) NOT NULL,
    code_challenge VARCHAR(255) NOT NULL,
    code_challenge_method VARCHAR(16) NOT NULL,
    expires_at DATETIME NOT NULL,
    used_at DATETIME NULL,
    ip_address VARCHAR(64) NULL,
    user_agent_hash CHAR(64) NULL,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_auth_codes_hash (code_hash),
    KEY idx_auth_codes_user (user_id),
    KEY idx_auth_codes_exp (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS access_tokens (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    client_id VARCHAR(128) NOT NULL,
    token_hash CHAR(64) NOT NULL,
    scope VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    revoked_at DATETIME NULL,
    ip_address VARCHAR(64) NULL,
    user_agent_hash CHAR(64) NULL,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_access_tokens_hash (token_hash),
    KEY idx_access_tokens_user (user_id),
    KEY idx_access_tokens_exp (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    actor_type VARCHAR(16) NOT NULL,
    actor_id BIGINT UNSIGNED NULL,
    action VARCHAR(64) NOT NULL,
    target_type VARCHAR(32) NULL,
    target_id VARCHAR(64) NULL,
    details_json TEXT NULL,
    ip_address VARCHAR(64) NULL,
    created_at DATETIME NOT NULL,
    KEY idx_audit_actor (actor_type, actor_id),
    KEY idx_audit_action (action),
    KEY idx_audit_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS oidc_clients (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id VARCHAR(128) NOT NULL,
    client_secret_enc TEXT NOT NULL,
    name VARCHAR(190) NOT NULL,
    redirect_uris TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    note VARCHAR(255) NULL,
    created_by_admin_id BIGINT UNSIGNED NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uq_oidc_clients_client_id (client_id),
    KEY idx_oidc_clients_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS oidc_client_domains (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id VARCHAR(128) NOT NULL,
    domain_normalized VARCHAR(255) NOT NULL,
    domain_raw VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_client_domains_norm (domain_normalized),
    KEY idx_client_domains_client (client_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
