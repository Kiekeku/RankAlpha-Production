/* ──────────────────────────── 1) SCHEMA ──────────────────────────── */
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM information_schema.schemata
     WHERE schema_name = 'rankalpha'
  ) THEN
    CREATE SCHEMA rankalpha AUTHORIZATION rankalpha;
  END IF;
END
$$;


/* ──────────────────────────── 2) SEQUENCE ──────────────────────────── */
CREATE SEQUENCE IF NOT EXISTS
  rankalpha.dim_fin_metric_metric_key_seq;


/* ──────────────────────────── 3) DIMENSION: FINANCIAL METRIC ──────────────────────────── */
CREATE TABLE IF NOT EXISTS rankalpha.dim_fin_metric (
    metric_key      INT  PRIMARY KEY
                        DEFAULT nextval('rankalpha.dim_fin_metric_metric_key_seq'),
    metric_code     VARCHAR(60)  NOT NULL UNIQUE,
    metric_name     TEXT         NOT NULL,
    stmt_code       CHAR(3)      NOT NULL,
    default_unit    VARCHAR(12)  DEFAULT 'USD'
);

/* Pre-load BS metrics (idempotent via ON CONFLICT) */
INSERT INTO rankalpha.dim_fin_metric(metric_code, metric_name, stmt_code)
VALUES
  ('cash_sti',        'Cash, Cash Equivalents & Short Term Investments', 'BS'),
  ('cash',            'Cash & Cash Equivalents',                         'BS'),
  ('sti',             'Short Term Investments',                          'BS'),
  ('ar',              'Accounts Receivable, Net',                        'BS'),
  ('inventory',       'Inventories',                                     'BS'),
  ('other_cur_assets','Other Short Term Assets',                         'BS'),
  ('tot_cur_assets',  'Total Current Assets',                            'BS'),
  ('ppne',            'Property, Plant & Equipment, Net',                'BS'),
  ('lt_investments',  'Long Term Investments & Receivables',             'BS'),
  ('oth_lt_assets',   'Other Long Term Assets',                          'BS'),
  ('tot_assets',      'Total Assets',                                    'BS'),
  ('ap',              'Accounts Payable',                                'BS'),
  ('st_debt',         'Short Term Debt',                                 'BS'),
  ('oth_st_liab',     'Other Short Term Liabilities',                    'BS'),
  ('tot_cur_liab',    'Total Current Liabilities',                       'BS'),
  ('lt_debt',         'Long Term Debt',                                  'BS'),
  ('oth_lt_liab',     'Other Long Term Liabilities',                     'BS'),
  ('tot_liab',        'Total Liabilities',                               'BS'),
  ('sh_equity',       'Total Equity',                                    'BS'),
  ('tot_liab_equity', 'Total Liabilities & Equity',                      'BS')
ON CONFLICT (metric_code) DO NOTHING;

