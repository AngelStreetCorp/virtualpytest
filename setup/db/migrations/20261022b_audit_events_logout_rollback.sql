-- Rollback of 20261022b_audit_events_logout.sql (TASK-154). CASCADE removes the trigger on auth.audit_log_entries.
BEGIN;
DROP FUNCTION IF EXISTS public.audit_events_log_logout() CASCADE;
COMMIT;
