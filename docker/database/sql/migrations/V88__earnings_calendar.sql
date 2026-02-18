-- Create table to track the next known earnings date per stock (sourced from Finnhub)

CREATE TABLE IF NOT EXISTS rankalpha.fact_stock_next_earnings (
    stock_key        INT NOT NULL PRIMARY KEY REFERENCES rankalpha.dim_stock(stock_key),
    earnings_date    DATE NOT NULL,
    earnings_time    TEXT NULL,
    earnings_source  TEXT NOT NULL DEFAULT 'finnhub',
    load_ts          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS fact_stock_next_earnings_date_idx
    ON rankalpha.fact_stock_next_earnings (earnings_date);
