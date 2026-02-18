--  Dimension tables
--------------------------------------------------------------------

-- ▸ What correlation algorithm / basis was used?
CREATE TABLE IF NOT EXISTS dim_corr_method (
    corr_method_key SERIAL PRIMARY KEY,
    corr_method_name VARCHAR(40) NOT NULL UNIQUE      -- e.g. 'Pearson', 'Spearman', 'Kendall'
);

-- ▸ Optional: normalise common look-back windows (makes slicing easier)
CREATE TABLE IF NOT EXISTS dim_corr_window (
    corr_window_key SERIAL PRIMARY KEY,
    window_label VARCHAR(30) NOT NULL UNIQUE,         -- e.g. '30D', '90D', '252D'
    window_days    SMALLINT  NOT NULL                 -- numeric length for quick filtering
);

--------------------------------------------------------------------
--  Fact table
--------------------------------------------------------------------
/*
    A pairwise correlation is symmetric, so we only store the combination
    where stock1_key < stock2_key.  That cuts storage ~50 % and eliminates
    duplicate rows.
*/
CREATE TABLE IF NOT EXISTS fact_stock_correlation (
    /* Date **as-of** which the correlation was calculated (typically today) */
    date_key          INT  NOT NULL REFERENCES dim_date(date_key),

    fact_id           UUID NOT NULL DEFAULT uuid_generate_v4(),

    /* Ordered stock pair */
    stock1_key        INT  NOT NULL REFERENCES dim_stock(stock_key),
    stock2_key        INT  NOT NULL REFERENCES dim_stock(stock_key),

    /* Meta-data */
    corr_method_key   INT  NOT NULL REFERENCES dim_corr_method(corr_method_key),
    corr_window_key   INT  NOT NULL REFERENCES dim_corr_window(corr_window_key),

    /* The actual coefficient: −1.000 … +1.000 */
    correlation_value NUMERIC(6,4) NOT NULL CHECK (correlation_value BETWEEN -1 AND 1),

    corr_runid        UUID NOT NULL,                    -- batch / job id
    load_ts           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_fact_stock_corr PRIMARY KEY (date_key, fact_id),
    /* Enforce stock1_key < stock2_key so each pair stored once */
    CONSTRAINT chk_stock_order CHECK (stock1_key < stock2_key)
) PARTITION BY RANGE (date_key);

--------------------------------------------------------------------
--  Indexes for the hot paths
--------------------------------------------------------------------
/* Fast lookup for a particular pair over time */
CREATE INDEX IF NOT EXISTS idx_corr_pair_date
        ON fact_stock_correlation (stock1_key, stock2_key, date_key);

/* Slice everything for one date (e.g., build a full matrix) */
CREATE INDEX IF NOT EXISTS idx_corr_date
        ON fact_stock_correlation (date_key);
