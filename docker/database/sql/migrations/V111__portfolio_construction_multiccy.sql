-- ======================================================================
--  V111__portfolio_construction_multiccy.sql
--  Portfolio construction + deployments + multi-currency support.
--  Adds:
--    - dim_stock.currency_code (local/listing currency)
--    - portfolio portfolio_kind + broker metadata
--    - portfolio_cash_position (multi-currency cash line items)
--    - versioned portfolio policies (SCD2)
--    - daily portfolio runs (drafts + approvals)
--    - per-run positions (equity + cash) and per-line order intents
--    - model->broker deployments with sleeve portfolios
--    - sleeve attribution + internal cross records
--  Idempotent migration: safe to re-run in dev/CI.
-- ======================================================================

SET search_path = rankalpha, public;

-- Required for UUID default
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- Required for range exclusion constraints
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ───────────────────────────────────────────────────────────────────────
-- 1) ENUM TYPES
-- ───────────────────────────────────────────────────────────────────────
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'portfolio_kind'
      AND n.nspname = 'rankalpha'
  ) THEN
    CREATE TYPE rankalpha.portfolio_kind AS ENUM ('BROKER', 'MODEL', 'SLEEVE');
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'portfolio_run_kind'
      AND n.nspname = 'rankalpha'
  ) THEN
    CREATE TYPE rankalpha.portfolio_run_kind AS ENUM ('MODEL_CONSTRUCTION', 'BROKER_REBALANCE', 'SLEEVE_BUILD');
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'portfolio_run_status'
      AND n.nspname = 'rankalpha'
  ) THEN
    CREATE TYPE rankalpha.portfolio_run_status AS ENUM ('DRAFT', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'SUPERSEDED');
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'approval_status'
      AND n.nspname = 'rankalpha'
  ) THEN
    CREATE TYPE rankalpha.approval_status AS ENUM ('PENDING', 'APPROVED', 'REJECTED');
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'portfolio_position_role'
      AND n.nspname = 'rankalpha'
  ) THEN
    CREATE TYPE rankalpha.portfolio_position_role AS ENUM ('BASELINE', 'TARGET');
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'portfolio_instrument_type'
      AND n.nspname = 'rankalpha'
  ) THEN
    CREATE TYPE rankalpha.portfolio_instrument_type AS ENUM ('EQUITY', 'CASH');
  END IF;
END$$;

-- ───────────────────────────────────────────────────────────────────────
-- 2) MULTI-CURRENCY: dim_stock.currency_code (local/listing currency)
-- ───────────────────────────────────────────────────────────────────────
ALTER TABLE rankalpha.dim_stock
  ADD COLUMN IF NOT EXISTS currency_code CHAR(3) NOT NULL DEFAULT 'USD';

COMMENT ON COLUMN rankalpha.dim_stock.currency_code IS
  'ISO-4217 listing currency for the security; fact_security_price is stored in this currency.';

-- ───────────────────────────────────────────────────────────────────────
-- 3) PORTFOLIO: kind + broker metadata
-- ───────────────────────────────────────────────────────────────────────
ALTER TABLE rankalpha.portfolio
  ADD COLUMN IF NOT EXISTS portfolio_kind rankalpha.portfolio_kind NOT NULL DEFAULT 'BROKER',
  ADD COLUMN IF NOT EXISTS broker_name VARCHAR(32),
  ADD COLUMN IF NOT EXISTS broker_account_id VARCHAR(64);

COMMENT ON COLUMN rankalpha.portfolio.portfolio_kind IS
  'BROKER=real brokerage account; MODEL=model portfolio; SLEEVE=shadow book for a deployment.';
COMMENT ON COLUMN rankalpha.portfolio.broker_name IS
  'Broker identifier (e.g., IBKR) when portfolio_kind=BROKER.';
COMMENT ON COLUMN rankalpha.portfolio.broker_account_id IS
  'External broker account id when portfolio_kind=BROKER.';

