-- Inverse of 20261020d_notification_prefs.sql (drops every saved notification preference).
BEGIN;
DROP TABLE IF EXISTS public.notification_prefs;
COMMIT;
