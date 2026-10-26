-- TASK-154: record sign-outs. GoTrue writes 'logout' to auth.audit_log_entries; failed sign-ins are
-- not written there at all (verified: no error entries in 8k rows), so they stay unrecorded.
-- Additive and idempotent. Rollback: 20261022b_audit_events_logout_rollback.sql.

BEGIN;

CREATE OR REPLACE FUNCTION public.audit_events_log_logout() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NEW.payload->>'action' = 'logout' THEN
        INSERT INTO public.audit_events (at, actor_kind, actor_id, actor_email, category, action, target, outcome)
        VALUES (NEW.created_at, 'user', NEW.payload->>'actor_id', NEW.payload->>'actor_username',
                'auth', 'auth.logout', NEW.payload->>'actor_id', 'ok');
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RETURN NEW;  -- auditing must never block a sign-out
END $$;
REVOKE ALL ON FUNCTION public.audit_events_log_logout() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS audit_events_logout ON auth.audit_log_entries;
CREATE TRIGGER audit_events_logout AFTER INSERT ON auth.audit_log_entries
    FOR EACH ROW EXECUTE FUNCTION public.audit_events_log_logout();

COMMIT;
