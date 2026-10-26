-- TASK-154: one append-only audit table for what every user, AI agent, host and cron job did.
-- Written by the servers (service role) through shared/src/lib/database/audit_events_db.py.
-- Logins are written by a trigger on auth.users, the one layer that sees every sign-in path.
-- Additive and idempotent. Rollback: 20261022a_audit_events_rollback.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.audit_events (
    id            BIGSERIAL PRIMARY KEY,
    at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    team_id       UUID,
    actor_kind    TEXT NOT NULL DEFAULT 'system'
                   CHECK (actor_kind IN ('user','agent','host','cron','service','system')),
    actor_id      TEXT,
    actor_email   TEXT,
    actor_role    TEXT,
    category      TEXT NOT NULL
                   CHECK (category IN ('auth','api','control','ai','deploy','test','admin','system')),
    action        TEXT NOT NULL,
    target        TEXT,
    outcome       TEXT NOT NULL DEFAULT 'ok'
                   CHECK (outcome IN ('ok','denied','error','refused')),
    method        TEXT,
    status_code   INT,
    duration_ms   INT,
    request_id    TEXT,
    network       JSONB,
    meta          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_audit_events_team_at     ON public.audit_events (team_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor_at    ON public.audit_events (actor_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_category_at ON public.audit_events (category, at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_outcome_at  ON public.audit_events (outcome, at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_at_brin     ON public.audit_events USING BRIN (at);

COMMENT ON TABLE public.audit_events IS
    'TASK-154 audit trail. Append-only. Written by vpt-server (service role) and the auth.users login trigger. '
    'RLS service_role only; anon/authenticated have no grant.';
COMMENT ON COLUMN public.audit_events.network IS
    '{ip_hash, user_agent}; ip is present only when VPT_AUDIT_STORE_RAW_IP=1.';
COMMENT ON COLUMN public.audit_events.meta IS
    'Redacted: no file contents, no env values, no command output, no AI prompt or response bodies. Strings capped.';

ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_audit_events" ON public.audit_events;
CREATE POLICY "service_role_all_audit_events" ON public.audit_events
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.audit_events FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.audit_events_id_seq FROM anon, authenticated;
GRANT ALL ON public.audit_events TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.audit_events_id_seq TO service_role;

-- Login: every sign-in path (password, OAuth, token) advances auth.users.last_sign_in_at.
CREATE OR REPLACE FUNCTION public.audit_events_log_login() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NEW.last_sign_in_at IS NOT NULL
       AND NEW.last_sign_in_at IS DISTINCT FROM OLD.last_sign_in_at THEN
        INSERT INTO public.audit_events (at, actor_kind, actor_id, actor_email, category, action, target, outcome)
        VALUES (NEW.last_sign_in_at, 'user', NEW.id::text, NEW.email, 'auth', 'auth.login', NEW.id::text, 'ok');
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RETURN NEW;  -- auditing must never block a sign-in
END $$;
REVOKE ALL ON FUNCTION public.audit_events_log_login() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS audit_events_login ON auth.users;
CREATE TRIGGER audit_events_login AFTER UPDATE OF last_sign_in_at ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.audit_events_log_login();

COMMIT;
