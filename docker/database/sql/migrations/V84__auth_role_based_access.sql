-- RBAC bootstrap: canonical roles + user/role assignment tables
-- Provides a shared source of truth for application security states

CREATE TABLE IF NOT EXISTS rankalpha.auth_role (
    role_id SERIAL PRIMARY KEY,
    role_name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    is_assignable BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rankalpha.auth_user (
    user_id BIGSERIAL PRIMARY KEY,
    email VARCHAR(320) NOT NULL UNIQUE,
    full_name TEXT,
    avatar_url TEXT,
    provider VARCHAR(40),
    provider_account_id TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT auth_user_email_chk CHECK (position('@' in email) > 1)
);

CREATE TABLE IF NOT EXISTS rankalpha.auth_user_role (
    user_id BIGINT NOT NULL REFERENCES rankalpha.auth_user(user_id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES rankalpha.auth_role(role_id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by BIGINT REFERENCES rankalpha.auth_user(user_id) ON DELETE SET NULL,
    note TEXT,
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_auth_user_role_role ON rankalpha.auth_user_role (role_id);

INSERT INTO rankalpha.auth_role (role_name, description, is_assignable)
VALUES
    ('viewer',   'Read-only dashboards and public data', TRUE),
    ('analyst',  'Research tooling and AI analysis controls', TRUE),
    ('operator', 'Operational controls: pipeline refresh, cache invalidation', TRUE),
    ('admin',    'Full administrative access', TRUE)
ON CONFLICT (role_name) DO NOTHING;

CREATE OR REPLACE VIEW rankalpha.vw_auth_user_roles AS
SELECT
    u.user_id,
    u.email,
    u.full_name,
    u.is_active,
    u.last_login_at,
    r.role_name,
    ur.assigned_at,
    ur.assigned_by
FROM rankalpha.auth_user AS u
JOIN rankalpha.auth_user_role AS ur ON ur.user_id = u.user_id
JOIN rankalpha.auth_role AS r ON r.role_id = ur.role_id;
