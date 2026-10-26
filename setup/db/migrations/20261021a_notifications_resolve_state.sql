-- TASK-100 — notification resolve state. One optional column on public.notifications:
-- resolved_at: the platform saw the underlying condition clear; the row stays in the bell for a 2 h
-- grace then is auto-purged. NULL = still live. `dismissed` (the existing task-145 tombstone) is
-- unchanged: the X still drops the row from server-side history at once.
-- Rows from before this migration simply have NULL.
BEGIN;

ALTER TABLE public.notifications
    ADD COLUMN IF NOT EXISTS resolved_at BIGINT;

-- Optional: a partial index on resolved items so the grace-period purge is cheap once the table grows.
CREATE INDEX IF NOT EXISTS idx_notifications_resolved_at
    ON public.notifications (team_id, user_id, resolved_at)
    WHERE resolved_at IS NOT NULL;

COMMENT ON COLUMN public.notifications.resolved_at IS
    'TASK-100: epoch ms when the platform saw the underlying condition clear. NULL = still live.';

COMMIT;
