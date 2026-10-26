-- 20261016e_drop_workspace_project_tags.sql
-- BUG-0558 — drop the dormant workspace.project_tags field.
-- The field was added in Phase 2 of the workspaces feature but no code ever read or wrote
-- it for filtering. Project scoping works via the project's own scope tag applied to
-- executables (TASK-65 G9 + G10) and devices (device_flags.flags). Operators who set
-- `project_tags` on a workspace saw no effect; the cleaner answer is to drop the column.
-- Idempotent. RLS unchanged (service_role only). Inverse: 20261016e_drop_workspace_project_tags_rollback.sql.
-- Canonical twin: setup/db/schema/067_drop_workspace_project_tags.sql.

BEGIN;

ALTER TABLE public.workspaces DROP COLUMN IF EXISTS project_tags;

COMMENT ON TABLE public.workspaces IS
    'Workspaces are named, switchable contexts with hard filters (device_filter, script_filter, hidden_pages) and soft permission filters (permissions = intersection, denied_permissions = extra denials). The Phase-2 project_tags field was dropped in BUG-0558 because no code read it; project scoping lives on the project''s own scope tag (TASK-65 G9 + G10) and on executable_tags.';

COMMIT;