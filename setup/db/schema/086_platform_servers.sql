-- 086 — platform_servers (TASK-179 P1). Same content as migration 20261026a_platform_servers.sql.
-- WRITTEN, NOT APPLIED. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS public.platform_servers (
    name        TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT platform_servers_name_chk CHECK (name ~ '^[A-Za-z0-9][A-Za-z0-9_-]*$'),
    CONSTRAINT platform_servers_url_origin_chk CHECK (url ~ '^https?://[^/?#[:space:]]+$')
);

CREATE UNIQUE INDEX IF NOT EXISTS platform_servers_name_lower_uq ON public.platform_servers (lower(name));

COMMENT ON TABLE public.platform_servers IS
    'TASK-179: the platform''s servers (name = SERVER_NAME, url = public origin). Not team-scoped: it lists the platform''s machines, like platform_update_settings.';

ALTER TABLE public.platform_servers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_platform_servers" ON public.platform_servers;
CREATE POLICY "service_role_all_platform_servers" ON public.platform_servers
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.platform_servers FROM anon, authenticated;

INSERT INTO public.platform_servers (name, url, sort_order) VALUES
    ('Awesomation',        'https://virtualpytest.angelstreet.io',        0),
    ('vpt-pi1',            'https://vpt-pi1.angelstreet.io',             10),
    ('vpt-pi4',            'https://vpt-pi4.angelstreet.io',             20),
    ('QualiAI',            'https://virtualpytest.qualiai.io',           30),
    ('gcloud-standalone',  'https://gcloudstandalone-api.virtualpytest.com', 40)
ON CONFLICT DO NOTHING;

COMMIT;
