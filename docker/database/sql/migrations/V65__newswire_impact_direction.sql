-- V65__newswire_impact_direction.sql
-- Add per-impact direction and magnitude fields; optional expected return pct.

BEGIN;

ALTER TABLE rankalpha.fact_news_impact
  ADD COLUMN IF NOT EXISTS direction TEXT NULL CHECK (direction IN ('positive','negative','mixed','unclear')),
  ADD COLUMN IF NOT EXISTS magnitude_score NUMERIC(5,2) NULL,
  ADD COLUMN IF NOT EXISTS expected_return_pct NUMERIC(6,2) NULL;

CREATE INDEX IF NOT EXISTS fact_news_impact_direction_idx
  ON rankalpha.fact_news_impact (direction);

COMMIT;

