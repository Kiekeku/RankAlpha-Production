-- V85__newswire_trace_columns.sql
-- Capture newswire trace metadata (prefilter reason, body fetch status, LLM trace).

BEGIN;

ALTER TABLE rankalpha.fact_news_raw
  ADD COLUMN IF NOT EXISTS body_fetch_status TEXT NULL,
  ADD COLUMN IF NOT EXISTS body_fetch_error TEXT NULL;

ALTER TABLE rankalpha.fact_news_event
  ADD COLUMN IF NOT EXISTS prefilter_reason TEXT NULL,
  ADD COLUMN IF NOT EXISTS llm_prompt TEXT NULL,
  ADD COLUMN IF NOT EXISTS llm_response JSONB NULL,
  ADD COLUMN IF NOT EXISTS llm_ran_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS llm_model TEXT NULL,
  ADD COLUMN IF NOT EXISTS llm_tokens_prompt INT NULL,
  ADD COLUMN IF NOT EXISTS llm_tokens_completion INT NULL,
  ADD COLUMN IF NOT EXISTS llm_error TEXT NULL;

COMMIT;

