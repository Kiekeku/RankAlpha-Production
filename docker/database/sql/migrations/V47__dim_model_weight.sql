/* ------------------------------------------------------------
   V47__dim_model_weight.sql
   Create table to persist factor combination weights (momentum/value/sentiment).
   Weights are computed by scorer (hybrid IC + risk parity) and referenced by MV.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE TABLE IF NOT EXISTS rankalpha.dim_model_weight (
  weight_id          BIGSERIAL PRIMARY KEY,
  as_of_date         DATE NOT NULL,
  method             TEXT NOT NULL DEFAULT 'HYBRID_IC_RP',
  window_days        INT  NOT NULL,
  horizon_days       INT  NOT NULL,
  w_momentum         NUMERIC(6,4) NOT NULL,
  w_value            NUMERIC(6,4) NOT NULL,
  w_sentiment        NUMERIC(6,4) NOT NULL,
  lambda_rp          NUMERIC(6,4) NOT NULL,
  alpha_shrink       NUMERIC(6,4) NOT NULL,
  sentiment_coverage NUMERIC(6,4) NULL,
  notes              TEXT NULL,
  created_at         TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS dim_model_weight_unique_idx
  ON rankalpha.dim_model_weight (as_of_date, method);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

