-- 20261005a_run_management_rollback.sql
-- Inverse of 20261005a_run_management.sql (TASK-42 Wave 1A, data worker).
--
-- Drops the run-governance / run-quality / manual-run tables and reverts the
-- script_results ALTER. Safe to re-run (DROP IF EXISTS / DROP TRIGGER IF EXISTS).
--
-- ⚠  Run only after redeploying code that does NOT reference these tables —
-- otherwise queries will 404 on missing relations.

BEGIN;

-- Governance RPCs (they reference the tables below).
DROP FUNCTION IF EXISTS public.run_mgmt_assign_script_results(
    UUID, UUID[], TEXT[], BOOLEAN, UUID, BOOLEAN, UUID, BOOLEAN, UUID[], TEXT, TEXT[]);
DROP FUNCTION IF EXISTS public.run_mgmt_replace_labels(UUID, TEXT, UUID, UUID[], TEXT[], TEXT, TEXT[]);

-- script_results: drop the columns and constraints added by the forward migration.
ALTER TABLE public.script_results
    DROP CONSTRAINT IF EXISTS script_results_milestone_fk;
ALTER TABLE public.script_results
    DROP CONSTRAINT IF EXISTS script_results_run_group_fk;
DROP INDEX IF EXISTS public.script_results_team_milestone_idx;
DROP INDEX IF EXISTS public.script_results_team_run_group_idx;
ALTER TABLE public.script_results DROP COLUMN IF EXISTS milestone_id;
ALTER TABLE public.script_results DROP COLUMN IF EXISTS run_group_id;

-- Run services: SQL functions, then tables (children before parents).
DROP FUNCTION IF EXISTS public.rm_finalize_manual_session(uuid, uuid, text, integer);
DROP FUNCTION IF EXISTS public.rm_update_manual_session(uuid, uuid, integer, text, jsonb, text, boolean, boolean);
DROP FUNCTION IF EXISTS public.rm_create_manual_session(uuid, text, text, uuid, integer, text, jsonb, text, text, text, text, jsonb);
DROP FUNCTION IF EXISTS public.rm_fail_defect_jira_push(uuid, uuid, text, boolean);
DROP FUNCTION IF EXISTS public.rm_complete_defect_jira_push(uuid, uuid, text, text);
DROP FUNCTION IF EXISTS public.rm_claim_defect_jira_push(uuid, uuid, text, text, integer);
DROP FUNCTION IF EXISTS public.rm_run_query(uuid, text[], text[], timestamptz, timestamptz, text[], text[], text[], text[], text[], text[], uuid[], uuid[], boolean, boolean, text, boolean, integer, integer, text);
DROP FUNCTION IF EXISTS public.rm_executed_script_names(uuid, text[], text[], timestamptz, timestamptz);
DROP FUNCTION IF EXISTS public.rm_quality_slow(uuid, text[], text[], timestamptz, timestamptz, integer);
DROP FUNCTION IF EXISTS public.rm_quality_flaky(uuid, text[], text[], timestamptz, timestamptz, integer);
DROP FUNCTION IF EXISTS public.rm_eligible_attempts(uuid, text[], text[], timestamptz, timestamptz);
DROP TABLE IF EXISTS public.defect_jira_pushes;

-- manual_session_steps: dropped before manual_sessions (FK parent drop order).
DROP TABLE IF EXISTS public.manual_session_steps;

-- Drop everything else. Order matters when there are FK references, so we drop
-- children before parents.
DROP TABLE IF EXISTS public.manual_sessions;
DROP TABLE IF EXISTS public.custom_reports;
DROP TABLE IF EXISTS public.run_share_snapshots;
DROP TABLE IF EXISTS public.defect_script_results;
DROP TABLE IF EXISTS public.defects;
DROP TABLE IF EXISTS public.run_group_rerun_requests;
DROP TABLE IF EXISTS public.testcase_labels;
DROP TABLE IF EXISTS public.script_result_labels;
DROP TABLE IF EXISTS public.run_label_definitions;
DROP TABLE IF EXISTS public.run_milestones;
DROP TABLE IF EXISTS public.run_groups;

-- Trigger functions (their triggers went with the tables).
DROP FUNCTION IF EXISTS public.run_mgmt_enforce_label_cap();
DROP FUNCTION IF EXISTS public.run_mgmt_touch_updated_at();

-- Parent keys added for the composite FKs. Last: every referencing table is gone.
ALTER TABLE public.testcase_definitions
    DROP CONSTRAINT IF EXISTS testcase_definitions_team_id_testcase_id_key;
ALTER TABLE public.script_results
    DROP CONSTRAINT IF EXISTS script_results_team_id_id_key;

COMMIT;