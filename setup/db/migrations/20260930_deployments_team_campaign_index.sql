-- ============================================================================
-- Index campaign deployments per team for GET /server/deployment/executions/recent
-- ============================================================================
-- The route's "completed campaigns" list embeds
--     deployments!inner(...) with team_id = X AND campaign_id IS NOT NULL
-- and nothing indexed campaign_id, so Postgres seq-scanned the whole deployments
-- table on every call. Ad-hoc "Run Now" launches each insert one deployments row,
-- so that table grows with every run while campaign rows stay rare.
--
-- Measured on a customer DB (~381k deployments, 4 campaign runs for the team):
--   before  Parallel Seq Scan on deployments, 31873 buffers read (~250 MB),
--           64.6 ms idle; six admins' browsers refresh together on each
--           terminal deployment event, so the route logged queries=1.28s.
--   after   index probe, ~1 ms.
--
-- DEPLOY NOTES
--   * Built CONCURRENTLY so it never blocks deployments writes. CONCURRENTLY
--     cannot run inside a transaction block - run this file standalone (the
--     Supabase SQL editor / CLI may wrap it: drop the keyword there, the build
--     takes a few seconds on 400k rows).
--   * DB-only: no application change needed.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_deployments_team_campaign
    ON public.deployments (team_id)
    WHERE campaign_id IS NOT NULL;

COMMENT ON INDEX public.idx_deployments_team_campaign IS
    'Campaign deployments per team: keeps the completed-campaigns leg of /server/deployment/executions/recent off a seq scan of deployments.';

ANALYZE public.deployments;
