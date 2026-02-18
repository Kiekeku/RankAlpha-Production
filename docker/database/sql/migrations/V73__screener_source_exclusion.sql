/* ------------------------------------------------------------
   V73__screener_source_exclusion.sql
   Adds opt-out and weighting metadata to screener sources.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

ALTER TABLE rankalpha.dim_source
    ADD COLUMN IF NOT EXISTS exclude_from_screener BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE rankalpha.dim_source
    ADD COLUMN IF NOT EXISTS screener_weight NUMERIC(6,4) NOT NULL DEFAULT 1.0;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
