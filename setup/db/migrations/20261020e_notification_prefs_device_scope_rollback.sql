BEGIN;
DELETE FROM public.notification_prefs WHERE scope_type = 'device';
ALTER TABLE public.notification_prefs DROP CONSTRAINT IF EXISTS notification_prefs_scope_type_check;
ALTER TABLE public.notification_prefs ADD CONSTRAINT notification_prefs_scope_type_check
    CHECK (scope_type IN ('team', 'workspace', 'project', 'user'));
COMMIT;
