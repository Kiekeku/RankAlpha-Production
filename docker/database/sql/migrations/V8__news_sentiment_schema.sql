-- Adding tables to store news articles and sentiment scores

-- Table to store news articles
CREATE TABLE IF NOT EXISTS fact_news_articles (
    article_id     UUID NOT NULL DEFAULT uuid_generate_v4(),       -- Unique identifier for the article
    stock_key      INT NOT NULL REFERENCES dim_stock(stock_key),   -- Reference to the stock the article relates to
    source_key     INT NOT NULL REFERENCES dim_source(source_key), -- Reference to the news source (e.g., Yahoo, Bloomberg)
    article_date   INT NOT NULL REFERENCES dim_date(date_key),     -- The date the article was published (YYYYMMDD)
    
    headline       TEXT NOT NULL,                                    -- Headline of the news article
    content        TEXT NOT NULL,                                    -- Full content of the news article
    url            TEXT NOT NULL,                                    -- URL of the news article
    
    load_ts        TIMESTAMPTZ NOT NULL DEFAULT NOW(),               -- Timestamp when the article was loaded
    PRIMARY KEY (article_id)
);

-- Table to store sentiment analysis for each news article
CREATE TABLE IF NOT EXISTS fact_news_sentiment (
    article_id     UUID NOT NULL REFERENCES fact_news_articles(article_id), -- Reference to the article
    sentiment_score DECIMAL(5, 3) NOT NULL,                               -- Sentiment score: range [-1.0, 1.0] for negative to positive
    sentiment_label VARCHAR(20) NOT NULL,                                  -- Sentiment label: Positive, Neutral, Negative
    analysis_runid UUID NOT NULL,                                          -- Unique ID for the sentiment analysis run
    load_ts        TIMESTAMPTZ NOT NULL DEFAULT NOW(),                    -- Timestamp when the sentiment was recorded
    
    PRIMARY KEY (article_id)  -- One-to-one relationship with news articles
);

-- Index to speed up queries based on stock, source, and date
CREATE INDEX IF NOT EXISTS idx_fact_news_articles_stock_date
    ON fact_news_articles (stock_key, article_date);

-- Index for efficient queries on sentiment analysis
CREATE INDEX IF NOT EXISTS idx_fact_news_sentiment_sentiment_score
    ON fact_news_sentiment (sentiment_score);

-- Optionally, you can track historical sentiment changes if required by adding a versioning mechanism:
-- e.g., create a history table or add versioning to the sentiment analysis