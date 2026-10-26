-- 20261016e_drop_workspace_project_tags_rollback.sql
-- Inverse of 20261016e_drop_workspace_project_tags.sql. Re-adds the column with the
-- previous default. No data is recoverable (the column was empty in production for
-- every workspace that ever set it).

BEGIN;

ALTER TABLE public.workspaces ADD COLUMN IF NOT EXISTS project_tags JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN public.workspaces.project_tags IS
    'Re-added by the BUG-0558 rollback. No code reads it; use the project''s own scope tag (TASK-65 G9 + G10) for project scoping.';

COMMIT;