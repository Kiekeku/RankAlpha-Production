-- V68 revised: add a stored date column and maintain via trigger to satisfy
-- Postgres immutability requirements for expression indexes.

BEGIN;

-- Add a plain date column to index on
ALTER TABLE rankalpha.sentiment_analysis_queue
  ADD COLUMN IF NOT EXISTS run_after_date DATE;

-- Trigger to keep run_after_date in sync (UTC date)
CREATE OR REPLACE FUNCTION rankalpha.set_saq_run_after_date()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.run_after_date := (NEW.run_after_ts AT TIME ZONE 'UTC')::date;
  RETURN NEW;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_set_saq_run_after_date_ins'
  ) THEN
    CREATE TRIGGER trg_set_saq_run_after_date_ins
    BEFORE INSERT ON rankalpha.sentiment_analysis_queue
    FOR EACH ROW EXECUTE PROCEDURE rankalpha.set_saq_run_after_date();
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_set_saq_run_after_date_upd'
  ) THEN
    CREATE TRIGGER trg_set_saq_run_after_date_upd
    BEFORE UPDATE OF run_after_ts ON rankalpha.sentiment_analysis_queue
    FOR EACH ROW EXECUTE PROCEDURE rankalpha.set_saq_run_after_date();
  END IF;
END$$;

-- Backfill existing rows
UPDATE rankalpha.sentiment_analysis_queue
SET run_after_date = (run_after_ts AT TIME ZONE 'UTC')::date
WHERE run_after_date IS NULL;

-- Unique index using the stored date column
CREATE UNIQUE INDEX IF NOT EXISTS saq_unique_stock_date_pending
  ON rankalpha.sentiment_analysis_queue (stock_key, run_after_date)
  WHERE status IN ('pending','in_progress') AND event_id IS NULL;

COMMIT;
