/*───────────────────────────────────────────────────────────────────────────
  FACT_SCORE_HISTORY – YEARLY PARTITION & INDEX GENERATOR
  • Requires parent rankalpha.fact_score_history already partitioned BY RANGE(date_key)
  • PostgreSQL 11+ (uses CREATE INDEX IF NOT EXISTS)
───────────────────────────────────────────────────────────────────────────*/
DO
$$
DECLARE
    yr           INT;         -- loop variable for the year
    child_tbl    TEXT;        -- e.g. fact_score_history_2025
BEGIN
    FOR yr IN 1997 .. 2100 LOOP
        child_tbl := format('fact_score_history_%s', yr);

        /* ─── 1.  Create partition table if absent ─── */
        IF NOT EXISTS (
              SELECT 1
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              WHERE n.nspname = 'rankalpha'
                AND c.relname  = child_tbl
        ) THEN
            EXECUTE format(
                'CREATE TABLE rankalpha.%I
                   PARTITION OF rankalpha.fact_score_history
                   FOR VALUES FROM (%s0101) TO (%s0101);',
                child_tbl, yr, yr + 1
            );
        END IF;

        /* ─── 2.  Idempotent index creation ─── */
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I
               ON rankalpha.%I (score_type_key);',
            child_tbl || '_score_type_key_idx',
            child_tbl
        );

        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I
               ON rankalpha.%I (source_key);',
            child_tbl || '_source_key_idx',
            child_tbl
        );

        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I
               ON rankalpha.%I (stock_key);',
            child_tbl || '_stock_key_idx',
            child_tbl
        );
    END LOOP;
END;
$$;
