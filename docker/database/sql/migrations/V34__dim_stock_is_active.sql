/* ------------------------------------------------------------
   V34__dim_stock_is_active.sql
   Adds an is_active flag to dim_stock and initializes it.
   - Defaults to TRUE for all existing rows
   - Sets FALSE for symbols suffixed with '-YYYYMM'
   - Adds a simple index for filtering
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- 1) Add column with default
ALTER TABLE rankalpha.dim_stock
  ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT TRUE;

-- 2) Initialize: mark delisted-style tickers (e.g., ABC-202401) as inactive
UPDATE rankalpha.dim_stock
   SET is_active = FALSE
 WHERE symbol ~ '-[0-9]{6}$';

-- 3) Helpful index for filtering
CREATE INDEX IF NOT EXISTS idx_dim_stock_is_active
  ON rankalpha.dim_stock (is_active);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

