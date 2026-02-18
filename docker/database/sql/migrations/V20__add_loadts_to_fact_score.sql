/* ------------------------------------------------------------
   V20250629_03__add_loadts_to_score_history.sql
   Adds load_ts column (UTC timestamp) to rankalpha.fact_score_history
   Idempotent – safe to run repeatedly
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

/* 1. Add column only if it does not exist */
ALTER TABLE rankalpha.fact_score_history
    ADD COLUMN IF NOT EXISTS load_ts timestamptz;

/* 2. Ensure default value (server‑side) */
ALTER TABLE rankalpha.fact_score_history
    ALTER COLUMN load_ts SET DEFAULT now();

/* 3. Back‑fill any legacy rows that may be NULL */
UPDATE rankalpha.fact_score_history
   SET load_ts = now()
 WHERE load_ts IS NULL;

/* 4. Enforce NOT NULL for all future inserts */
ALTER TABLE rankalpha.fact_score_history
    ALTER COLUMN load_ts SET NOT NULL;
