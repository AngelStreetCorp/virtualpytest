-- ============================================================================
-- 20261015b_projects_tags_is_scope_rollback.sql
-- Rollback for 20261015b. Drops the `is_scope` column from `projects_tags`.
-- ============================================================================

SET search_path = public;

ALTER TABLE public.projects_tags DROP COLUMN IF EXISTS is_scope;

DELETE FROM public.data_migrations WHERE id = '20261015b_projects_tags_is_scope';
