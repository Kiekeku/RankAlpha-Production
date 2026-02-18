-- V66__sentiment_analysis_queue.sql
-- Queue table to request sentiment analyses (e.g., from Newswire).

BEGIN;

CREATE TABLE IF NOT EXISTS rankalpha.sentiment_analysis_queue (
  queue_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  stock_key        INT NOT NULL REFERENCES rankalpha.dim_stock(stock_key),
  symbol           TEXT NOT NULL,
  event_id         UUID NULL REFERENCES rankalpha.fact_news_event(event_id) ON DELETE SET NULL,
  title            TEXT NULL,
  url              TEXT NULL,
  priority         INT NOT NULL DEFAULT 0,
  status           TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','in_progress','done','failed')),
  enqueue_ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
  run_after_ts     TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_ts       TIMESTAMPTZ NULL,
  completed_ts     TIMESTAMPTZ NULL,
  attempts         INT NOT NULL DEFAULT 0,
  source           TEXT NULL DEFAULT 'newswire'
);

CREATE INDEX IF NOT EXISTS saq_status_prio_idx ON rankalpha.sentiment_analysis_queue (status, priority DESC, enqueue_ts);
CREATE INDEX IF NOT EXISTS saq_stock_idx ON rankalpha.sentiment_analysis_queue (stock_key);
CREATE INDEX IF NOT EXISTS saq_event_idx ON rankalpha.sentiment_analysis_queue (event_id);

-- Prevent duplicate pending/in_progress entries for the same (event_id, stock_key)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE schemaname='rankalpha' AND indexname='saq_unique_pending_event_stock'
  ) THEN
    EXECUTE 'CREATE UNIQUE INDEX saq_unique_pending_event_stock ON rankalpha.sentiment_analysis_queue (event_id, stock_key)
             WHERE status IN (''pending'',''in_progress'') AND event_id IS NOT NULL';
  END IF;
END$$;

COMMIT;

