-- TASK-145 follow-up — a user can mute ONE device: notification_prefs gets scope_type 'device'
-- (scope_id = device_id; user_id = the muting user, or '' for a shared device row). Idempotent.
BEGIN;
ALTER TABLE public.notification_prefs DROP CONSTRAINT IF EXISTS notification_prefs_scope_type_check;
ALTER TABLE public.notification_prefs ADD CONSTRAINT notification_prefs_scope_type_check
    CHECK (scope_type IN ('team', 'workspace', 'project', 'device', 'user'));
COMMIT;
