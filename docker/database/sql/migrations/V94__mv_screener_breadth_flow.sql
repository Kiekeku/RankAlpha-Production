/* ------------------------------------------------------------
   V94__mv_screener_breadth_flow.sql
   - Extended breadth view aligned with flow methodology (canonical styles)
   - Derived from mv_screener_flow_us with percent-of-universe normalization
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_screener_breadth_flow;

CREATE MATERIALIZED VIEW rankalpha.mv_screener_breadth_flow AS
SELECT
  d.full_date     AS change_date,
  f.date_key      AS date_key,
  f.style_name    AS canonical_name,
  COALESCE(f.entered_count, 0)::numeric(20,6)    AS entered_count,
  COALESCE(f.dropped_count, 0)::numeric(20,6)    AS dropped_count,
  COALESCE(f.continuers_count, 0)::numeric(20,6) AS continuers_count,
  COALESCE(f.eligible_count, 0)::numeric(20,6)   AS eligible_count,
  CASE WHEN COALESCE(f.eligible_count, 0) > 0 THEN (f.entered_count / f.eligible_count)::numeric(12,6) ELSE 0::numeric(12,6) END AS entered_pct,
  CASE WHEN COALESCE(f.eligible_count, 0) > 0 THEN (f.dropped_count / f.eligible_count)::numeric(12,6) ELSE 0::numeric(12,6) END AS dropped_pct,
  CASE WHEN COALESCE(f.eligible_count, 0) > 0 THEN (f.continuers_count / f.eligible_count)::numeric(12,6) ELSE 0::numeric(12,6) END AS continuers_pct,
  CASE WHEN COALESCE(f.eligible_count, 0) > 0 THEN ((f.entered_count - f.dropped_count) / f.eligible_count)::numeric(12,6) ELSE 0::numeric(12,6) END AS net_pct_us,
  CASE WHEN COALESCE(f.eligible_count, 0) > 0 THEN ((f.entered_count + f.dropped_count) / f.eligible_count)::numeric(12,6) ELSE 0::numeric(12,6) END AS churn_pct
FROM rankalpha.mv_screener_flow_us f
JOIN rankalpha.dim_date d ON d.date_key = f.date_key;

CREATE UNIQUE INDEX IF NOT EXISTS mv_screener_breadth_flow_pk
  ON rankalpha.mv_screener_breadth_flow (date_key, canonical_name);

CREATE INDEX IF NOT EXISTS mv_screener_breadth_flow_style_date
  ON rankalpha.mv_screener_breadth_flow (canonical_name, date_key);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

