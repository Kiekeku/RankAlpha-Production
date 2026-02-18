/* ------------------------------------------------------------
   V107__mv_universe_eligible_normalize_asset_types.sql
   - Expand universe_policy.allowed_asset_types to include common case/synonym variants
     (Equity/ETP) produced by upstream processes.
   - Refresh mv_universe_eligible to pick up the new policy.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

UPDATE rankalpha.universe_policy p
SET allowed_asset_types = (
    SELECT ARRAY_AGG(DISTINCT x ORDER BY x)
    FROM unnest(p.allowed_asset_types || ARRAY['Equity','ETP','etp','ETF']) AS x
),
    updated_at = now()
WHERE p.policy_code = 'default';

-- Flyway runs migrations in a transaction; REFRESH CONCURRENTLY is not allowed.
REFRESH MATERIALIZED VIEW rankalpha.mv_universe_eligible;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
