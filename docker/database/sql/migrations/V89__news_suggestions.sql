-- V89__news_suggestions.sql
-- Partner-facing news suggestion intake tables and processing queue.

BEGIN;

CREATE TABLE IF NOT EXISTS rankalpha.news_suggestion (
  suggestion_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  submitted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at        TIMESTAMPTZ NULL,
  source_name         TEXT NOT NULL,
  submitter_reference TEXT NULL,
  idempotency_key     TEXT NULL,
  status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','in_progress','accepted','rejected','merged')),
  status_reason       TEXT NULL,
  url                 TEXT NOT NULL,
  url_canonical       TEXT NOT NULL,
  url_hash            TEXT NOT NULL,
  title               TEXT NOT NULL,
  snippet             TEXT NULL,
  body_text           TEXT NULL,
  body_bytes          INT NULL,
  body_fingerprint    BIGINT NULL,
  text_fingerprint    BIGINT NULL,
  published_at        TIMESTAMPTZ NULL,
  language            TEXT NULL,
  country             TEXT NULL,
  raw_payload         JSONB NULL,
  cluster_id          UUID NULL REFERENCES rankalpha.dim_news_cluster(cluster_id) ON DELETE SET NULL,
  event_id            UUID NULL REFERENCES rankalpha.fact_news_event(event_id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS news_suggestion_source_idempotency_uidx
  ON rankalpha.news_suggestion (source_name, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS news_suggestion_status_idx
  ON rankalpha.news_suggestion (status, submitted_at DESC);

CREATE INDEX IF NOT EXISTS news_suggestion_url_hash_idx
  ON rankalpha.news_suggestion (url_hash);

CREATE TABLE IF NOT EXISTS rankalpha.news_ingest_queue (
  queue_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  suggestion_id UUID NOT NULL REFERENCES rankalpha.news_suggestion(suggestion_id) ON DELETE CASCADE,
  status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','in_progress','done','failed')),
  priority      INT NOT NULL DEFAULT 0,
  enqueue_ts    TIMESTAMPTZ NOT NULL DEFAULT now(),
  run_after_ts  TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_ts    TIMESTAMPTZ NULL,
  completed_ts  TIMESTAMPTZ NULL,
  attempts      INT NOT NULL DEFAULT 0,
  last_error    TEXT NULL,
  locked_by     TEXT NULL,
  locked_ts     TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS news_ingest_queue_ready_idx
  ON rankalpha.news_ingest_queue (status, priority DESC, run_after_ts, enqueue_ts);

CREATE UNIQUE INDEX IF NOT EXISTS news_ingest_queue_pending_unique
  ON rankalpha.news_ingest_queue (suggestion_id)
  WHERE status IN ('pending','in_progress');

COMMIT;

