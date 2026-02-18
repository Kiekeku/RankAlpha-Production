/* ------------------------------------------------------------
   V36__performance_indexes_grading.sql
   Indexes to speed /api/v1/grading/grades
   - Composite indexes on fact_score_history partitions (date_key, score_type_key)
   - Helper indexes for AI analysis and dim lookups
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- 1) fact_score_history per-partition composite index (date_key, score_type_key)
DO $$
DECLARE
  yr INT;
  child_tbl TEXT;
BEGIN
  FOR yr IN 1997..2100 LOOP
    child_tbl := format('fact_score_history_%s', yr);
    IF EXISTS (
      SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE n.nspname = 'rankalpha' AND c.relname = child_tbl
    ) THEN
      EXECUTE format(
        'CREATE INDEX IF NOT EXISTS %I ON rankalpha.%I (date_key, score_type_key, stock_key)',
        child_tbl || '_date_type_stock_idx', child_tbl
      );
    END IF;
  END LOOP;

  -- default partition (if present)
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'rankalpha' AND c.relname = 'fact_score_history_default'
  ) THEN
    CREATE INDEX IF NOT EXISTS fact_score_history_default_date_type_stock_idx
      ON rankalpha.fact_score_history_default (date_key, score_type_key, stock_key);
  END IF;
END $$;

-- 2) AI analysis helpers
CREATE INDEX IF NOT EXISTS idx_fact_ai_stock_analysis_date_stock
  ON fact_ai_stock_analysis (date_key, stock_key);

-- 3) Dim lookups used at runtime
CREATE INDEX IF NOT EXISTS idx_dim_score_type_name
  ON dim_score_type (score_type_name);

-- Sector filtering (dim_stock is usually small, but add if not exists)
CREATE INDEX IF NOT EXISTS idx_dim_stock_active_sector
  ON dim_stock (is_active, sector);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
