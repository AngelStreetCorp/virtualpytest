-- ============================================================================
-- 20261015a_executable_tags_virtual_script_campaign_rollback.sql
-- TASK-65 — Projects (first-class concept). Phase 1 plan artifact.
-- G10 rollback: reverse 20261015a_executable_tags_virtual_script_campaign.sql.
--
-- Drops any `virtual_script` / `campaign` rows from `executable_tags` first
-- (the original CHECK would reject them on constraint re-add), then restores
-- the VARCHAR(10) column width and the original two-value CHECK. Provided
-- so the data_migrations apply can be reversed if Phase 1 is rejected after
-- merge — the same convention the other TASK-65 migrations follow.
--
-- This file is a BLUEPRINT only. Do NOT apply unless the forward migration
-- has been applied first and is being rolled back as part of a recovery.
-- ============================================================================

BEGIN;

-- 1. Wipe the G10-only rows. Without this, the re-added CHECK on step 3
--    would fail: the constraint re-add is a full-table validation in Postgres
--    and rejects existing rows that violate it.
DELETE FROM public.executable_tags
WHERE executable_type IN ('virtual_script', 'campaign');

-- 2. Drop the widened CHECK.
ALTER TABLE public.executable_tags
    DROP CONSTRAINT IF EXISTS executable_tags_executable_type_check;

-- 3. Restore the original column width. VARCHAR(20) → VARCHAR(10) is a
--    narrowing cast; with step 1's DELETE it's safe (no 'virtual_script' value
--    longer than 10 chars can remain).
ALTER TABLE public.executable_tags
    ALTER COLUMN executable_type TYPE VARCHAR(10);

-- 4. Re-add the original CHECK.
ALTER TABLE public.executable_tags
    ADD CONSTRAINT executable_tags_executable_type_check
    CHECK (executable_type IN ('script', 'testcase'));

-- 5. Restore the original column comment.
COMMENT ON COLUMN public.executable_tags.executable_type IS
    'Type: "script" or "testcase"';

COMMIT;