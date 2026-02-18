/*-----------------------------------------------------------
  1. Remove the old PK ( (date_key, stock_key, stmt_code, metric_key) )
-----------------------------------------------------------*/
ALTER TABLE IF EXISTS rankalpha.fact_fin_fundamentals
        DROP CONSTRAINT IF EXISTS pk_fact_finfund;

/*-----------------------------------------------------------
  2. Add the new PK ( (date_key, stock_key, metric_key) )
     – but only if it doesn’t exist yet
-----------------------------------------------------------*/
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM   pg_constraint c
        WHERE  c.conname  = 'pk_fact_finfund'
          AND  c.conrelid = 'rankalpha.fact_fin_fundamentals'::regclass
    ) THEN
        -- DDL inside PL/pgSQL must be executed dynamically
        EXECUTE '
            ALTER TABLE rankalpha.fact_fin_fundamentals
            ADD CONSTRAINT pk_fact_finfund
            PRIMARY KEY (date_key, stock_key, metric_key)
        ';
    END IF;
END $$;