/* Loader for PL, CF & DER metrics */
WITH new_metrics(metric_code, metric_name, stmt_code) AS (
  VALUES
    /* P/L */
    ('revenue',           'Revenue',                            'PL'),
    ('cogs',              'Cost of revenue',                    'PL'),
    ('gross_profit',      'Gross Profit',                       'PL'),
    ('opex',              'Operating Expenses',                 'PL'),
    ('sga',               'Selling, General & Administrative',  'PL'),
    ('rnd',               'Research & Development',             'PL'),
    ('oper_income',       'Operating Income (Loss)',            'PL'),
    ('non_oper_income',   'Non-Operating Income (Loss)',        'PL'),
    ('pretax_income',     'Pretax Income (Loss)',               'PL'),
    ('income_tax',        'Income Tax (Expense) Benefit, net',  'PL'),
    ('net_income',        'Net Income',                         'PL'),

    /* CASH-FLOW */
    ('cf_net_inc',        'Net Income / Starting Line',             'CF'),
    ('cf_dna',            'Depreciation & Amortization',            'CF'),
    ('cf_non_cash',       'Other Non-Cash Items',                   'CF'),
    ('cf_stock_comp',     'Stock-Based Compensation',               'CF'),
    ('cf_change_wc',      'Change in Working Capital',              'CF'),
    ('cf_oper',           'Cash from Operating Activities',         'CF'),
    ('cf_capex',          'Change in Fixed Assets & Intangibles',   'CF'),
    ('cf_lt_invest',      'Net Change in Long-Term Investment',     'CF'),
    ('cf_other_invest',   'Other Investing Activities',             'CF'),
    ('cf_invest',         'Cash from Investing Activities',         'CF'),
    ('cf_div_paid',       'Dividends Paid',                         'CF'),
    ('cf_debt_net',       'Cash From (Repayment of) Debt',          'CF'),
    ('cf_equity_rep',     'Cash From (Repurchase of) Equity',       'CF'),
    ('cf_other_fin',      'Other Financing Activities',             'CF'),
    ('cf_fin',            'Cash from Financing Activities',         'CF'),
    ('cf_net_change',     'Net Changes in Cash',                    'CF'),

    /* DERIVED */
    ('gpm',               'Gross Profit Margin',                    'DER'),
    ('opm',               'Operating Margin',                       'DER'),
    ('ebitda',            'EBITDA',                                 'DER'),
    ('eps_basic',         'Earnings Per Share, Basic',              'DER'),
    ('eps_diluted',       'Earnings Per Share, Diluted',            'DER'),
    ('sales_ps',          'Sales Per Share',                        'DER'),
    ('equity_ps',         'Equity Per Share',                       'DER'),
    ('npm',               'Net Profit Margin',                      'DER'),
    ('fcf',               'Free Cash Flow',                         'DER'),
    ('fcf_ps',            'Free Cash Flow Per Share',               'DER'),
    ('fcf_to_ni',         'Free Cash Flow to Net Income',           'DER'),
    ('div_ps',            'Dividends Per Share',                    'DER'),
    ('current_ratio',     'Current Ratio',                          'DER'),
    ('piotroski_f',       'Piotroski F-Score',                      'DER'),
    ('croic',             'Cash Return On Invested Capital',        'DER'),
    ('div_payout',        'Dividend Payout Ratio',                  'DER'),
    ('net_debt_ebitda',   'Net Debt / EBITDA',                      'DER'),
    ('net_debt_ebit',     'Net Debt / EBIT',                        'DER'),
    ('roic',              'Return On Invested Capital',             'DER'),
    ('liab_equity_ratio', 'Liabilities to Equity Ratio',            'DER'),
    ('debt_ratio',        'Debt Ratio',                             'DER'),
    ('total_debt',        'Total Debt',                             'DER'),
    ('roe',               'Return on Equity',                       'DER'),
    ('roa',               'Return on Assets',                       'DER')
)
INSERT INTO rankalpha.dim_fin_metric(metric_code, metric_name, stmt_code)
SELECT metric_code, metric_name, stmt_code
  FROM new_metrics
ON CONFLICT (metric_code) DO NOTHING;


/* ──────────────────────────── 4) FACT: FUNDAMENTALS ──────────────────────────── */
/* Parent table, partitioned by RANGE(date_key) */
CREATE TABLE IF NOT EXISTS rankalpha.fact_fin_fundamentals (
    date_key     INT       NOT NULL,
    fact_id      UUID      DEFAULT uuid_generate_v4(),
    stock_key    INT       NOT NULL,
    source_key   INT       NOT NULL,
    fiscal_year  SMALLINT  NOT NULL,
    fiscal_per   VARCHAR(2) NOT NULL,
    stmt_code    CHAR(3)   NOT NULL,
    metric_key   INT       NOT NULL,
    metric_value NUMERIC(20,4) NOT NULL,
    restated     BOOLEAN   DEFAULT FALSE,
    ttm_flag     BOOLEAN   DEFAULT FALSE,
    load_ts      TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT pk_fact_finfund PRIMARY KEY (date_key, stock_key, stmt_code, metric_key),
    CONSTRAINT fk_finfund_date     FOREIGN KEY(date_key)   REFERENCES rankalpha.dim_date(date_key),
    CONSTRAINT fk_finfund_stock    FOREIGN KEY(stock_key)  REFERENCES rankalpha.dim_stock(stock_key),
    CONSTRAINT fk_finfund_source   FOREIGN KEY(source_key) REFERENCES rankalpha.dim_source(source_key),
    CONSTRAINT fk_finfund_metric   FOREIGN KEY(metric_key) REFERENCES rankalpha.dim_fin_metric(metric_key)
)
PARTITION BY RANGE (date_key);

