-- V67__news_body_columns.sql
-- Store extracted article body for selected sources under gating.

BEGIN;

ALTER TABLE rankalpha.fact_news_raw
  ADD COLUMN IF NOT EXISTS body_text TEXT,
  ADD COLUMN IF NOT EXISTS body_fingerprint BIGINT,
  ADD COLUMN IF NOT EXISTS body_bytes INT,
  ADD COLUMN IF NOT EXISTS body_truncated BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS body_fetch_ts TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS body_source TEXT,
  ADD COLUMN IF NOT EXISTS body_lang TEXT;

CREATE INDEX IF NOT EXISTS fact_news_raw_body_fp_idx
  ON rankalpha.fact_news_raw (body_fingerprint)
  WHERE body_fingerprint IS NOT NULL;

COMMIT;

