-- 20260929c_role_catalog.sql
-- TASK-31 phase A — a catalog of system roles, two new roles, and external aliases.
--
--   * public.roles: one row per system role with its display name. The role ids are fixed
--     (admin, manager, developer, tester, viewer); what an installation calls them is data,
--     edited on the Roles page.
--   * public.role_aliases: the name an external provisioning system uses for a role
--     (provider_type 'idp' sends "DevUser" -> developer). Not seeded: each installation
--     adds its own from the Roles page or PUT /server/roles/<role>.
--   * profiles.role and role_permissions.role now reference roles(role) instead of each
--     carrying its own CHECK list.
--   * role_permissions gains the two new editable roles, manager and developer. Admin still
--     has no row: it holds every permission and never consults the table.
--
-- Requires 20260929a_role_permissions.sql and 20260929b_role_page_view_permissions.sql.
-- Canonical twin for fresh installs: setup/db/schema/053_role_catalog.sql.
-- RLS: service_role only, anon/authenticated revoked (post-TASK-10 posture).
-- Idempotent: safe to re-run; never overwrites edited rows.
-- Inverse: 20260929c_role_catalog_rollback.sql.

BEGIN;

-- ------------------------------------------------------------------ roles
CREATE TABLE IF NOT EXISTS public.roles (
    role         TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    updated_by   UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT roles_role_check
        CHECK (role IN ('admin', 'manager', 'developer', 'tester', 'viewer')),
    CONSTRAINT roles_display_name_not_blank
        CHECK (length(btrim(display_name)) > 0)
);

COMMENT ON TABLE public.roles IS
    'System roles and the name this installation shows for each. Role ids are fixed; '
    'the rank between them lives in code (auth_middleware.ROLE_RANK).';

INSERT INTO public.roles (role, display_name) VALUES
    ('admin',     'Admin'),
    ('manager',   'Manager'),
    ('developer', 'Developer'),
    ('tester',    'Tester'),
    ('viewer',    'Viewer')
ON CONFLICT (role) DO NOTHING;

-- ------------------------------------------------------------ role_aliases
CREATE TABLE IF NOT EXISTS public.role_aliases (
    provider_type TEXT NOT NULL,
    external_name TEXT NOT NULL,
    role          TEXT NOT NULL REFERENCES public.roles(role) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT role_aliases_provider_not_blank CHECK (length(btrim(provider_type)) > 0),
    CONSTRAINT role_aliases_name_not_blank     CHECK (length(btrim(external_name)) > 0)
);

-- One meaning per external name, whatever its case.
CREATE UNIQUE INDEX IF NOT EXISTS role_aliases_provider_name_key
    ON public.role_aliases (lower(provider_type), lower(external_name));

COMMENT ON TABLE public.role_aliases IS
    'Role names used by external provisioning systems (provider_type as in profiles.provider_type).';

-- ---------------------------------------------- profiles.role -> roles(role)
ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_role_check;
ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_role_fkey;
ALTER TABLE public.profiles
    ADD CONSTRAINT profiles_role_fkey FOREIGN KEY (role) REFERENCES public.roles(role);

-- ------------------------------------- role_permissions.role -> roles(role)
ALTER TABLE public.role_permissions DROP CONSTRAINT IF EXISTS role_permissions_role_check;
ALTER TABLE public.role_permissions DROP CONSTRAINT IF EXISTS role_permissions_role_fkey;
ALTER TABLE public.role_permissions
    ADD CONSTRAINT role_permissions_role_fkey FOREIGN KEY (role) REFERENCES public.roles(role);
-- Admin holds everything and never has a row.
ALTER TABLE public.role_permissions
    ADD CONSTRAINT role_permissions_role_check CHECK (role <> 'admin');

COMMENT ON TABLE public.role_permissions IS
    'Default permissions per editable system role (manager, developer, tester, viewer). Admin '
    'holds everything and has no row. Read by the backend auth middleware (TTL-cached) and '
    'GET /server/roles.';

-- Same seed as setup/db/schema/053_role_catalog.sql.
INSERT INTO public.role_permissions (role, permissions) VALUES
('manager', '[
    "dashboard:view",
    "device_control:view", "device_control:execute",
    "device_control:reboot", "device_control:restart_streams",
    "testcases:view", "testcases:create", "testcases:edit", "testcases:delete", "testcases:hide",
    "campaigns:view", "campaigns:create", "campaigns:edit", "campaigns:delete", "campaigns:execute",
    "builder.test:view", "builder.test:use",
    "builder.campaign:view", "builder.campaign:use",
    "execution.run:view", "execution.run:run_test", "execution.run:run_campaign",
    "execution.monitor:view",
    "execution.build:view", "execution.build:use",
    "reports.tests:view", "reports.campaigns:view",
    "reports.models:view", "reports.dependency:view",
    "monitoring.incidents:view", "monitoring.heatmap:view", "monitoring.ai_queue:view",
    "interface:view", "interface:create", "interface:edit", "interface:delete",
    "ai_agent:view", "ai_agent:use",
    "plugins.grafana:view", "plugins.langfuse:view", "plugins.postman:view",
    "plugins.jira:view", "plugins.jira:manage", "plugins.testrail:view", "plugins.slack:view",
    "settings.cicd:view",
    "settings.status:view",
    "org.users:view", "org.users:create", "org.users:edit",
    "org.teams:view", "org.teams:manage_members",
    "org.invite:send"
]'::jsonb),
('developer', '[
    "dashboard:view",
    "device_control:view", "device_control:execute",
    "testcases:view", "testcases:create", "testcases:edit", "testcases:hide",
    "campaigns:view", "campaigns:create", "campaigns:edit", "campaigns:execute",
    "builder.test:view", "builder.test:use",
    "builder.campaign:view", "builder.campaign:use",
    "execution.run:view", "execution.run:run_test", "execution.run:run_campaign",
    "execution.monitor:view",
    "execution.build:view", "execution.build:use",
    "reports.tests:view", "reports.campaigns:view",
    "reports.models:view", "reports.dependency:view",
    "monitoring.incidents:view", "monitoring.heatmap:view", "monitoring.ai_queue:view",
    "interface:view", "interface:create", "interface:edit", "interface:delete",
    "ai_agent:view", "ai_agent:use",
    "plugins.grafana:view", "plugins.langfuse:view", "plugins.postman:view",
    "plugins.jira:view", "plugins.jira:manage", "plugins.testrail:view", "plugins.slack:view",
    "settings.cicd:view",
    "settings.status:view"
]'::jsonb)
ON CONFLICT (role) DO NOTHING;

-- ---------------------------------------------------------------- RLS
ALTER TABLE public.roles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_roles" ON public.roles;
CREATE POLICY "service_role_all_roles" ON public.roles
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.roles FROM anon, authenticated;

ALTER TABLE public.role_aliases ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_role_aliases" ON public.role_aliases;
CREATE POLICY "service_role_all_role_aliases" ON public.role_aliases
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.role_aliases FROM anon, authenticated;

COMMIT;
