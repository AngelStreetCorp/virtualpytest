-- ============================================================================
-- 20261006c_report_snapshots_project_ids.sql
-- TASK-65 — Projects (first-class concept). Phase 1 plan artifact.
--
-- Adds:
--   * report_snapshots.project_ids UUID[] NOT NULL DEFAULT '{}'
--
-- A cheap denormalisation: the per-run list (Reports page) and the report HTML
-- badge both want to know "which project(s) does this report belong to". The
-- authoritative source is `executable_tags` -> `projects_tags`, but the Reports
-- list renders the badge without an extra join when this column is set.
--
-- This file is a BLUEPRINT committed on the task65-projects branch. It is NOT
-- applied yet. The data_migrations guard row at the bottom is commented out.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS).
-- ============================================================================

BEGIN;

ALTER TABLE public.report_snapshots
    ADD COLUMN IF NOT EXISTS project_ids UUID[] NOT NULL DEFAULT '{}'::uuid[];

CREATE INDEX IF NOT EXISTS report_snapshots_project_ids_gin
    ON public.report_snapshots USING GIN (project_ids);

COMMENT ON COLUMN public.report_snapshots.project_ids IS
    'TASK-65 — UUIDs of the projects this snapshot belongs to. Derived from '
    'executable_tags -> projects_tags at snapshot time. Used by the Reports '
    'list and the report HTML badge. Phase 1 plan artifact.';

-- ============================================================================
-- data_migrations guard row — commented out so Phase 1 does NOT apply.
-- ============================================================================
-- INSERT INTO public.data_migrations (name) VALUES ('20261006c_report_snapshots_project_ids')
-- ON CONFLICT (name) DO NOTHING;

COMMIT;