-- 067 — drop workspace.project_tags (BUG-0558).
-- Idempotent. Same content as migration 20261016e_drop_workspace_project_tags.sql.
-- Apply BEFORE the deploy that ships the matching code change in BUG-0558.

BEGIN;

ALTER TABLE public.workspaces DROP COLUMN IF EXISTS project_tags;

COMMENT ON TABLE public.workspaces IS
    'Workspaces are named, switchable contexts with hard filters (device_filter, script_filter, hidden_pages) and soft permission filters (permissions = intersection, denied_permissions = extra denials). The Phase-2 project_tags field was dropped in BUG-0558 because no code read it.';

COMMIT;