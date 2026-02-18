
/* ---------- schema change ---------- */
-- 1. Make sure the UNIQUE CONSTRAINT (source_name, version) exists on dim_source
DO
$$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM   pg_constraint
        WHERE  conname  = 'dim_source_source_name_version_uc'
        AND    conrelid = 'rankalpha.dim_source'::regclass
    ) THEN
        ALTER TABLE rankalpha.dim_source
            ADD CONSTRAINT dim_source_source_name_version_uc
            UNIQUE (source_name, version);
    END IF;
END
$$;

-- 2. For good measure, also create an index for query performance (harmless if it’s already there)
CREATE UNIQUE INDEX IF NOT EXISTS dim_source_source_name_version_uidx
    ON rankalpha.dim_source (source_name, version);


-- 1. Drop the old column if it’s still around
ALTER TABLE IF EXISTS rankalpha.fact_fin_fundamentals
    DROP COLUMN IF EXISTS fiscal_per;

ALTER TABLE IF EXISTS rankalpha.fact_fin_fundamentals
    DROP COLUMN IF EXISTS stmt_code;

-- 2. Add the new column if it isn’t present yet
ALTER TABLE IF EXISTS rankalpha.fact_fin_fundamentals
    ADD COLUMN IF NOT EXISTS fiscal_period VARCHAR(3) NOT NULL;

-- 3. Seed dim_source – ignore the row if it is already there
-- make the (source_name, version) pair unique
/* ---------- schema change ---------- */
-- 1. Make sure we have a uniqueness guarantee for (source_name, version)
CREATE UNIQUE INDEX IF NOT EXISTS dim_source_source_name_version_uidx
    ON rankalpha.dim_source (source_name, version);

-- now the insert is idempotent
INSERT INTO rankalpha.dim_source (source_name, version)
VALUES ('Refinitv', 1)
ON CONFLICT ON CONSTRAINT dim_source_source_name_version_uc DO NOTHING;
