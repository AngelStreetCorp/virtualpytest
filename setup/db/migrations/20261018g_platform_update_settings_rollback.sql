-- Inverse of 20261018g_platform_update_settings.sql (drops the stored settings; the server falls back to its JSON file / .env).
BEGIN;
DROP TABLE IF EXISTS public.platform_update_settings;
COMMIT;
