/* ------------------------------------------------------------
   V33__widen_score_history_score_precision.sql
   Widen fact_score_history.score to allow up to 8 integer digits
   (e.g., values > 100000), while keeping 2 decimal places.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- Drop dependent view(s) before altering the column type
DROP VIEW IF EXISTS rankalpha.vw_score_history;

-- Parent is partitioned by RANGE(date_key); altering the parent column type
-- cascades to all partitions in supported PostgreSQL versions.
ALTER TABLE rankalpha.fact_score_history
  ALTER COLUMN score TYPE numeric(10,2);

-- Recreate dependent view
CREATE OR REPLACE VIEW rankalpha.vw_score_history AS
SELECT
    h.date_key,
    d.full_date          AS as_of_date,
    s.symbol,
    st.score_type_name,
    h.score,
    src.source_name,
    h.load_ts
FROM   rankalpha.fact_score_history      h
JOIN   rankalpha.dim_stock          s   ON s.stock_key = h.stock_key
JOIN   rankalpha.dim_score_type     st  ON st.score_type_key = h.score_type_key
JOIN   rankalpha.dim_date           d   ON d.date_key = h.date_key
JOIN   rankalpha.dim_source         src ON src.source_key = h.source_key;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
