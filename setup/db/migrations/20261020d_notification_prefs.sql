-- TASK-145 — notification preferences (categories x channels), per team / workspace / project / user.
-- One row = one category's channels at one scope. Non-user rows (team, workspace, project) are written by a
-- team admin only (the server enforces it); a user row belongs to one user. user_id is '' for non-user rows so the
-- unique key needs no NULL handling; it is TEXT with no FK (the auto-sign test principal has no UUID).
-- RLS by team: service_role only (the server reads and writes it, every query filters team_id). Idempotent.
-- Same content as schema/075_notification_prefs.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.notification_prefs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id      UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    scope_type   TEXT NOT NULL CHECK (scope_type IN ('team', 'workspace', 'project', 'user')),
    scope_id     TEXT NOT NULL,
    user_id      TEXT NOT NULL DEFAULT '',
    category     TEXT NOT NULL CHECK (category IN
                   ('device', 'host', 'script', 'capture', 'ai_spend', 'storage', 'deploy', 'security', 'support', 'action')),
    bell         BOOLEAN NOT NULL DEFAULT TRUE,
    toast        BOOLEAN NOT NULL DEFAULT FALSE,
    email        BOOLEAN NOT NULL DEFAULT FALSE,
    min_severity TEXT NOT NULL DEFAULT 'info' CHECK (min_severity IN ('info', 'warning', 'error')),
    muted_until  TIMESTAMPTZ,
    locked       BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT notification_prefs_unique UNIQUE (team_id, scope_type, scope_id, user_id, category)
);

CREATE INDEX IF NOT EXISTS idx_notification_prefs_team ON public.notification_prefs (team_id, user_id);

COMMENT ON TABLE public.notification_prefs IS
    'TASK-145: which notification categories reach the bell / toast / email, per team, workspace, project or user. Most specific scope wins; a locked row cannot be overridden. Resolution: frontend/src/contexts/notificationStore.ts resolvePrefs.';

ALTER TABLE public.notification_prefs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_notification_prefs" ON public.notification_prefs;
CREATE POLICY "service_role_all_notification_prefs" ON public.notification_prefs FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.notification_prefs FROM anon, authenticated;

COMMIT;
