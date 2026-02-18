/* ------------------------------------------------------------
   V83__sentiment_queue_force_flag.sql
   - Add force_run flag to sentiment queue for recency overrides.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

ALTER TABLE rankalpha.sentiment_analysis_queue
  ADD COLUMN IF NOT EXISTS force_run BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN rankalpha.sentiment_analysis_queue.force_run IS
  'When true, recency guards are bypassed and the analysis runs even if the stock was analyzed recently.';

