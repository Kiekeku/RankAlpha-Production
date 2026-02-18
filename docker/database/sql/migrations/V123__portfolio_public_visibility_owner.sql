/* ------------------------------------------------------------
   V123__portfolio_public_visibility_owner.sql
   - Add publication and ownership metadata to rankalpha.portfolio.
   - Public portfolios are intended for MODEL portfolios only.
   - BROKER portfolios must never be public/visible.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

ALTER TABLE rankalpha.portfolio
  ADD COLUMN IF NOT EXISTS is_public boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS is_visible boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS portfolio_owner_id bigint NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_portfolio_owner_user'
      AND conrelid = 'rankalpha.portfolio'::regclass
  ) THEN
    ALTER TABLE rankalpha.portfolio
      ADD CONSTRAINT fk_portfolio_owner_user
        FOREIGN KEY (portfolio_owner_id)
        REFERENCES rankalpha.auth_user(user_id)
        ON DELETE SET NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_portfolio_visible_implies_public'
      AND conrelid = 'rankalpha.portfolio'::regclass
  ) THEN
    ALTER TABLE rankalpha.portfolio
      ADD CONSTRAINT ck_portfolio_visible_implies_public
        CHECK (NOT is_visible OR is_public);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_portfolio_public_requires_model'
      AND conrelid = 'rankalpha.portfolio'::regclass
  ) THEN
    ALTER TABLE rankalpha.portfolio
      ADD CONSTRAINT ck_portfolio_public_requires_model
        CHECK (NOT is_public OR portfolio_kind = 'MODEL');
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_portfolio_broker_not_public'
      AND conrelid = 'rankalpha.portfolio'::regclass
  ) THEN
    ALTER TABLE rankalpha.portfolio
      ADD CONSTRAINT ck_portfolio_broker_not_public
        CHECK (
          portfolio_kind <> 'BROKER'
          OR (is_public IS FALSE AND is_visible IS FALSE)
        );
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_portfolio_public_owner_null'
      AND conrelid = 'rankalpha.portfolio'::regclass
  ) THEN
    ALTER TABLE rankalpha.portfolio
      ADD CONSTRAINT ck_portfolio_public_owner_null
        CHECK (NOT is_public OR portfolio_owner_id IS NULL);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_portfolio_public_visible
  ON rankalpha.portfolio (is_public, is_visible)
  WHERE is_public IS TRUE;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

