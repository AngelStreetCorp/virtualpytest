-- TASK-145 follow-up — notification history per account (was localStorage per browser).
-- One row = one notification of one user; (team_id, user_id, id) is the episode key the app uses.
-- `dismissed` rows stay as tombstones so a browser with an old local cache does not bring them back.
-- The server keeps the newest 200 rows per user (trimmed on insert). user_id is TEXT, no FK (the auto-sign
-- test principal has no UUID). RLS: service_role only; the server filters team_id and the caller's user_id.
-- Same content as schema/076_notifications_history.sql. Idempotent.
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
