-- V87__newswire_textfp_index.sql
-- Add an index to accelerate duplicate detection by text fingerprint

BEGIN;

CREATE INDEX IF NOT EXISTS fact_news_raw_text_fingerprint_idx
  ON rankalpha.fact_news_raw (text_fingerprint);

COMMIT;

