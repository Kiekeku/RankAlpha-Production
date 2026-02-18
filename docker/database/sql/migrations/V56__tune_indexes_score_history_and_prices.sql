/* ------------------------------------------------------------
   V56__tune_indexes_score_history_and_prices.sql
   - Add composite indexes to fact_score_history partitions to speed
     latest-per-stock-per-score_type lookups and windowed queries.
   - Add supporting index to fact_security_price for fast latest-per-stock reads.
   - Purely additive; no impact on existing views or data.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

/* ------------------------------------------------------------
   1) fact_score_history: per-partition composite index
      Pattern used by queries:
        ROW_NUMBER() OVER (
          PARTITION BY f.stock_key
          ORDER BY f.date_key DESC, f.load_ts DESC, f.fact_id DESC)
      and filters on score_type_key.
      Create (stock_key, score_type_key, date_key DESC) on each child.
   ------------------------------------------------------------ */
DO $$
DECLARE
    rec RECORD;
    idx_name TEXT;
BEGIN
    FOR rec IN
        SELECT n.nspname AS nsp, c.relname AS rel
        FROM   pg_inherits i
        JOIN   pg_class    c ON c.oid = i.inhrelid
        JOIN   pg_namespace n ON n.oid = c.relnamespace
        WHERE  i.inhparent = 'rankalpha.fact_score_history'::regclass
    LOOP
        idx_name := rec.rel || '_sk_stk_dk_idx';
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %s (stock_key, score_type_key, date_key DESC)',
            idx_name,
            quote_ident(rec.nsp) || '.' || quote_ident(rec.rel)
        );
    END LOOP;
END$$;

/* ------------------------------------------------------------
   2) fact_security_price: add (stock_key, date_key DESC)
      Speeds “latest price per stock” lateral joins and as-of ranges.
   ------------------------------------------------------------ */
CREATE INDEX IF NOT EXISTS idx_fact_security_price_stock_date_desc
    ON rankalpha.fact_security_price (stock_key, date_key DESC);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
