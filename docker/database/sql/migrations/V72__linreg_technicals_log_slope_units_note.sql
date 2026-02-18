/* ------------------------------------------------------------
   V72__linreg_technicals_log_slope_units_note.sql

   Context:
   - On 2025-10-14, the scorer changed how it writes the
     "linear regression {N}" technicals (LINREG_200/90/50/30) into
     rankalpha.fact_score_history.

   - Previously: values represented raw-price slope (price units per day)
     from an OLS fit on Close.

   - Now: values represent log-price slope (per-day log return) scaled to
     percent per trading day (log_slope * 100). This brings technicals into
     the same unit family as momentum ranking and removes price-level bias.

   - Existing historical rows remain in the original units. Consumers that
     use cross-sectional percentile scaling (e.g., mv_latest_grades legacy
     fallback) remain robust.

   This migration records the semantic change via a column comment so that
   psql \d+ and metadata explorers surface it.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

COMMENT ON COLUMN rankalpha.fact_score_history.score IS
  'Score value (NUMERIC). Note: for score types "linear regression {N}", rows inserted on/after 2025-10-14 represent log-price slope scaled to percent per day; older rows represent raw-price slope (price units per day).';

/* End of file */

