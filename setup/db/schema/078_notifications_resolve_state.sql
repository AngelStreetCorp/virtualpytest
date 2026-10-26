-- 078 — notification resolve state (TASK-100). Same content as migration 20261021a_notifications_resolve_state.sql.
-- See public.notifications in 076; this adds `resolved_at`. The existing `dismissed` tombstone handles user close.
BEGIN;

ALTER TABLE public.notifications
    ADD COLUMN IF NOT EXISTS resolved_at BIGINT;

CREATE INDEX IF NOT EXISTS idx_notifications_resolved_at
    ON public.notifications (team_id, user_id, resolved_at)
    WHERE resolved_at IS NOT NULL;

COMMENT ON COLUMN public.notifications.resolved_at IS
    'TASK-100: epoch ms when the platform saw the underlying condition clear. NULL = still live.';

COMMIT;
