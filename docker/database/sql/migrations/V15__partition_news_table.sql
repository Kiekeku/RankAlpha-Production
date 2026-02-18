-- V3__partition_and_seed_news.sql

----------------------------------------------------------------------
-- 1) Initial, destructive setup (only if we haven’t done it yet)  --
----------------------------------------------------------------------

DO $$
BEGIN
  -- test for one of the new partitions — if it exists, skip all the drops/creates
  IF NOT EXISTS (
    SELECT 1
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'rankalpha'
       AND c.relname = 'fact_news_articles_2020'
  ) THEN

    -- a) Drop any old versions
    EXECUTE 'DROP TABLE IF EXISTS rankalpha.fact_news_sentiment';
    EXECUTE 'DROP TABLE IF EXISTS rankalpha.fact_news_articles';

    -- b) Recreate the partitioned articles table
    EXECUTE '
      CREATE TABLE rankalpha.fact_news_articles (
        article_id   UUID        NOT NULL DEFAULT uuid_generate_v4(),
        stock_key    INT         NOT NULL,
        source_key   INT         NOT NULL,
        article_date INT         NOT NULL,
        headline     TEXT        NOT NULL,
        content      TEXT        NOT NULL,
        url          TEXT        NOT NULL,
        load_ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT fact_news_articles_pkey PRIMARY KEY (article_date, article_id),
        CONSTRAINT fact_news_articles_article_date_fkey FOREIGN KEY (article_date)
          REFERENCES rankalpha.dim_date (date_key),
        CONSTRAINT fact_news_articles_source_key_fkey FOREIGN KEY (source_key)
          REFERENCES rankalpha.dim_source (source_key),
        CONSTRAINT fact_news_articles_stock_key_fkey FOREIGN KEY (stock_key)
          REFERENCES rankalpha.dim_stock (stock_key)
      ) PARTITION BY RANGE (article_date)';
    
    -- c) Create the unpartitioned sentiment table
    EXECUTE '
      CREATE TABLE rankalpha.fact_news_sentiment (
        article_id      UUID        NOT NULL,
        sentiment_score NUMERIC(5,3) NOT NULL,
        sentiment_label VARCHAR(20) NOT NULL,
        analysis_runid  UUID        NOT NULL,
        load_ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT fact_news_sentiment_pkey PRIMARY KEY (article_id)
      )';
    EXECUTE 'CREATE INDEX idx_fact_news_sentiment_score
             ON rankalpha.fact_news_sentiment (sentiment_score)';

  END IF;
END
$$;


----------------------------------------------------------------------
-- 2) Add any missing partitions & indexes (runs every time)        --
----------------------------------------------------------------------

DO $$
DECLARE
  yr INT;
BEGIN
  FOR yr IN 2020..2100 LOOP
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS rankalpha.fact_news_articles_%1$s
         PARTITION OF rankalpha.fact_news_articles
         FOR VALUES FROM (%1$s0101) TO (%2$s0101)',
      yr, yr+1
    );
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS idx_fact_news_articles_%1$s_stock_date
         ON rankalpha.fact_news_articles_%1$s (stock_key, article_date)',
      yr
    );
  END LOOP;

  EXECUTE '
    CREATE TABLE IF NOT EXISTS rankalpha.fact_news_articles_default
      PARTITION OF rankalpha.fact_news_articles DEFAULT';
  EXECUTE '
    CREATE INDEX IF NOT EXISTS idx_fact_news_articles_default_stock_date
      ON rankalpha.fact_news_articles_default (stock_key, article_date)';
END
$$;
