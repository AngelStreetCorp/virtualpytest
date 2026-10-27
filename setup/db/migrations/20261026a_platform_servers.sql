-- TASK-179 P1: the platform's one list of servers (name, public origin). Read by every server (cached 60 s) and by the frontend.
-- Platform-level, so no team_id: the servers are the platform's machines, same reasoning as platform_update_settings (20261018g).
-- Service role only; the API (GET /server/servers any signed-in user, PUT platform admin) is the only way in.
-- name = that server's SERVER_NAME (case kept, matched case-insensitively). url = public origin, no path.
-- APPLIED on node1 (192.168.0.102) 2026-10-26. Idempotent. Twin: setup/db/schema/086_platform_servers.sql. Inverse: 20261026a_platform_servers_rollback.sql.

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
