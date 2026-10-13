-- 20260929b_role_page_view_permissions.sql
-- Page visibility now follows view permissions: the nav hides, and the route guard refuses,
-- any page whose PAGE_PERMISSIONS entry (frontend/src/types/auth.ts) the user lacks.
--
-- Before this, most pages were not gated at all, so testers and viewers could open pages
-- whose view permission their role never held. This adds exactly those view permissions to
-- the role defaults, so nobody loses a page they can open today. An admin can then untick
-- any of them on the Roles page to hide that page from the role.
--
--   viewer + interface, ai_agent, builder.test, builder.campaign,
--            execution.run, execution.monitor, execution.build   (all :view)
--   tester + execution.build, plugins.grafana, plugins.langfuse, plugins.slack (all :view)
--
-- None of these view permissions gates a backend route today, so this widens page
-- visibility only, not API access. The viewer read-only floor is unaffected.
--
-- Requires 20260929a_role_permissions.sql.
-- Idempotent: adds only what a row lacks, never removes anything an admin set.
-- Rollback: none needed — untick on the Roles page.

BEGIN;

UPDATE public.role_permissions r
SET permissions = (
        SELECT jsonb_agg(DISTINCT p ORDER BY p)
        FROM (
            SELECT jsonb_array_elements_text(r.permissions) AS p
            UNION
            SELECT unnest(CASE r.role
                WHEN 'viewer' THEN ARRAY[
                    'interface:view', 'ai_agent:view',
                    'builder.test:view', 'builder.campaign:view',
                    'execution.run:view', 'execution.monitor:view', 'execution.build:view']
                WHEN 'tester' THEN ARRAY[
                    'execution.build:view',
                    'plugins.grafana:view', 'plugins.langfuse:view', 'plugins.slack:view']
            END)
        ) AS merged
    ),
    updated_at = NOW()
WHERE r.role IN ('viewer', 'tester');

COMMIT;
