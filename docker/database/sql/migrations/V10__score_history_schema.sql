CREATE TABLE IF NOT EXISTS fact_score_history (
    date_key       INT  NOT NULL REFERENCES dim_date(date_key),
    fact_id        UUID NOT NULL DEFAULT uuid_generate_v4(),
    
    stock_key      INT  NOT NULL REFERENCES dim_stock(stock_key),
    source_key     INT  NOT NULL REFERENCES dim_source(source_key),
    score_type_key INT  NOT NULL REFERENCES dim_score_type(score_type_key),
    
    momentum_value DECIMAL(5, 2) NOT NULL,

    PRIMARY KEY (date_key, fact_id)
) PARTITION BY RANGE (date_key);

CREATE TABLE fact_score_history_2025
  PARTITION OF fact_score_history
  FOR VALUES FROM (20250101) TO (20260101);