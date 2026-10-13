-- 20260929a_role_permissions.sql
-- Role default permissions move from code into the database so admins can edit them
-- from the Roles page (Org → Roles).
--
-- Until now the tester/viewer defaults were hard-coded in three places that had drifted
-- apart (auth_middleware.ROLE_DEFAULT_PERMISSIONS, server_permissions_routes._ROLE_PERMISSIONS,
-- frontend types/auth.ts ROLE_PERMISSIONS). This table is now the single source:
-- principal_holds_permission() reads it through a short TTL cache, and the frontend
-- reads it via GET /server/roles.
--
--   * One row per editable role. `admin` is deliberately absent: it holds every
--     permission and never consults this table.
--   * Global, not team-scoped: profiles.role is platform-wide, so one Tester definition
--     covers every tenant (the same shape as `tenants`).
--   * Viewer read-only floor: a viewer row may only hold `*:view` permissions. The server's
--     viewer write block (enforce_viewer_read_only) stays in force regardless; the CHECK
--     keeps the table from ever claiming otherwise.
--
-- Seeded with exactly the values auth_middleware enforced before this migration, so
-- applying it changes no one's access.
--
-- ⚠ Apply BEFORE deploying the code that reads it: without the table, testers and viewers
-- resolve to no role defaults (fail-closed) and lose every page their role granted.
--
-- RLS: service_role only, anon/authenticated revoked (post-TASK-10 posture).
-- Idempotent: safe to re-run; never overwrites edited rows.
-- Inverse: 20260929a_role_permissions_rollback.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.role_permissions (
    role        TEXT PRIMARY KEY,
    permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_by  UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT role_permissions_role_check
        CHECK (role IN ('tester', 'viewer')),
    CONSTRAINT role_permissions_is_array
        CHECK (jsonb_typeof(permissions) = 'array'),
    CONSTRAINT role_permissions_viewer_view_only
        CHECK (role <> 'viewer'
               OR NOT jsonb_path_exists(permissions, '$[*] ? (!(@ like_regex ":view$"))'))
);

COMMENT ON TABLE public.role_permissions IS
    'Default permissions per system role (tester, viewer). Admin holds everything and has no row. '
    'Read by the backend auth middleware (TTL-cached) and GET /server/roles.';

INSERT INTO public.role_permissions (role, permissions) VALUES
('tester', '[
    "dashboard:view",
    "device_control:view", "device_control:execute",
    "testcases:view", "testcases:create", "testcases:edit", "testcases:hide",
    "campaigns:view", "campaigns:create", "campaigns:edit", "campaigns:execute",
    "builder.test:view", "builder.test:use",
    "builder.campaign:view", "builder.campaign:use",
    "execution.run:view", "execution.run:run_test", "execution.run:run_campaign",
    "execution.monitor:view",
    "reports.tests:view", "reports.campaigns:view",
    "reports.models:view", "reports.dependency:view",
    "monitoring.incidents:view", "monitoring.heatmap:view", "monitoring.ai_queue:view",
    "interface:view",
    "ai_agent:view", "ai_agent:use",
    "plugins.postman:view",
    "plugins.jira:view", "plugins.jira:manage", "plugins.testrail:view",
    "settings.status:view"
]'::jsonb),
('viewer', '[
    "dashboard:view",
    "testcases:view", "campaigns:view",
    "reports.tests:view", "reports.campaigns:view",
    "reports.models:view", "reports.dependency:view",
    "monitoring.incidents:view", "monitoring.heatmap:view", "monitoring.ai_queue:view",
    "device_control:view",
    "plugins.postman:view", "plugins.jira:view", "plugins.testrail:view",
    "plugins.slack:view", "plugins.grafana:view", "plugins.langfuse:view",
    "settings.status:view"
]'::jsonb)
ON CONFLICT (role) DO NOTHING;

ALTER TABLE public.role_permissions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_role_permissions" ON public.role_permissions;
CREATE POLICY "service_role_all_role_permissions" ON public.role_permissions
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.role_permissions FROM anon, authenticated;

COMMIT;
