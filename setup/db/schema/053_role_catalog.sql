-- 053_role_catalog.sql
-- System roles, their preferred names, and the default permissions of
-- every editable role. Canonical fresh-install state of TASK-31 phase A; existing databases
-- get it from the migrations 20260929a_role_permissions.sql, 20260929b_role_page_view_permissions.sql
-- 20260929c_role_catalog.sql and 20260929h_role_preferred_names.sql.
--
-- Role ids are fixed (admin, manager, developer, tester, viewer); their rank lives in code
-- (auth_middleware.ROLE_RANK). Admin holds every permission and has no role_permissions row.
-- A viewer row may only hold `*:view` permissions (enforce_viewer_read_only blocks every write
-- anyway). RLS: service_role only.

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

-- A preferred name maps to exactly one role (an external platform sends it; 20260929h).
CREATE UNIQUE INDEX IF NOT EXISTS roles_display_name_key
    ON public.roles (lower(btrim(display_name)));

-- ---------------------------------------------- profiles.role -> roles(role)
ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_role_check;
ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_role_fkey;
ALTER TABLE public.profiles
    ADD CONSTRAINT profiles_role_fkey FOREIGN KEY (role) REFERENCES public.roles(role);

-- -------------------------------------------------------- role_permissions
CREATE TABLE IF NOT EXISTS public.role_permissions (
    role        TEXT PRIMARY KEY REFERENCES public.roles(role),
    permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_by  UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT role_permissions_role_check
        CHECK (role <> 'admin'),
    CONSTRAINT role_permissions_is_array
        CHECK (jsonb_typeof(permissions) = 'array'),
    CONSTRAINT role_permissions_viewer_view_only
        CHECK (role <> 'viewer'
               OR NOT jsonb_path_exists(permissions, '$[*] ? (!(@ like_regex ":view$"))'))
);

COMMENT ON TABLE public.role_permissions IS
    'Default permissions per editable system role (manager, developer, tester, viewer). Admin '
    'holds everything and has no row. Read by the backend auth middleware (TTL-cached) and '
    'GET /server/roles.';

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
]'::jsonb),
('tester', '[
    "ai_agent:use",
    "ai_agent:view",
    "builder.campaign:use",
    "builder.campaign:view",
    "builder.test:use",
    "builder.test:view",
    "campaigns:create",
    "campaigns:edit",
    "campaigns:execute",
    "campaigns:view",
    "dashboard:view",
    "device_control:execute",
    "device_control:view",
    "execution.build:view",
    "execution.monitor:view",
    "execution.run:run_campaign",
    "execution.run:run_test",
    "execution.run:view",
    "interface:view",
    "monitoring.ai_queue:view",
    "monitoring.heatmap:view",
    "monitoring.incidents:view",
    "plugins.grafana:view",
    "plugins.jira:manage",
    "plugins.jira:view",
    "plugins.langfuse:view",
    "plugins.postman:view",
    "plugins.slack:view",
    "plugins.testrail:view",
    "reports.campaigns:view",
    "reports.dependency:view",
    "reports.models:view",
    "reports.tests:view",
    "settings.status:view",
    "testcases:create",
    "testcases:edit",
    "testcases:hide",
    "testcases:view"
]'::jsonb),
('viewer', '[
    "ai_agent:view",
    "builder.campaign:view",
    "builder.test:view",
    "campaigns:view",
    "dashboard:view",
    "device_control:view",
    "execution.build:view",
    "execution.monitor:view",
    "execution.run:view",
    "interface:view",
    "monitoring.ai_queue:view",
    "monitoring.heatmap:view",
    "monitoring.incidents:view",
    "plugins.grafana:view",
    "plugins.jira:view",
    "plugins.langfuse:view",
    "plugins.postman:view",
    "plugins.slack:view",
    "plugins.testrail:view",
    "reports.campaigns:view",
    "reports.dependency:view",
    "reports.models:view",
    "reports.tests:view",
    "settings.status:view",
    "testcases:view"
]'::jsonb)
ON CONFLICT (role) DO NOTHING;

-- ---------------------------------------------------------------- RLS
ALTER TABLE public.roles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_roles" ON public.roles;
CREATE POLICY "service_role_all_roles" ON public.roles
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.roles FROM anon, authenticated;


ALTER TABLE public.role_permissions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_role_permissions" ON public.role_permissions;
CREATE POLICY "service_role_all_role_permissions" ON public.role_permissions
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.role_permissions FROM anon, authenticated;

COMMIT;
