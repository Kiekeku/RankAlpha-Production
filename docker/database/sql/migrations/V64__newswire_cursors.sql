-- V64__newswire_cursors.sql
-- Persist last-seen cursors per news source so the collector resumes after restarts.

BEGIN;

CREATE TABLE IF NOT EXISTS rankalpha.news_cursor (
  source_name TEXT PRIMARY KEY,
  last_seen   TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01 00:00:00+00',
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed rows for known sources
INSERT INTO rankalpha.news_cursor(source_name, last_seen)
VALUES
  ('gdelt', '1970-01-01 00:00:00+00'),
  ('serper', '1970-01-01 00:00:00+00')
ON CONFLICT (source_name) DO NOTHING;

COMMIT;

