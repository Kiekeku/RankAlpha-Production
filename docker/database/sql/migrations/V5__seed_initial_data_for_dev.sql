-- V5__seed_initial_data.sql
-- Seed initial data for RankAlpha development (10 stocks, mixed styles)

-- ▶ Ensure schema
SET search_path = rankalpha, public;

-- ▶ 1️⃣  Source (only Yahoo)
INSERT INTO dim_source (source_name, version) VALUES
  ('Yahoo Finance', '1')
ON CONFLICT (source_name) DO NOTHING;

-- ▶ 2️⃣  Styles
INSERT INTO dim_style (style_name) VALUES
  ('momentum'),
  ('value'),
  ('sentiment')
ON CONFLICT (style_name) DO NOTHING;

-- ▶ 3️⃣  Stocks (10 symbols)
INSERT INTO dim_stock (symbol, company_name, sector, exchange) VALUES
  ('AAPL',  'Apple Inc.',                    'Information Technology',   'NASDAQ'),
  ('MSFT',  'Microsoft Corporation',         'Information Technology',   'NASDAQ'),
  ('GOOGL', 'Alphabet Inc.',                 'Communication Services',   'NASDAQ'),
  ('AMZN',  'Amazon.com, Inc.',              'Consumer Discretionary',   'NASDAQ'),
  ('TSLA',  'Tesla, Inc.',                   'Consumer Discretionary',   'NASDAQ'),
  ('JPM',   'JPMorgan Chase & Co.',          'Financials',               'NYSE'),
  ('NVDA',  'NVIDIA Corporation',            'Information Technology',   'NASDAQ'),
  ('META',  'Meta Platforms, Inc.',          'Communication Services',   'NASDAQ'),
  ('WMT',   'Walmart Inc.',                  'Consumer Staples',         'NYSE'),
  ('BAC',   'Bank of America Corporation',   'Financials',               'NYSE')
ON CONFLICT (symbol) DO NOTHING;

-- ▶ 4️⃣  Snapshot #1: 2024-05-01 (mixed styles)
DO
$$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM fact_screener_rank
     WHERE date_key = 20240501
       AND screening_runid = '11111111-0000-0000-0000-000000000001'
  ) THEN

    INSERT INTO fact_screener_rank
      (date_key, stock_key, source_key, style_key, rank_value, screening_runid)
    VALUES
      -- momentum: AAPL, MSFT, GOOGL
      (20240501,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'AAPL'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'momentum'),
       1, '11111111-0000-0000-0000-000000000001'),
      (20240501,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'MSFT'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'momentum'),
       2, '11111111-0000-0000-0000-000000000001'),
      (20240501,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'GOOGL'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'momentum'),
       3, '11111111-0000-0000-0000-000000000001'),

      -- value: AMZN, TSLA, JPM
      (20240501,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'AMZN'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'value'),
       1, '11111111-0000-0000-0000-000000000001'),
      (20240501,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'TSLA'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'value'),
       2, '11111111-0000-0000-0000-000000000001'),
      (20240501,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'JPM'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'value'),
       3, '11111111-0000-0000-0000-000000000001'),

      -- sentiment: NVDA, META, WMT, BAC
      (20240501,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'NVDA'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'sentiment'),
       1, '11111111-0000-0000-0000-000000000001'),
      (20240501,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'META'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'sentiment'),
       2, '11111111-0000-0000-0000-000000000001'),
      (20240501,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'WMT'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'sentiment'),
       3, '11111111-0000-0000-0000-000000000001'),
      (20240501,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'BAC'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'sentiment'),
       4, '11111111-0000-0000-0000-000000000001');

  END IF;
END;
$$;

-- ▶ 5️⃣  Snapshot #2: 2024-05-02 (reverse ranks)
DO
$$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM fact_screener_rank
     WHERE date_key = 20240502
       AND screening_runid = '22222222-0000-0000-0000-000000000002'
  ) THEN

    INSERT INTO fact_screener_rank
      (date_key, stock_key, source_key, style_key, rank_value, screening_runid)
    VALUES
      -- momentum reversed
      (20240502,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'AAPL'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'momentum'),
       3, '22222222-0000-0000-0000-000000000002'),
      (20240502,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'MSFT'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'momentum'),
       2, '22222222-0000-0000-0000-000000000002'),
      (20240502,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'GOOGL'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'momentum'),
       1, '22222222-0000-0000-0000-000000000002'),

      -- value reversed
      (20240502,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'AMZN'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'value'),
       3, '22222222-0000-0000-0000-000000000002'),
      (20240502,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'TSLA'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'value'),
       2, '22222222-0000-0000-0000-000000000002'),
      (20240502,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'JPM'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'value'),
       1, '22222222-0000-0000-0000-000000000002'),

      -- sentiment reversed
      (20240502,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'NVDA'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'sentiment'),
       4, '22222222-0000-0000-0000-000000000002'),
      (20240502,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'META'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'sentiment'),
       3, '22222222-0000-0000-0000-000000000002'),
      (20240502,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'WMT'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'sentiment'),
       2, '22222222-0000-0000-0000-000000000002'),
      (20240502,
       (SELECT stock_key FROM dim_stock  WHERE symbol = 'BAC'),
       (SELECT source_key FROM dim_source WHERE source_name = 'Yahoo Finance'),
       (SELECT style_key FROM dim_style   WHERE style_name = 'sentiment'),
       1, '22222222-0000-0000-0000-000000000002');

  END IF;
END;
$$;
