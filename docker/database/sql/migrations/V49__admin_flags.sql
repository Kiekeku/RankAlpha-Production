/* ------------------------------------------------------------
   V49__admin_flags.sql
   Admin flags for operational toggles (set via API).
   - force_recompute_weights: when true, scorer recomputes hybrid weights on next run
     and resets the flag to false after upsert.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE TABLE IF NOT EXISTS rankalpha.admin_flag (
  flag_name   TEXT PRIMARY KEY,
  flag_value  BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
);

/* Seed known flags (idempotent) */
INSERT INTO rankalpha.admin_flag(flag_name, flag_value)
VALUES ('force_recompute_weights', FALSE)
ON CONFLICT (flag_name) DO NOTHING;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