-- ───────────────────────────────────────────────────────────────────────
-- 4) CURRENT CASH POSITIONS (multi-currency line items)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rankalpha.portfolio_cash_position (
  portfolio_id    UUID NOT NULL REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,
  currency_code   CHAR(3) NOT NULL,
  cash_amount     NUMERIC(20,4) NOT NULL,
  last_update_ts  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (portfolio_id, currency_code)
);

CREATE INDEX IF NOT EXISTS ix_cashpos_portfolio
  ON rankalpha.portfolio_cash_position (portfolio_id);

COMMENT ON TABLE rankalpha.portfolio_cash_position IS
  'Current cash balances by currency for a portfolio (supports margin via negative cash_amount).';

-- ───────────────────────────────────────────────────────────────────────
-- 5) VERSIONED PORTFOLIO POLICY (SCD2)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rankalpha.portfolio_policy_version (
  policy_id             BIGSERIAL PRIMARY KEY,
  portfolio_id          UUID NOT NULL REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,
  effective_from        DATE NOT NULL,
  effective_to          DATE,
  target_vol            NUMERIC(12,6),
  target_gross_exposure NUMERIC(12,6),
  target_net_exposure   NUMERIC(12,6),
  constraints           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by            TEXT,
  validity              DATERANGE GENERATED ALWAYS AS
                        (daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[)')) STORED,
  CONSTRAINT uq_policy_version UNIQUE (portfolio_id, effective_from)
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ex_portfolio_policy_validity'
  ) THEN
    ALTER TABLE rankalpha.portfolio_policy_version
      ADD CONSTRAINT ex_portfolio_policy_validity
      EXCLUDE USING gist (portfolio_id WITH =, validity WITH &&);
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_policy_portfolio_from
  ON rankalpha.portfolio_policy_version (portfolio_id, effective_from DESC);

-- ───────────────────────────────────────────────────────────────────────
-- 6) MODEL -> BROKER DEPLOYMENTS (SLEEVES)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rankalpha.portfolio_deployment (
  deployment_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  broker_portfolio_id UUID NOT NULL REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,
  model_portfolio_id  UUID NOT NULL REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,
  sleeve_portfolio_id UUID NOT NULL REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,
  allocation_pct      NUMERIC(6,2) NOT NULL CHECK (allocation_pct >= 0 AND allocation_pct <= 100),
  effective_from      DATE NOT NULL DEFAULT current_date,
  effective_to        DATE,
  is_active           BOOLEAN NOT NULL DEFAULT TRUE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by          TEXT,
  validity            DATERANGE GENERATED ALWAYS AS
                      (daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[)')) STORED,
  CONSTRAINT uq_deployment_sleeve UNIQUE (sleeve_portfolio_id)
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ex_portfolio_deployment_validity'
  ) THEN
    ALTER TABLE rankalpha.portfolio_deployment
      ADD CONSTRAINT ex_portfolio_deployment_validity
      EXCLUDE USING gist (broker_portfolio_id WITH =, model_portfolio_id WITH =, validity WITH &&);
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_deploy_broker
  ON rankalpha.portfolio_deployment (broker_portfolio_id, effective_from DESC);
CREATE INDEX IF NOT EXISTS ix_deploy_model
  ON rankalpha.portfolio_deployment (model_portfolio_id, effective_from DESC);

COMMENT ON TABLE rankalpha.portfolio_deployment IS
  'Deployment of a MODEL portfolio into a BROKER account via a SLEEVE shadow book.';

-- ───────────────────────────────────────────────────────────────────────
-- 7) DAILY RUNS (drafts + approvals)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rankalpha.portfolio_run (
  run_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  portfolio_id UUID NOT NULL REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,
  run_kind     rankalpha.portfolio_run_kind NOT NULL,
  as_of_date   DATE NOT NULL,
  run_seq      INT NOT NULL DEFAULT 1,
  status       rankalpha.portfolio_run_status NOT NULL DEFAULT 'DRAFT',
  policy_id    BIGINT REFERENCES rankalpha.portfolio_policy_version(policy_id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by   TEXT,
  approved_at  TIMESTAMPTZ,
  approved_by  TEXT,
  CONSTRAINT uq_portfolio_run UNIQUE (portfolio_id, run_kind, as_of_date, run_seq)
);

-- Only one approved run per portfolio/kind/day.
CREATE UNIQUE INDEX IF NOT EXISTS ux_portfolio_run_one_approved
  ON rankalpha.portfolio_run (portfolio_id, run_kind, as_of_date)
  WHERE status = 'APPROVED';

CREATE INDEX IF NOT EXISTS ix_portfolio_run_status
  ON rankalpha.portfolio_run (status, as_of_date DESC);

-- ───────────────────────────────────────────────────────────────────────
-- 8) BROKER RUN INPUTS (which model runs + allocations were used)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rankalpha.portfolio_run_input (
  broker_run_id            UUID NOT NULL REFERENCES rankalpha.portfolio_run(run_id) ON DELETE CASCADE,
  deployment_id            UUID NOT NULL REFERENCES rankalpha.portfolio_deployment(deployment_id) ON DELETE CASCADE,
  model_run_id             UUID NOT NULL REFERENCES rankalpha.portfolio_run(run_id) ON DELETE CASCADE,
  allocation_pct_snapshot  NUMERIC(6,2) NOT NULL CHECK (allocation_pct_snapshot >= 0 AND allocation_pct_snapshot <= 100),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (broker_run_id, deployment_id)
);

