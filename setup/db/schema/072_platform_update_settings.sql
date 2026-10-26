-- 072 — platform_update_settings (TASK-128 G9). Same content as migration 20261018g_platform_update_settings.sql.
-- WRITTEN, NOT APPLIED. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS public.platform_update_settings (
    server_name TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    is_secret   BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (server_name, key)
);

COMMENT ON TABLE public.platform_update_settings IS
    'TASK-128: Platform update settings of one server (server_name = SERVER_NAME). Not team-scoped: it configures the install, like applied_migrations.';

ALTER TABLE public.platform_update_settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_platform_update_settings" ON public.platform_update_settings;
CREATE POLICY "service_role_all_platform_update_settings" ON public.platform_update_settings
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.platform_update_settings FROM anon, authenticated;

COMMIT;
