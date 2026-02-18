/* ------------------------------------------------------------
   V53__mv_screener_changes_unique_index.sql
   Ensure mv_screener_changes supports concurrent refresh by
   replacing the expression-based unique index with a plain
   column index (NULLS NOT DISTINCT keeps NULL style_key unique).
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

DROP INDEX IF EXISTS mv_screener_changes_pk;

CREATE UNIQUE INDEX mv_screener_changes_pk
  ON rankalpha.mv_screener_changes (
    change_date_key,
    stock_key,
    source_key,
    style_key,
    change_type
  ) NULLS NOT DISTINCT;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
