/* ------------------------------------------------------------
   V112__portfolio_instrument_type_expansion.sql
   - Expand portfolio_instrument_type enum for future instruments.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

ALTER TYPE rankalpha.portfolio_instrument_type ADD VALUE IF NOT EXISTS 'ETF';
ALTER TYPE rankalpha.portfolio_instrument_type ADD VALUE IF NOT EXISTS 'FX';
ALTER TYPE rankalpha.portfolio_instrument_type ADD VALUE IF NOT EXISTS 'FUTURE';
ALTER TYPE rankalpha.portfolio_instrument_type ADD VALUE IF NOT EXISTS 'OPTION';
ALTER TYPE rankalpha.portfolio_instrument_type ADD VALUE IF NOT EXISTS 'BOND';
ALTER TYPE rankalpha.portfolio_instrument_type ADD VALUE IF NOT EXISTS 'CRYPTO';

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

