-- V63__newswire_material_events.sql
-- Schema for raw news, clustering, material events, and impacts

BEGIN;

-- Raw ingestion table (dedup at URL level; may not be mapped to a stock yet)
CREATE TABLE IF NOT EXISTS rankalpha.fact_news_raw (
  raw_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  first_seen_ts    TIMESTAMPTZ NOT NULL DEFAULT now(),
  published_at     TIMESTAMPTZ NULL,
  source_domain    TEXT NOT NULL,
  url_canonical    TEXT NOT NULL,
  title            TEXT NOT NULL,
  snippet          TEXT NULL,
  language         VARCHAR(10) NULL,
  country          VARCHAR(2) NULL,
  dedup_key        TEXT NOT NULL,
  text_fingerprint BIGINT NULL,
  cluster_id       UUID NULL,
  raw_json         JSONB NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS fact_news_raw_dedup_key_uidx
  ON rankalpha.fact_news_raw (dedup_key);
CREATE INDEX IF NOT EXISTS fact_news_raw_published_idx
  ON rankalpha.fact_news_raw (published_at DESC);
CREATE INDEX IF NOT EXISTS fact_news_raw_cluster_idx
  ON rankalpha.fact_news_raw (cluster_id);

-- Clusters of near-duplicate stories
CREATE TABLE IF NOT EXISTS rankalpha.dim_news_cluster (
  cluster_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  first_seen_ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
  simhash            BIGINT NOT NULL,
  source_count       INT NOT NULL DEFAULT 1,
  centroid_raw_id    UUID NULL REFERENCES rankalpha.fact_news_raw(raw_id) ON DELETE SET NULL,
  is_official        BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS dim_news_cluster_first_seen_idx
  ON rankalpha.dim_news_cluster (first_seen_ts DESC);

-- Materialized events decided for clusters
CREATE TABLE IF NOT EXISTS rankalpha.fact_news_event (
  event_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  cluster_id       UUID NOT NULL REFERENCES rankalpha.dim_news_cluster(cluster_id) ON DELETE CASCADE,
  event_type       TEXT NULL,
  materiality_score NUMERIC(5,2) NOT NULL,
  direction        TEXT NULL,     -- positive|negative|mixed|unclear
  timescale        TEXT NULL,     -- immediate|near-term|long
  summary          TEXT NULL,
  decided_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  model_version    TEXT NULL,
  is_high_confidence BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS fact_news_event_cluster_idx
  ON rankalpha.fact_news_event (cluster_id);
CREATE INDEX IF NOT EXISTS fact_news_event_materiality_idx
  ON rankalpha.fact_news_event (materiality_score DESC);

-- Impacts to stocks
CREATE TABLE IF NOT EXISTS rankalpha.fact_news_impact (
  impact_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  event_id     UUID NOT NULL REFERENCES rankalpha.fact_news_event(event_id) ON DELETE CASCADE,
  stock_key    INT  NOT NULL REFERENCES rankalpha.dim_stock(stock_key),
  role         TEXT NOT NULL,     -- issuer|competitor|supplier|customer|index|sector
  confidence   NUMERIC(5,2) NOT NULL DEFAULT 0.5,
  rationale    TEXT NULL
);
CREATE INDEX IF NOT EXISTS fact_news_impact_event_idx
  ON rankalpha.fact_news_impact (event_id);
CREATE INDEX IF NOT EXISTS fact_news_impact_stock_idx
  ON rankalpha.fact_news_impact (stock_key);

-- View: latest material news, joined with a representative impact (highest confidence)
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_latest_material_news;
CREATE MATERIALIZED VIEW rankalpha.mv_latest_material_news AS
WITH ranked AS (
  SELECT
    e.event_id,
    e.cluster_id,
    e.materiality_score,
    e.event_type,
    e.direction,
    e.timescale,
    e.summary,
    e.decided_at,
    c.first_seen_ts,
    r.title AS title,
    r.url_canonical AS url,
    r.source_domain,
    i.stock_key,
    i.role,
    i.confidence,
    ROW_NUMBER() OVER (PARTITION BY e.event_id ORDER BY i.confidence DESC) AS rnk
  FROM rankalpha.fact_news_event e
  JOIN rankalpha.dim_news_cluster c ON c.cluster_id = e.cluster_id
  LEFT JOIN rankalpha.fact_news_raw r ON r.raw_id = c.centroid_raw_id
  LEFT JOIN rankalpha.fact_news_impact i ON i.event_id = e.event_id
)
SELECT
  x.event_id,
  x.cluster_id,
  x.first_seen_ts,
  x.decided_at,
  x.materiality_score,
  x.event_type,
  x.direction,
  x.timescale,
  x.summary,
  x.title,
  x.url,
  x.source_domain,
  d.symbol,
  d.company_name,
  x.role,
  x.confidence
FROM ranked x
LEFT JOIN rankalpha.dim_stock d ON d.stock_key = x.stock_key
WHERE x.rnk = 1;

CREATE UNIQUE INDEX IF NOT EXISTS mv_latest_material_news_pk
  ON rankalpha.mv_latest_material_news (event_id);
CREATE INDEX IF NOT EXISTS mv_latest_material_news_symbol_idx
  ON rankalpha.mv_latest_material_news (symbol);
CREATE INDEX IF NOT EXISTS mv_latest_material_news_score_idx
  ON rankalpha.mv_latest_material_news (materiality_score DESC);

-- View: news by symbol (non-material allowed later; for now, only material events)
DROP VIEW IF EXISTS rankalpha.vw_news_by_symbol;
CREATE VIEW rankalpha.vw_news_by_symbol AS
SELECT
  m.symbol,
  m.company_name,
  m.event_id,
  m.first_seen_ts,
  m.decided_at,
  m.materiality_score,
  m.event_type,
  m.direction,
  m.timescale,
  m.summary,
  m.title,
  m.url,
  m.source_domain,
  m.role,
  m.confidence
FROM rankalpha.mv_latest_material_news m;

COMMIT;

