-- Adding fact table for storing stock scores from screeners

-- fact table to store stock scores (partitioned by date)
CREATE TABLE IF NOT EXISTS fact_stock_scores (
    date_key       INT  NOT NULL REFERENCES dim_date(date_key),     -- Reference to date dimension (YYYYMMDD)
    fact_id        UUID NOT NULL DEFAULT uuid_generate_v4(),        -- Unique identifier for each score entry
    
    stock_key      INT  NOT NULL REFERENCES dim_stock(stock_key),   -- Reference to the stock
    style_key      INT  NOT NULL REFERENCES dim_style(style_key),   -- Reference to the style (e.g., value, momentum)
    
    score_value    DECIMAL(5, 2) NOT NULL,                           -- Stock score (e.g., 85.75)
    rank_value     INT NOT NULL,                                     -- Rank value based on the score
    score_runid    UUID NOT NULL,                                    -- Unique identifier for the score calculation run
    load_ts        TIMESTAMPTZ NOT NULL DEFAULT NOW(),               -- Timestamp of when the score was loaded
    
    PRIMARY KEY (date_key, fact_id)                                  -- Primary key to uniquely identify the record
) PARTITION BY RANGE (date_key);

-- Index to speed up queries that join on stock_key and style_key
CREATE INDEX IF NOT EXISTS idx_fact_stock_scores_stock_style
    ON fact_stock_scores (stock_key, style_key);

-- Adding additional information about the stock scores (optional)
CREATE TABLE IF NOT EXISTS dim_score_type (
    score_type_key SERIAL PRIMARY KEY,                              -- Unique ID for each score type
    score_type_name VARCHAR(50) NOT NULL UNIQUE                     -- Name of the score type (e.g., Momentum, Value, etc.)
);

-- New fact table to store different score types for each stock
CREATE TABLE IF NOT EXISTS fact_stock_score_types (
    date_key       INT  NOT NULL REFERENCES dim_date(date_key),     -- Date of score calculation
    fact_id        UUID NOT NULL DEFAULT uuid_generate_v4(),        -- Unique ID for the record
    
    stock_key      INT  NOT NULL REFERENCES dim_stock(stock_key),   -- Stock being scored
    score_type_key INT  NOT NULL REFERENCES dim_score_type(score_type_key), -- Reference to the score type (e.g., Momentum)
    
    score_value    DECIMAL(5, 2) NOT NULL,                          -- The calculated score value for this type
    rank_value     INT NOT NULL,                                    -- The rank of the stock for this score type
    score_runid    UUID NOT NULL,                                   -- Unique ID for the scoring run
    
    load_ts        TIMESTAMPTZ NOT NULL DEFAULT NOW(),              -- Timestamp for record creation
    
    PRIMARY KEY (date_key, fact_id)                                  -- Primary key for each unique record
) PARTITION BY RANGE (date_key);

-- Index for performance when filtering by score_type and stock
CREATE INDEX IF NOT EXISTS idx_fact_stock_score_types_score_type_stock
    ON fact_stock_score_types (score_type_key, stock_key);