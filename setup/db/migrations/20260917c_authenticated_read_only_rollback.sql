-- Rollback for 20260917c_authenticated_read_only.sql (TASK-22).
-- Restores the pre-TASK-22 grants. This REOPENS the privilege-escalation path
-- described in that migration — only run it to unblock a broken deployment, and
-- close signup (GOTRUE DISABLE_SIGNUP=true) for as long as it is rolled back.
BEGIN;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON public.profiles, public.team_members
    TO authenticated;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON SEQUENCES TO anon, authenticated;

COMMIT;
