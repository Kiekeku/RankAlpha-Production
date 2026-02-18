BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'rankalpha'
          AND table_name   = 'dim_fin_metric'
          AND column_name  = 'stmt_code'
          AND (
                (data_type = 'character'           ) OR
                (data_type = 'character varying'
                     AND (character_maximum_length IS NULL
                          OR character_maximum_length < 64))
              )
    ) THEN
        EXECUTE 'ALTER TABLE rankalpha.dim_fin_metric
                 ALTER COLUMN stmt_code TYPE varchar(64);';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'rankalpha'
          AND table_name   = 'dim_fin_metric'
          AND column_name  = 'default_unit'
          AND (
                (data_type = 'character'           ) OR
                (data_type = 'character varying'
                     AND (character_maximum_length IS NULL
                          OR character_maximum_length < 64))
              )
    ) THEN
        EXECUTE 'ALTER TABLE rankalpha.dim_fin_metric
                 ALTER COLUMN default_unit TYPE varchar(64);';
    END IF;
END $$;

INSERT INTO rankalpha.dim_fin_metric
    (metric_code, metric_name, stmt_code, default_unit)
VALUES
    ('a1fcf', 'Free Cash Flow', 'Cash Flow', 'Millions'),
    ('aastturn', 'Asset turnover', 'Efficiency Ratios', 'Actual Values'),
    ('abepsxclxo', 'EPS Basic excluding extraordinary items', 'Per Share Ratios', 'Actual Values'),
    ('abvps', 'Book value (total equity) per Share', 'Per Share Ratios', 'Actual Values'),
    ('acfshr', 'Cash Flow per Share', 'Per Share Ratios', 'Actual Values'),
    ('acshps', 'Cash per Share', 'Per Share Ratios', 'Actual Values'),
    ('acurratio', 'Current ratio', 'Financial Strength', 'Actual Values'),
    ('adiv5yavg', 'Ordinary Dividend Per Share, 5 year average', 'Dividend', 'Percentage'),
    ('adivshr', 'Ordinary Dividend per Share', 'Dividend', 'Actual Values'),
    ('aebitd', 'EBITDA', 'Income Statement', 'Millions'),
    ('aebt', 'Earnings before taxes', 'Income Statement', 'Millions'),
    ('aebtnorm', 'Earnings before taxes Normalized', 'Income Statement', 'Millions'),
    ('aepsinclxo', 'EPS including extraordinary items', 'Per Share Ratios', 'Actual Values'),
    ('aepsnorm', 'EPS Normalized', 'Per Share Ratios', 'Actual Values'),
    ('aepsxclxor', 'EPS excluding extraordinary items', 'Per Share Ratios', 'Actual Values'),
    ('agrosmgn', 'Gross Margin', 'Profitability Ratios', 'Percentage'),
    ('aintcov', 'Net Interest coverage', 'Financial Strength', 'Actual Values'),
    ('ainvturn', 'Inventory turnover', 'Efficiency Ratios', 'Actual Values'),
    ('altd2eq', 'LT debt/equity', 'Financial Strength', 'Percentage'),
    ('aniac', 'Net Income available to common', 'Income Statement', 'Millions'),
    ('aniacnorm', 'Net Income Available to Common, Normalized', 'Income Statement', 'Millions'),
    ('aniperemp', 'Net Income/employee', 'Efficiency Ratios', 'Actual Values'),
    ('anpmgnpct', 'Net Profit Margin %', 'Profitability Ratios', 'Percentage'),
    ('aopmgnpct', 'Operating margin', 'Profitability Ratios', 'Percentage'),
    ('apayratio', 'Payout ratio', 'Financial Strength', 'Percentage'),
    ('apr2rev', 'Price to sales, most recent fiscal year', 'Price Related', 'Actual Values'),
    ('apr2tanbk', 'Price to Tangible Book, most recent fiscal year', 'Price Related', 'Actual Values'),
    ('aprfcfps', 'Price to Free Cash Flow per Share, most recent fiscal year', 'Price Related', 'Actual Values'),
    ('aprice2bk', 'Price to Book, most recent fiscal year', 'Price Related', 'Actual Values'),
    ('aptmgnpct', 'Pretax margin', 'Profitability Ratios', 'Percentage'),
    ('aquickrati', 'Quick ratio', 'Financial Strength', 'Actual Values'),
    ('arecturn', 'Receivables turnover', 'Efficiency Ratios', 'Actual Values'),
    ('arev', 'Revenue', 'Income Statement', 'Millions'),
    ('arevperemp', 'Revenue/employee', 'Efficiency Ratios', 'Actual Values'),
    ('arevps', 'Revenue per Share', 'Per Share Ratios', 'Actual Values'),
    ('aroa5yavg', 'Return on average assets, 5 year average', 'Management Effectiveness', 'Percentage'),
    ('aroapct', 'Return on average assets', 'Management Effectiveness', 'Percentage'),
    ('aroe5yavg', 'Return on average equity, 5 year average', 'Management Effectiveness', 'Percentage'),
    ('aroepct', 'Return on average equity', 'Management Effectiveness', 'Percentage'),
    ('aroipct', 'Return on investment', 'Management Effectiveness', 'Percentage'),
    ('atanbvps', 'Book value (tangible) per Share', 'Per Share Ratios', 'Actual Values'),
    ('atotd2eq', 'Total debt/total equity', 'Financial Strength', 'Percentage'),
    ('beta', 'Beta, compared to major market index', 'Price Related', 'Actual Values'),
    ('bvtrendgr', 'Book value per Share growth rate, 5 year CAGR', 'Growth Rates', 'Percentage'),
    ('csptrendgr', 'Capital Spending growth rate, 5 year CAGR', 'Growth Rates', 'Percentage'),
    ('divgrpct', 'Ordinary Dividend growth rate, 3 year CAGR', 'Growth Rates', 'Percentage'),
    ('divyield_curttm', 'Current Dividend Yield, trailing 12 months', 'Dividend', 'Percentage'),
    ('ebitda_ayr5cagr', 'Earnings Before Interest, Taxes, Depreciation & Amortization, 5 Year CAGR', 'Growth Rates', 'Percentage'),
    ('ebitda_ttmy5cagr', 'Earnings Before Interest, Taxes, Depreciation & Amortization, 5 Year TTM CAGR', 'Growth Rates', 'Percentage'),
    ('epsactual', 'Previous Actual Annual EPS', 'Other', 'USD'),
    ('epsactualq', 'Previous Actual Quarterly EPS', 'Other', 'USD'),
    ('epschngyr', 'EPS Change %, most recent quarter 1 year ago', 'Growth Rates', 'Percentage'),
    ('epsgrpct', 'EPS growth rate, 3 year CAGR', 'Growth Rates', 'Percentage'),
    ('epssurprise', 'Previous Annual Surprise', 'Other', 'USD'),
    ('epssurpriseprc', 'Previous Annual Surprise as a Percentage', 'Other', 'USD'),
    ('epssurpriseq', 'Previous Quarter Surprise', 'Other', 'USD'),
    ('epssurpriseqprc', 'Previous Quarter Surprise as a Percentage', 'Other', 'USD'),
    ('epstrendgr', 'EPS growth rate, 5 year CAGR', 'Growth Rates', 'Percentage'),
    ('ev2fcf_cura', 'Current Enterprise Value/Free Cash Flow, most recent fiscal year', 'Financial Strength', 'Actual Values'),
    ('ev2fcf_curttm', 'Current Enterprise value/Free Cash Flow, trailing 12 months', 'Financial Strength', 'Actual Values'),
    ('focf2rev_aavg5', 'Free Operating Cash Flow/Revenue, 5 Year Average', 'Profitability Ratios', 'Percentage'),
    ('focf2rev_ttm', 'Free Operating Cash Flow/Revenue', 'Profitability Ratios', 'Percentage'),
    ('focf_ayr5cagr', 'Free Operating Cash Flow growth rate, 5 Year CAGR', 'Growth Rates', 'Percentage'),
    ('grosmgn5yr', 'Gross Margin, 5 year average', 'Profitability Ratios', 'Percentage'),
    ('margin5yr', 'Net Profit Margin, 5 year average', 'Profitability Ratios', 'Percentage'),
    ('mktcap', 'Market capitalization, includes all classes of securities/listings', 'Share Related Items', 'Millions'),
    ('netdebt_a', 'Net Debt', 'Balance Sheet', 'Millions'),
    ('netdebt_i', 'Net Debt', 'Balance Sheet', 'Millions'),
    ('npmtrendgr', 'Net Profit Margin growth rate, 5 year CAGR', 'Growth Rates', 'Percentage'),
    ('opmgn5yr', 'Operating Margin, 5 year average', 'Profitability Ratios', 'Percentage'),
    ('pebexclxor', 'P/E Basic excluding extraordinary items, trailing 12 months', 'Price Related', 'Actual Values'),
    ('peexclxor', 'Price-to-Earnings Ratio (P/E) excluding extraordinary items, trailing 12 months', 'Price Related', 'Actual Values'),
    ('peinclxor', 'P/E including extraordinary items, trailing 12 months', 'Price Related', 'Actual Values'),
    ('pr2tanbk', 'Price to Tangible Book, most recent quarter', 'Price Related', 'Actual Values'),
    ('price2bk', 'Price to Book, most recent quarter', 'Price Related', 'Actual Values'),
    ('projdps', 'Current Consensus for Annual Total Dividend Per Share', 'Other', 'USD'),
    ('projdpsh', 'High Estimate', 'Other', 'USD'),
    ('projdpsl', 'Low Estimate', 'Other', 'USD'),
    ('projdpsnumofest', 'Number of Estimates', 'Other', 'USD'),
    ('projeps', 'Current Consensus for Annual EPS', 'Other', 'USD'),
    ('projepsh', 'High Estimate', 'Other', 'USD'),
    ('projepsl', 'Low Estimate', 'Other', 'USD'),
    ('projepsnumofest', 'Number of Estimates', 'Other', 'USD'),
    ('projepsq', 'Current Consensus for Quarterly EPS', 'Other', 'USD'),
    ('projepsqh', 'High Estimate', 'Other', 'USD'),
    ('projepsql', 'Low Estimate', 'Other', 'USD'),
    ('projepsqnumofest', 'Number of Estimates', 'Other', 'USD'),
    ('projltgrowthrate', 'Current Consensus for long term (5 year) growth rate of EPS', 'Other', 'USD'),
    ('projprofit', 'Current Consensus for Profit', 'Other', 'USD'),
    ('projprofith', 'High Estimate', 'Other', 'USD'),
    ('projprofitl', 'Low Estimate', 'Other', 'USD'),
    ('projprofitnumofest', 'Number of Estimates', 'Other', 'USD'),
    ('projsalesh', 'High Estimate', 'Other', 'USD'),
    ('projsalesl', 'Low Estimate', 'Other', 'USD'),
    ('projsalesnumofest', 'Number of Estimates', 'Other', 'USD'),
    ('projsalesps', 'Current Consensus for Annual Revenue Per Share', 'Other', 'USD'),
    ('projsalesq', 'Current Consensus for Quarterly Revenue', 'Other', 'USD'),
    ('projsalesqh', 'High Estimate', 'Other', 'USD'),
    ('projsalesql', 'Low Estimate', 'Other', 'USD'),
    ('projsalesqnumofest', 'Number of Estimates', 'Other', 'USD'),
    ('ptmgn5yr', 'Pretax Margin, 5 year average', 'Profitability Ratios', 'Percentage'),
    ('qbvps', 'Book value (total equity) per Share', 'Per Share Ratios', 'Actual Values'),
    ('qcshps', 'Cash per Share', 'Per Share Ratios', 'Actual Values'),
    ('qcurratio', 'Current ratio', 'Financial Strength', 'Actual Values'),
    ('qltd2eq', 'Long Term debt/equity ratio', 'Financial Strength', 'Percentage'),
    ('qquickrati', 'Quick ratio', 'Financial Strength', 'Actual Values'),
    ('qtanbvps', 'Book value (tangible) per Share', 'Per Share Ratios', 'Actual Values'),
    ('qtotd2eq', 'Total debt/total equity ratio', 'Financial Strength', 'Percentage'),
    ('revchngyr', 'Revenue Change %, most recent quarter vs 1 year ago', 'Growth Rates', 'Percentage'),
    ('revgrpct', 'Revenue growth rate, 3 year CAGR', 'Growth Rates', 'Percentage'),
    ('revps5ygr', 'Revenue per Share growth rate, 5 yr CAGR', 'Growth Rates', 'Percentage'),
    ('revtrendgr', 'Revenue growth rate, 5 year CAGR', 'Growth Rates', 'Percentage'),
    ('stld_ayr5cagr', 'Total Debt growth rate, 5 Year CAGR', 'Growth Rates', 'Percentage'),
    ('tanbv_ayr5cagr', 'Tangible Book Value (Total Equity) growth rate, 5 Year CAGR', 'Growth Rates', 'Percentage'),
    ('targetprice', 'Current 12 month Consensus Target Price', 'Other', 'USD'),
    ('ttmastturn', 'Asset turnover', 'Efficiency Ratios', 'Actual Values'),
    ('ttmbepsxcl', 'EPS Basic excluding extraordinary items', 'Per Share Ratios', 'Actual Values'),
    ('ttmcfshr', 'Cash Flow per Share', 'Per Share Ratios', 'Actual Values'),
    ('ttmdivshr', 'Ordinary Dividends per share', 'Dividend', 'Actual Values'),
    ('ttmdivshradj', 'Ordinary Dividends per Share (fully adjusted)', 'Dividend', 'Actual Values'),
    ('ttmebitd', 'Earnings Before Interest, Taxes, Depreciation (EBITD)', 'Income Statement', 'Millions'),
    ('ttmebitdps', 'EBITD per Share', 'Per Share Ratios', 'Actual Values'),
    ('ttmebt', 'Earnings before taxes', 'Income Statement', 'Millions'),
    ('ttmepschg', 'EPS Change %, TTM over TTM', 'Growth Rates', 'Percentage'),
    ('ttmepsincx', 'EPS including extraordinary items', 'Per Share Ratios', 'Actual Values'),
    ('ttmepsxclx', 'EPS excluding extraordinary items', 'Per Share Ratios', 'Actual Values'),
    ('ttmfcf', 'Free Cash Flow', 'Cash Flow', 'Millions'),
    ('ttmfcfshr', 'Free Cash Flow per Share', 'Per Share Ratios', 'Actual Values'),
    ('ttmgrosmgn', 'Gross Margin', 'Profitability Ratios', 'Percentage'),
    ('ttmintcov', 'Net Interest coverage', 'Financial Strength', 'Actual Values'),
    ('ttminvturn', 'Inventory turnover', 'Efficiency Ratios', 'Actual Values Efficiency Ratios'),
    ('ttmniac', 'Net Income accruing to common shares for dividends and retained earnings', 'Income Statement', 'Millions'),
    ('ttmniperem', 'Net Income/employee', 'Efficiency Ratios', 'Actual Values Efficiency Ratios'),
    ('ttmnpmgn', 'Net Profit Margin %', 'Profitability Ratios', 'Percentage'),
    ('ttmopmgn', 'Operating margin', 'Profitability Ratios', 'Percentage'),
    ('ttmpayrat', 'Payout ratio', 'Financial Strength', 'Percentage'),
    ('ttmpehigh', 'P/E excluding extraordinary items high, trailing 12 months', 'Price Related', 'Actual Values'),
    ('ttmpelow', 'P/E excluding extraordinary items low, trailing 12 months', 'Price Related', 'Actual Values'),
    ('ttmpr2rev', 'Price to sales, trailing 12 month', 'Price Related', 'Actual Values'),
    ('ttmprcfps', 'Price to Cash Flow per Share, trailing 12 month', 'Price Related', 'Actual Values'),
    ('ttmprfcfps', 'Price to Free Cash Flow per Share, trailing 12 months', 'Price Related', 'Actual Values'),
    ('ttmptmgn', 'Pretax margin', 'Profitability Ratios', 'Percentage'),
    ('ttmrecturn', 'Receivables turnover', 'Efficiency Ratios', 'Actual Values Efficiency Ratios'),
    ('ttmrev', 'Revenue', 'Income Statement', 'Millions'),
    ('ttmrevchg', 'Revenue Change %, TTM over TTM', 'Growth Rates', 'Percentage'),
    ('ttmrevpere', 'Revenue/employee', 'Efficiency Ratios', 'Actual Values Efficiency Ratios'),
    ('ttmrevps', 'Revenue per share', 'Per Share Ratios', 'Actual Values'),
    ('ttmroapct', 'Return on average assets', 'Management Effectiveness', 'Percentage'),
    ('ttmroepct', 'Return on average equity', 'Management Effectiveness', 'Percentage'),
    ('ttmroipct', 'Return on investment', 'Management Effectiveness', 'Percentage'),
    ('vdes_ttm', 'Earnings per Share (EPS), Normalized, Excluding Extraordinary Items, Avg. Diluted Shares Outstanding', 'Income Statement', 'Actual Values'),
    ('yld5yavg', 'Ordinary Dividend Yield, 5 Year Average', 'Dividend', 'Percentage')
ON CONFLICT (metric_code) DO UPDATE SET
    metric_name  = EXCLUDED.metric_name,
    stmt_code    = EXCLUDED.stmt_code,
    default_unit = EXCLUDED.default_unit;

COMMIT;