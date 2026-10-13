-- 062_run_management_permissions.sql
-- Role defaults for the run-management permissions (TASK-42). Canonical fresh-install
-- state; existing databases get it from migration 20261005b_run_management_permissions.sql
-- (same statement — keep the two in step).
--
-- Reads (run summary, groups, milestones, labels, group report) reuse the existing
-- `reports.tests:view` that every role already holds. The writes get four new
-- permissions, granted here to the editable roles that can already run tests:
--
--   reports.runs:edit        groups, milestones, labels, assignments, saved reports
--                            -> manager, developer, tester
--   reports.defects:edit     local defects and their evidence links, Jira push
--                            -> manager, developer, tester
--   reports.manual:execute   record a manual run
--                            -> manager, developer, tester
--   reports.share:create     publish/revoke a sanitized public run snapshot
--                            -> manager, developer (publishing data outside the team)
--
-- Viewers get none (the role_permissions viewer row may only hold :view permissions,
-- and the global viewer floor blocks writes anyway). Admin holds everything and has
-- no row. Team ceilings (teams.permissions) are not widened: a team with an explicit
-- ceiling keeps it until an admin adds the new permissions on the Teams page.
--
-- Idempotent: adds only what a row lacks, never removes anything an admin set.
-- Requires 053_role_catalog.sql.

BEGIN;

UPDATE public.role_permissions r
SET permissions = (
        SELECT jsonb_agg(DISTINCT p ORDER BY p)
        FROM (
            SELECT jsonb_array_elements_text(r.permissions) AS p
            UNION
            SELECT unnest(CASE r.role
                WHEN 'manager' THEN ARRAY[
                    'reports.runs:edit', 'reports.defects:edit',
                    'reports.manual:execute', 'reports.share:create']
                WHEN 'developer' THEN ARRAY[
                    'reports.runs:edit', 'reports.defects:edit',
                    'reports.manual:execute', 'reports.share:create']
                WHEN 'tester' THEN ARRAY[
                    'reports.runs:edit', 'reports.defects:edit',
                    'reports.manual:execute']
            END)
        ) AS merged
    ),
    updated_at = NOW()
WHERE r.role IN ('manager', 'developer', 'tester');

COMMIT;