CREATE INDEX IF NOT EXISTS ix_run_input_model_run
  ON rankalpha.portfolio_run_input (model_run_id);

-- ───────────────────────────────────────────────────────────────────────
-- 9) RUN POSITIONS (equity + cash; baseline + target)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rankalpha.portfolio_run_position (
  position_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  run_id             UUID NOT NULL REFERENCES rankalpha.portfolio_run(run_id) ON DELETE CASCADE,
  position_role      rankalpha.portfolio_position_role NOT NULL,
  instrument_type    rankalpha.portfolio_instrument_type NOT NULL,
  stock_key          INT REFERENCES rankalpha.dim_stock(stock_key),
  currency_code      CHAR(3),
  quantity           NUMERIC(20,4) NOT NULL,
  price_close_local  NUMERIC(20,4),
  market_value_local NUMERIC(20,4),
  market_value_base  NUMERIC(20,4),
  weight_pct         NUMERIC(12,6),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_runpos_instrument CHECK (
    (instrument_type = 'EQUITY' AND stock_key IS NOT NULL AND currency_code IS NULL)
    OR
    (instrument_type = 'CASH'   AND stock_key IS NULL AND currency_code IS NOT NULL)
  )
);

-- Uniqueness by instrument type (partial unique indexes).
CREATE UNIQUE INDEX IF NOT EXISTS ux_runpos_equity
  ON rankalpha.portfolio_run_position (run_id, position_role, stock_key)
  WHERE instrument_type = 'EQUITY';

CREATE UNIQUE INDEX IF NOT EXISTS ux_runpos_cash
  ON rankalpha.portfolio_run_position (run_id, position_role, currency_code)
  WHERE instrument_type = 'CASH';

CREATE INDEX IF NOT EXISTS ix_runpos_run_role
  ON rankalpha.portfolio_run_position (run_id, position_role);

-- ───────────────────────────────────────────────────────────────────────
-- 10) ORDER INTENTS (per-line approvals)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rankalpha.portfolio_order_intent (
  order_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  run_id             UUID NOT NULL REFERENCES rankalpha.portfolio_run(run_id) ON DELETE CASCADE,
  line_no            INT NOT NULL,
  stock_key          INT NOT NULL REFERENCES rankalpha.dim_stock(stock_key),
  action             rankalpha.trade_action NOT NULL,
  order_type         VARCHAR(16) NOT NULL DEFAULT 'MARKET',
  time_in_force      VARCHAR(12) NOT NULL DEFAULT 'DAY',
  limit_price        NUMERIC(20,4),
  stop_trigger_price NUMERIC(20,4),
  qty_shares         NUMERIC(20,4) NOT NULL,
  target_weight_after NUMERIC(12,6),
  approval_status    rankalpha.approval_status NOT NULL DEFAULT 'PENDING',
  approved_at        TIMESTAMPTZ,
  approved_by        TEXT,
  notes              TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_order_line UNIQUE (run_id, line_no)
);

