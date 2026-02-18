/* ------------------------------------------------------------
   V114__dim_date_set_weekday_trading_flag.sql
   - The initial calendar population (V2) does not set is_trading_day, so it
     defaults to TRUE for every date (including weekends).
   - Many API queries treat is_trading_day as a Mon–Fri trading calendar.
   - This migration sets is_trading_day to TRUE on weekdays and FALSE on weekends.
     (US market holidays are not modeled here.)
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

UPDATE rankalpha.dim_date
SET is_trading_day = (day_of_week BETWEEN 1 AND 5);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
