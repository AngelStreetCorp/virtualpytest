-- ============================================================================
-- 20261015a_executable_tags_virtual_script_campaign.sql
-- TASK-65 — Projects (first-class concept). Phase 1 plan artifact.
-- G10: virtual scripts + campaigns can carry tags at all.
--
-- Today the `executable_tags.executable_type` column accepts only
-- ('script', 'testcase'). The CHECK is fine-grained enough that any insert
-- with `executable_type = 'virtual_script'` or `'campaign'` blows up with a
-- constraint violation. G10 widens it.
--
-- Changes:
--   * Widen `executable_tags.executable_type` VARCHAR(10) → VARCHAR(20) so
--     'virtual_script' (13 chars) fits. 'campaign' is 8 chars and would fit
--     in 10; we widen once instead of per-type to avoid a future migration.
--   * Re-declare the CHECK with the four values:
--       ('script', 'testcase', 'virtual_script', 'campaign')
--     Drop the old constraint first; the auto-generated name is what the
--     CHECK was created with (Postgres names inline CHECKs as
--     `<table>_<column>_check` since 9.x but only when no name is given; the
--     real DB names it `executable_tags_executable_type_check`). Both
--     names are tried to stay safe across renames.
--   * Update the column comment.
--
-- This file is a BLUEPRINT committed on the task65-projects branch. It is
-- NOT applied yet. The data_migrations guard row at the bottom is commented
-- out (same convention the other TASK-65 migrations follow).
--
-- Idempotent: every DROP / ALTER uses IF EXISTS. The rollback file
-- 20261015a_executable_tags_virtual_script_campaign_rollback.sql restores
-- the original shape.
-- ============================================================================

BEGIN;

-- 1. Drop the original CHECK constraint on `executable_tags.executable_type`.
--    Postgres auto-names inline CHECKs as `<table>_<column>_check`; that is
--    the name we expect on a freshly-applied 016_folders_and_tags.sql. The
--    IF EXISTS keeps the file re-runnable if a future migration renamed it.
ALTER TABLE public.executable_tags
    DROP CONSTRAINT IF EXISTS executable_tags_executable_type_check;

-- 2. Widen the column so 'virtual_script' (13 chars) fits. 'campaign' (8)
--    already fits in VARCHAR(10) but we widen once for both.
ALTER TABLE public.executable_tags
    ALTER COLUMN executable_type TYPE VARCHAR(20);

-- 3. Re-declare the CHECK, now covering all four executable kinds.
ALTER TABLE public.executable_tags
    ADD CONSTRAINT executable_tags_executable_type_check
    CHECK (executable_type IN ('script', 'testcase', 'virtual_script', 'campaign'));

-- 4. Refresh the column comment so the schema browser reflects the new kinds.
COMMENT ON COLUMN public.executable_tags.executable_type IS
    'Type: "script", "testcase", "virtual_script", or "campaign". '
    'TASK-65 G10 widened the CHECK (and the column to VARCHAR(20)) so the '
    'same `executable_tags` table tags every kind of artefact the UI and the '
    'Atlas save.';

-- 5. The lookup index `idx_exec_tags_lookup (executable_type, executable_id)`
--    from 016_folders_and_tags.sql is unaffected: VARCHAR(20) is still
--    covered by the btree.

-- ============================================================================
-- data_migrations guard row — commented out so Phase 1 does NOT apply.
-- ============================================================================
-- INSERT INTO public.data_migrations (name) VALUES ('20261015a_executable_tags_virtual_script_campaign')
-- ON CONFLICT (name) DO NOTHING;

COMMIT;