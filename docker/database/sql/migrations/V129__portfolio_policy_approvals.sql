/* ------------------------------------------------------------
   V129__portfolio_policy_approvals.sql
   Add approval metadata to portfolio_policy_version.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

ALTER TABLE rankalpha.portfolio_policy_version
  ADD COLUMN IF NOT EXISTS approval_status rankalpha.approval_status NOT NULL DEFAULT 'APPROVED',
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS approved_by TEXT;

CREATE INDEX IF NOT EXISTS ix_policy_portfolio_approved
  ON rankalpha.portfolio_policy_version (portfolio_id, approval_status, effective_from DESC);

