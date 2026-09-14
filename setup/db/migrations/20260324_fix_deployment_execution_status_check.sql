-- =====================================================
-- Migration: align deployment_executions.status with scheduler/runtime code
-- The host scheduler and server routes persist queued, skipped, and aborted.
-- Older databases still reject some of these values via deployment_executions_status_check.
-- =====================================================

ALTER TABLE public.deployment_executions
  DROP CONSTRAINT IF EXISTS deployment_executions_status_check,
  ADD CONSTRAINT deployment_executions_status_check
  CHECK (status IN ('running', 'completed', 'failed', 'skipped', 'queued', 'aborted'));
