ALTER TABLE fact_score_history
    RENAME COLUMN momentum_value TO score;
    
CREATE INDEX IF NOT EXISTS idx_fact_score_history_stock_key
    ON fact_score_history (stock_key);

CREATE INDEX IF NOT EXISTS idx_fact_score_history_source_key
    ON fact_score_history (source_key);

CREATE INDEX IF NOT EXISTS idx_fact_score_history_score_type_key
    ON fact_score_history (score_type_key);