/* First calendar‐year partition (2020) */
CREATE TABLE IF NOT EXISTS rankalpha.fact_fin_fundamentals_2020
  PARTITION OF rankalpha.fact_fin_fundamentals
  FOR VALUES FROM (20200101) TO (20210101);

/* Default catch‐all partition */
CREATE TABLE IF NOT EXISTS rankalpha.fact_fin_fundamentals_default
  PARTITION OF rankalpha.fact_fin_fundamentals DEFAULT;

/* Indexes on the parent (ONLY applies to parent, auto‐pruned by partitions) */
CREATE INDEX IF NOT EXISTS ix_finfund_stock_metric
  ON ONLY rankalpha.fact_fin_fundamentals (stock_key, metric_key);

CREATE INDEX IF NOT EXISTS ix_finfund_stmt
  ON ONLY rankalpha.fact_fin_fundamentals (stmt_code);


/* ──────────────────────────── 5) PARTITION‐GENERATION FUNCTION ──────────────────────────── */
CREATE OR REPLACE FUNCTION rankalpha.create_fin_partitions(from_year INT, thru_year INT)
RETURNS VOID LANGUAGE plpgsql AS
$$
DECLARE
    yr INT;
BEGIN
    FOR yr IN from_year .. thru_year LOOP
        EXECUTE format($fmt$
            DO $inner$
            BEGIN
               IF NOT EXISTS (
                 SELECT 1
                   FROM pg_class c
                   JOIN pg_namespace n ON n.oid = c.relnamespace
                  WHERE n.nspname = 'rankalpha'
                    AND c.relname = 'fact_fin_fundamentals_%s'
               ) THEN
                   CREATE TABLE rankalpha.fact_fin_fundamentals_%s
                   PARTITION OF rankalpha.fact_fin_fundamentals
                   FOR VALUES FROM (%s0101) TO (%s0101);
               END IF;
            END
            $inner$;
        $fmt$, yr, yr, yr, yr+1);
    END LOOP;
END;
$$;

/* Call once to cover 2020–2100 (adjust as needed) */
SELECT rankalpha.create_fin_partitions(2020, 2100);


/* ──────────────────────────── 6) PARTITION INDEXES ──────────────────────────── */
/* Loop through all child partitions and ensure the two indexes exist */
DO $$
DECLARE
    rec RECORD;
    idx1_name TEXT;
    idx2_name TEXT;
BEGIN
    FOR rec IN
      SELECT c.relname AS child_relname
        FROM pg_inherits inh
        JOIN pg_class c ON c.oid = inh.inhrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE inh.inhparent = 'rankalpha.fact_fin_fundamentals'::regclass
         AND n.nspname   = 'rankalpha'
    LOOP
        idx1_name := format('finfund_%s_sk_mk_idx',
                            substring(rec.child_relname from '(\d{4})'));
        idx2_name := format('finfund_%s_mk_dk_idx',
                            substring(rec.child_relname from '(\d{4})'));

        EXECUTE format(
          'CREATE INDEX IF NOT EXISTS %I ON rankalpha.%I (stock_key, metric_key);',
          idx1_name, rec.child_relname
        );
        EXECUTE format(
          'CREATE INDEX IF NOT EXISTS %I ON rankalpha.%I (metric_key, date_key);',
          idx2_name, rec.child_relname
        );
    END LOOP;
END
$$;
