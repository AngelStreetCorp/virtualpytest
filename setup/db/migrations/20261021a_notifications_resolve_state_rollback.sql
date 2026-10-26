BEGIN;

DROP INDEX IF EXISTS public.idx_notifications_resolved_at;

ALTER TABLE public.notifications
    DROP COLUMN IF EXISTS resolved_at;

COMMIT;
