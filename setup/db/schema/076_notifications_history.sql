-- 076 — notification history per account (TASK-145 follow-up). Same content as migration 20261020f_notifications_history.sql.
BEGIN;

CREATE TABLE IF NOT EXISTS public.notifications (
    team_id    UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL,
    id         TEXT NOT NULL,
    category   TEXT NOT NULL DEFAULT 'action' CHECK (category IN
                 ('device', 'host', 'script', 'capture', 'ai_spend', 'storage', 'deploy', 'security', 'support', 'action')),
    severity   TEXT NOT NULL CHECK (severity IN ('error', 'warning', 'info', 'success')),
    message    TEXT NOT NULL,
    vars       JSONB,
    to_path    TEXT,
    scope      JSONB,
    ts         BIGINT NOT NULL,
    read       BOOLEAN NOT NULL DEFAULT FALSE,
    dismissed  BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (team_id, user_id, id)
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_ts ON public.notifications (team_id, user_id, ts DESC);

COMMENT ON TABLE public.notifications IS
    'TASK-145: the bell / Notifications page history, per user, newest 200. Client: frontend/src/contexts/notificationStore.ts. Routes: /server/notifications.';

ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_notifications" ON public.notifications;
CREATE POLICY "service_role_all_notifications" ON public.notifications FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.notifications FROM anon, authenticated;

COMMIT;
