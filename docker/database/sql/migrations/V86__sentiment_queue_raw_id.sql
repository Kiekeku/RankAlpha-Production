-- V86__sentiment_queue_raw_id.sql
-- Link sentiment queue entries to the originating news raw document.

BEGIN;

ALTER TABLE rankalpha.sentiment_analysis_queue
  ADD COLUMN IF NOT EXISTS raw_id UUID NULL REFERENCES rankalpha.fact_news_raw(raw_id);

COMMIT;

