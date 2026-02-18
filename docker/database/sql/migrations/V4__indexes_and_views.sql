-- V4__indexes_and_views.sql
-- 4️⃣ Indexes
CREATE INDEX IF NOT EXISTS ix_fact_rank_stock
    ON fact_screener_rank (stock_key);

CREATE INDEX IF NOT EXISTS ix_fact_rank_source
    ON fact_screener_rank (source_key);

CREATE INDEX IF NOT EXISTS ix_fact_rank_style
    ON fact_screener_rank (style_key);

CREATE INDEX IF NOT EXISTS ix_fact_rank_date
    ON fact_screener_rank (date_key);

CREATE INDEX IF NOT EXISTS ix_fact_rank_sk_ssk_dk
    ON fact_screener_rank (stock_key, source_key, style_key, date_key);

CREATE INDEX IF NOT EXISTS ix_fact_rank_snapshot
    ON fact_screener_rank (screening_runid);

-- 5️⃣ Latest‐snapshot view
CREATE OR REPLACE VIEW v_latest_screener AS
SELECT f.*
FROM   fact_screener_rank f
JOIN   (SELECT MAX(date_key) AS max_date FROM fact_screener_rank) m
  ON f.date_key = m.max_date;
