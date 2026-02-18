-- R__vw_news_sentiment.sql
-- Purpose : Human‑readable mash‑up of news sentiment & article metadata
-- Idempotent:  CREATE OR REPLACE VIEW  keeps Flyway checksum stable.

CREATE OR REPLACE VIEW rankalpha.vw_news_sentiment AS
SELECT
    a.article_id,                       -- UUID – PK surrogate
    a.article_date       AS date_key,   -- FK to dim_date (numeric yyyymmdd)
    d.full_date          AS article_date,
    s.stock_key,
    s.symbol,
    a.source_key,
    src.source_name,
    src.version          AS source_version,
    n.sentiment_score,
    n.sentiment_label,
    a.headline,
    a.url,
    a.load_ts
FROM   rankalpha.fact_news_sentiment  n
JOIN   rankalpha.fact_news_articles   a  ON a.article_id = n.article_id
JOIN   rankalpha.dim_stock            s  ON s.stock_key = a.stock_key
JOIN   rankalpha.dim_date             d  ON d.date_key  = a.article_date
JOIN   rankalpha.dim_source           src ON src.source_key = a.source_key;

COMMENT ON VIEW rankalpha.vw_news_sentiment IS
'Denormalised lens for quants: one row per article with sentiment, ticker, date, headline & source.';

