-- ============================================================================
-- 20261015b_projects_tags_is_scope.sql
-- TASK-65 — Projects (first-class concept). Phase 1 plan artifact.
-- G11/BUG-0523: distinguish a project's auto-created *scope* tag from any
-- user-attached tags.
--
-- Today, every project auto-creates exactly one tag in `tags` whose name
-- is the slugified project name, and `projects_tags` links it. A user can
-- ALSO attach extra tags to the same project via `POST /server/projects/<id>/tags`
-- — those user-tags show in the same `projects_tags` rows. The frontend lists
-- them all under one "tags" count on the project card, which inflates the
-- count by 1 on every card (BUG-0523). The doc on `update_project` even says
-- "the slug is hidden in the UI" — the rule exists but the schema offers no
-- way to honour it.
--
-- This file adds `is_scope BOOLEAN NOT NULL DEFAULT FALSE` on `projects_tags`
-- so the auto-created scope tag is mechanically distinct from user tags.
-- The route / db layer reads `is_scope = TRUE` rows as "the scope tag the
-- project auto-creates" and excludes them from `user_tag_count` /
-- `user_tags`. Existing `executable_tags` scope filtering keeps using every
-- `projects_tags` row (scope + user tags both drive device / script filtering,
-- per G9 §14.2 in docs/tasks/TASK-65-projects.md).
--
-- Changes:
--   * ADD COLUMN is_scope BOOLEAN NOT NULL DEFAULT FALSE on `projects_tags`.
--   * Backfill: there are no projects in production (the 20261006a blueprint
--     is not applied yet), but to be safe the route layer tags the row it
--     just inserted in `create_project` instead. DEFAULT FALSE keeps any
--     pre-existing data opaque-but-correct.
--   * Update the table + column comments.
--
-- Safe to re-apply: ADD COLUMN IF NOT EXISTS is idempotent; the comment
-- statements are too.
--
-- This file is a BLUEPRINT committed on the feat/task65-g11-timerange branch.
-- It is NOT applied by this commit. `data_migrations` guards it until the
-- owner manually applies it (mirrors 20261006a). Apply AFTER 20261006a
-- and BEFORE the deployment that brings the G11 endpoints live.
-- ============================================================================

SET search_path = public;

ALTER TABLE public.projects_tags
    ADD COLUMN IF NOT EXISTS is_scope BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN public.projects_tags.is_scope IS
    'TASK-65 G11 / BUG-0523 — TRUE marks the row as the project''s auto-created scope tag. '
    'User-attached tags (via POST /server/projects/<id>/tags) have is_scope = FALSE. '
    'Used by the API only — `executable_tags` scope filtering still uses every project tag.';

-- data_migrations guard row (matches 20261006a pattern).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.data_migrations
        WHERE name = '20261015b_projects_tags_is_scope'
    ) THEN
        INSERT INTO public.data_migrations (name, applied_at)
        VALUES ('20261015b_projects_tags_is_scope', NOW());
    END IF;
END $$;
