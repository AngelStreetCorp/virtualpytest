-- ============================================================================
-- Rollback for 20260930_deployments_team_campaign_index.sql
-- ============================================================================
-- Reinstates the seq scan of deployments on every /executions/recent call.
-- CONCURRENTLY cannot run inside a transaction block - run this file standalone.

DROP INDEX CONCURRENTLY IF EXISTS public.idx_deployments_team_campaign;
