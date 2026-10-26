-- TASK-128 G9: Platform update settings (frontend target, SSH user/key, DB connection, agent token, GitHub token), one row per key.
-- Per SERVER, not per team: like applied_migrations, the schema belongs to the install and the settings describe how THIS server
-- updates its machines, so there is no team_id. server_name = this server's SERVER_NAME (a database can serve several servers).
-- Service role only; secrets (is_secret) are never returned by the API.
-- WRITTEN, NOT APPLIED. Idempotent. Until it is applied the server keeps using its JSON file store (GET /settings says storage "file").
-- Twin: setup/db/schema/072_platform_update_settings.sql. Inverse: 20261018g_platform_update_settings_rollback.sql.

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