CREATE INDEX IF NOT EXISTS ix_order_run_approval
  ON rankalpha.portfolio_order_intent (run_id, approval_status, line_no);

CREATE TABLE IF NOT EXISTS rankalpha.portfolio_order_intent_source (
  order_id          UUID NOT NULL REFERENCES rankalpha.portfolio_order_intent(order_id) ON DELETE CASCADE,
  recommendation_id UUID NOT NULL REFERENCES rankalpha.fact_trade_recommendation(recommendation_id),
  weight_component  NUMERIC(12,6),
  PRIMARY KEY (order_id, recommendation_id)
);

CREATE INDEX IF NOT EXISTS ix_order_source_rec
  ON rankalpha.portfolio_order_intent_source (recommendation_id);

CREATE TABLE IF NOT EXISTS rankalpha.portfolio_order_intent_alloc (
  order_id         UUID NOT NULL REFERENCES rankalpha.portfolio_order_intent(order_id) ON DELETE CASCADE,
  deployment_id    UUID NOT NULL REFERENCES rankalpha.portfolio_deployment(deployment_id) ON DELETE CASCADE,
  qty_component    NUMERIC(20,4) NOT NULL,
  weight_component NUMERIC(12,6),
  PRIMARY KEY (order_id, deployment_id)
);

-- ───────────────────────────────────────────────────────────────────────
-- 11) INTERNAL CROSSES BETWEEN SLEEVES (priced at as-of close)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rankalpha.fact_internal_cross (
  cross_id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  broker_run_id            UUID NOT NULL REFERENCES rankalpha.portfolio_run(run_id) ON DELETE CASCADE,
  stock_key                INT NOT NULL REFERENCES rankalpha.dim_stock(stock_key),
  cross_qty                NUMERIC(20,4) NOT NULL CHECK (cross_qty > 0),
  price_close_local        NUMERIC(20,4) NOT NULL,
  currency_code            CHAR(3) NOT NULL,
  buy_sleeve_portfolio_id  UUID NOT NULL REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,
  sell_sleeve_portfolio_id UUID NOT NULL REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,
  buy_trade_id             UUID REFERENCES rankalpha.fact_portfolio_trade(trade_id),
  sell_trade_id            UUID REFERENCES rankalpha.fact_portfolio_trade(trade_id),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_internal_cross_broker_run
  ON rankalpha.fact_internal_cross (broker_run_id);

COMMENT ON TABLE rankalpha.fact_internal_cross IS
  'Explicit internal crosses between sleeves when model deployments offset in a broker account.';

-- ───────────────────────────────────────────────────────────────────────
-- 12) LINK/ALLOCATE ACTUAL FILLS BACK TO INTENT + SLEEVES
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rankalpha.portfolio_trade_link (
  trade_id   UUID PRIMARY KEY REFERENCES rankalpha.fact_portfolio_trade(trade_id) ON DELETE CASCADE,
  order_id   UUID REFERENCES rankalpha.portfolio_order_intent(order_id),
  linked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_trade_link_order
  ON rankalpha.portfolio_trade_link (order_id);

CREATE TABLE IF NOT EXISTS rankalpha.portfolio_trade_alloc (
  trade_id            UUID NOT NULL REFERENCES rankalpha.fact_portfolio_trade(trade_id) ON DELETE CASCADE,
  deployment_id       UUID NOT NULL REFERENCES rankalpha.portfolio_deployment(deployment_id) ON DELETE CASCADE,
  qty_alloc           NUMERIC(20,4) NOT NULL,
  notional_alloc_base NUMERIC(20,4),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (trade_id, deployment_id)
);

CREATE INDEX IF NOT EXISTS ix_trade_alloc_deploy
  ON rankalpha.portfolio_trade_alloc (deployment_id);

-- ======================================================================
--  END OF MIGRATION
-- ======================================================================

