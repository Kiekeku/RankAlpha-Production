/* ------------------------------------------------------------
   V124__portfolio_engine_extensions.sql
   - Portfolio engine support tables:
     - signal subscriptions (source_name + strategy_name routing)
     - per-run artifacts and risk reports
     - export mapping (order intent -> broker queue row)
     - per-run idea input audit (ideas can fan out to many accounts)
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- Required for daterange exclusion constraints.
CREATE EXTENSION IF NOT EXISTS btree_gist;

--------------------------------------------------------------------
-- 1) ENUM TYPES
--------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'rankalpha'
      AND t.typname = 'signal_sizing_method'
  ) THEN
    CREATE TYPE rankalpha.signal_sizing_method AS ENUM (
      'USE_SIGNAL_SIZE',
      'NOTIONAL_PCT_NAV',
      'RISK_BUDGET_BPS_INV_VOL',
      'RISK_BUDGET_BPS_FIXED'
    );
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'rankalpha'
      AND t.typname = 'risk_severity'
  ) THEN
    CREATE TYPE rankalpha.risk_severity AS ENUM ('INFO', 'WARN', 'HARD');
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'rankalpha'
      AND t.typname = 'risk_status'
  ) THEN
    CREATE TYPE rankalpha.risk_status AS ENUM ('PASS', 'WARN', 'FAIL');
  END IF;
END $$;

--------------------------------------------------------------------
-- 2) VERSIONED MODEL CONFIGURATION (selection + weighting)
--------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rankalpha.portfolio_model_config_version (
  config_id bigserial PRIMARY KEY,

  model_portfolio_id uuid NOT NULL
    REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,

  effective_from date NOT NULL,
  effective_to date NULL,

  approval_status rankalpha.approval_status NOT NULL DEFAULT 'PENDING',
  approved_at timestamptz NULL,
  approved_by text NULL,

  config jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by text NULL,

  validity daterange GENERATED ALWAYS AS (
    daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[)')
  ) STORED
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ex_model_config_validity'
      AND conrelid = 'rankalpha.portfolio_model_config_version'::regclass
  ) THEN
    ALTER TABLE rankalpha.portfolio_model_config_version
      ADD CONSTRAINT ex_model_config_validity
        EXCLUDE USING gist (model_portfolio_id WITH =, validity WITH &&);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_model_config_active
  ON rankalpha.portfolio_model_config_version (model_portfolio_id, approval_status, effective_from DESC);

--------------------------------------------------------------------
-- 3) EXTERNAL SIGNAL SUBSCRIPTIONS (routing + sizing defaults)
--------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rankalpha.portfolio_signal_subscription (
  subscription_id bigserial PRIMARY KEY,

  broker_portfolio_id uuid NOT NULL
    REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,

  source_key int4 NOT NULL
    REFERENCES rankalpha.dim_source(source_key),

  -- NULL means wildcard (match any strategy_name for that source).
  strategy_name varchar(50) NULL,
  strategy_key text GENERATED ALWAYS AS (COALESCE(strategy_name, '*')) STORED,

  enabled boolean NOT NULL DEFAULT true,

  effective_from date NOT NULL,
  effective_to date NULL,

  approval_status rankalpha.approval_status NOT NULL DEFAULT 'PENDING',
  approved_at timestamptz NULL,
  approved_by text NULL,

  sizing_method rankalpha.signal_sizing_method NOT NULL,
  allocation_pct numeric(6,2) NULL,
  default_risk_budget_bps numeric(10,4) NULL,
  default_notional_pct_nav numeric(8,4) NULL,

  constraints jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by text NULL,

  validity daterange GENERATED ALWAYS AS (
    daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[)')
  ) STORED,

  CONSTRAINT ck_sigsub_allocation_pct
    CHECK (allocation_pct IS NULL OR (allocation_pct >= 0 AND allocation_pct <= 100))
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ex_sigsub_validity'
      AND conrelid = 'rankalpha.portfolio_signal_subscription'::regclass
  ) THEN
    ALTER TABLE rankalpha.portfolio_signal_subscription
      ADD CONSTRAINT ex_sigsub_validity
        EXCLUDE USING gist (
          broker_portfolio_id WITH =,
          source_key WITH =,
          strategy_key WITH =,
          validity WITH &&
        );
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_sigsub_active
  ON rankalpha.portfolio_signal_subscription
  (broker_portfolio_id, source_key, approval_status, enabled, effective_from DESC);

--------------------------------------------------------------------
-- 4) RUN ARTIFACTS (audit + metadata)
--------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rankalpha.portfolio_run_artifact (
  run_id uuid NOT NULL
    REFERENCES rankalpha.portfolio_run(run_id) ON DELETE CASCADE,

  artifact_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  PRIMARY KEY (run_id, artifact_type)
);

--------------------------------------------------------------------
-- 5) RUN SIGNAL INPUT AUDIT (idea -> many accounts/runs)
--------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rankalpha.portfolio_run_signal_input (
  run_id uuid NOT NULL
    REFERENCES rankalpha.portfolio_run(run_id) ON DELETE CASCADE,

  recommendation_id uuid NOT NULL
    REFERENCES rankalpha.fact_trade_recommendation(recommendation_id) ON DELETE RESTRICT,

  subscription_id bigint NULL
    REFERENCES rankalpha.portfolio_signal_subscription(subscription_id) ON DELETE SET NULL,

  sized_notional_base numeric(20,4) NULL,
  sized_qty_shares int4 NULL,

  included boolean NOT NULL DEFAULT true,
  reason text NULL,

  PRIMARY KEY (run_id, recommendation_id)
);

--------------------------------------------------------------------
-- 6) RISK REPORTS (approval gate)
--------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rankalpha.portfolio_run_risk_report (
  run_id uuid PRIMARY KEY
    REFERENCES rankalpha.portfolio_run(run_id) ON DELETE CASCADE,

  evaluated_at timestamptz NOT NULL DEFAULT now(),
  status rankalpha.risk_status NOT NULL,
  summary jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS rankalpha.portfolio_run_risk_check (
  run_id uuid NOT NULL
    REFERENCES rankalpha.portfolio_run_risk_report(run_id) ON DELETE CASCADE,

  check_code text NOT NULL,
  severity rankalpha.risk_severity NOT NULL,
  status rankalpha.risk_status NOT NULL,

  metric_value numeric(20,6) NULL,
  threshold_value numeric(20,6) NULL,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,

  PRIMARY KEY (run_id, check_code)
);

--------------------------------------------------------------------
-- 7) EXPORT MAPPING (order intent -> broker queue row)
--------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rankalpha.portfolio_order_export (
  order_id uuid PRIMARY KEY
    REFERENCES rankalpha.portfolio_order_intent(order_id) ON DELETE CASCADE,

  run_id uuid NOT NULL
    REFERENCES rankalpha.portfolio_run(run_id) ON DELETE CASCADE,

  recommendation_id uuid NOT NULL
    REFERENCES rankalpha.fact_trade_recommendation(recommendation_id) ON DELETE CASCADE,

  exported_at timestamptz NOT NULL DEFAULT now(),
  exported_by text NULL
);

CREATE INDEX IF NOT EXISTS ix_order_export_run
  ON rankalpha.portfolio_order_export (run_id, exported_at DESC);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
