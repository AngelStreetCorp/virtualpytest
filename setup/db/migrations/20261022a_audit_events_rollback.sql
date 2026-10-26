-- Rollback of 20261022a_audit_events.sql (TASK-154). No other table depends on it.
-- CASCADE on the function removes the audit_events_login trigger on auth.users.
BEGIN;
DROP FUNCTION IF EXISTS public.audit_events_log_login() CASCADE;
DROP TABLE IF EXISTS public.audit_events;
COMMIT;
