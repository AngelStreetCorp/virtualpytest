-- TASK-10 env2 parity: close app tables to the public (anon) key on proxmox3
-- Generated 2026-09-08 from live pg_policy / role_table_grants on proxmox3's 192.168.0.102.
-- Mirrors setup/db/migrations/20260908b_close_app_tables_to_public_key.sql (main env),
-- regenerated from THIS instance's own (diverged) policy set -- do not reuse main's file blindly.
-- PREREQUISITE: proxmox3 server (.103) + all hosts (.109/.110/.111/.180/.181/.182) already on
-- SUPABASE_SERVICE_ROLE_KEY -- verified 2026-09-08 via get_db_key_role()==service_role on all 7.
-- Idempotent: DROP POLICY IF EXISTS + REVOKE are safe to re-run.

BEGIN;

-- 1. Drop every policy that is a tautology (literal 'true' or '... OR true' compound),
--    which is functionally always-open regardless of its other clauses. Keeps the real
--    per-user policies on profiles/team_members untouched.
--   agent_benchmark_results
DROP POLICY IF EXISTS "agent_benchmark_results_access_policy" ON public."agent_benchmark_results";
DROP POLICY IF EXISTS "service_role_all_agent_benchmark_results" ON public."agent_benchmark_results";
--   agent_benchmark_runs
DROP POLICY IF EXISTS "agent_benchmark_runs_access_policy" ON public."agent_benchmark_runs";
DROP POLICY IF EXISTS "service_role_all_agent_benchmark_runs" ON public."agent_benchmark_runs";
--   agent_benchmarks
DROP POLICY IF EXISTS "agent_benchmarks_access_policy" ON public."agent_benchmarks";
DROP POLICY IF EXISTS "service_role_all_agent_benchmarks" ON public."agent_benchmarks";
--   agent_event_triggers
DROP POLICY IF EXISTS "agent_event_triggers_access_policy" ON public."agent_event_triggers";
DROP POLICY IF EXISTS "service_role_all_agent_event_triggers" ON public."agent_event_triggers";
--   agent_execution_history
DROP POLICY IF EXISTS "agent_execution_history_access_policy" ON public."agent_execution_history";
DROP POLICY IF EXISTS "service_role_all_agent_execution_history" ON public."agent_execution_history";
--   agent_feedback
DROP POLICY IF EXISTS "agent_feedback_access_policy" ON public."agent_feedback";
DROP POLICY IF EXISTS "service_role_all_agent_feedback" ON public."agent_feedback";
--   agent_instances
DROP POLICY IF EXISTS "agent_instances_access_policy" ON public."agent_instances";
DROP POLICY IF EXISTS "service_role_all_agent_instances" ON public."agent_instances";
--   agent_registry
DROP POLICY IF EXISTS "agent_registry_access_policy" ON public."agent_registry";
DROP POLICY IF EXISTS "service_role_all_agent_registry" ON public."agent_registry";
--   agent_scores
DROP POLICY IF EXISTS "agent_scores_access_policy" ON public."agent_scores";
DROP POLICY IF EXISTS "service_role_all_agent_scores" ON public."agent_scores";
--   ai_analysis_cache
DROP POLICY IF EXISTS "ai_analysis_cache_access_policy" ON public."ai_analysis_cache";
--   ai_graph_cache
DROP POLICY IF EXISTS "ai_graph_cache_access_policy" ON public."ai_graph_cache";
--   ai_prompt_disambiguation
DROP POLICY IF EXISTS "ai_prompt_disambiguation_access_policy" ON public."ai_prompt_disambiguation";
--   alerts
DROP POLICY IF EXISTS "alerts_access_policy" ON public."alerts";
--   campaign_executions
DROP POLICY IF EXISTS "campaign_executions_access_policy" ON public."campaign_executions";
--   campaigns
DROP POLICY IF EXISTS "campaigns_access_policy" ON public."campaigns";
DROP POLICY IF EXISTS "service_role_all_campaigns" ON public."campaigns";
--   campaigns_history
DROP POLICY IF EXISTS "campaigns_history_access_policy" ON public."campaigns_history";
DROP POLICY IF EXISTS "service_role_all_campaigns_history" ON public."campaigns_history";
--   deployment_executions
DROP POLICY IF EXISTS "deployment_executions_access_policy" ON public."deployment_executions";
--   deployments
DROP POLICY IF EXISTS "deployments_access_policy" ON public."deployments";
--   device
DROP POLICY IF EXISTS "device_access_policy" ON public."device";
--   device_flags
DROP POLICY IF EXISTS "device_flags_access_policy" ON public."device_flags";
--   device_models
DROP POLICY IF EXISTS "device_models_access_policy" ON public."device_models";
--   edge_metrics
DROP POLICY IF EXISTS "edge_metrics_access_policy" ON public."edge_metrics";
--   environment_profiles
DROP POLICY IF EXISTS "environment_profiles_access_policy" ON public."environment_profiles";
--   event_log
DROP POLICY IF EXISTS "event_log_access_policy" ON public."event_log";
DROP POLICY IF EXISTS "service_role_all_event_log" ON public."event_log";
--   executable_tags
DROP POLICY IF EXISTS "executable_tags_access_policy" ON public."executable_tags";
DROP POLICY IF EXISTS "service_role_all_executable_tags" ON public."executable_tags";
--   execution_results
DROP POLICY IF EXISTS "execution_results_access_policy" ON public."execution_results";
--   folders
DROP POLICY IF EXISTS "folders_access_policy" ON public."folders";
DROP POLICY IF EXISTS "service_role_all_folders" ON public."folders";
--   heatmaps
DROP POLICY IF EXISTS "heatmaps_access_policy" ON public."heatmaps";
--   library_visibility
DROP POLICY IF EXISTS "library_visibility_access_policy" ON public."library_visibility";
DROP POLICY IF EXISTS "service_role_all_library_visibility" ON public."library_visibility";
--   navigation_edges
DROP POLICY IF EXISTS "navigation_edges_access_policy" ON public."navigation_edges";
--   navigation_nodes
DROP POLICY IF EXISTS "navigation_nodes_access_policy" ON public."navigation_nodes";
--   navigation_trees
DROP POLICY IF EXISTS "navigation_trees_access_policy" ON public."navigation_trees";
--   navigation_trees_history
DROP POLICY IF EXISTS "navigation_trees_history_access_policy" ON public."navigation_trees_history";
--   node_metrics
DROP POLICY IF EXISTS "node_metrics_access_policy" ON public."node_metrics";
--   requirements
DROP POLICY IF EXISTS "requirements_access_policy" ON public."requirements";
DROP POLICY IF EXISTS "service_role_all_requirements" ON public."requirements";
--   resource_lock_queue
DROP POLICY IF EXISTS "resource_lock_queue_access_policy" ON public."resource_lock_queue";
DROP POLICY IF EXISTS "service_role_all_resource_lock_queue" ON public."resource_lock_queue";
--   resource_locks
DROP POLICY IF EXISTS "resource_locks_access_policy" ON public."resource_locks";
DROP POLICY IF EXISTS "service_role_all_resource_locks" ON public."resource_locks";
--   scheduled_events
DROP POLICY IF EXISTS "scheduled_events_access_policy" ON public."scheduled_events";
DROP POLICY IF EXISTS "service_role_all_scheduled_events" ON public."scheduled_events";
--   script_requirements
DROP POLICY IF EXISTS "script_requirements_access_policy" ON public."script_requirements";
DROP POLICY IF EXISTS "service_role_all_script_requirements" ON public."script_requirements";
--   script_results
DROP POLICY IF EXISTS "script_results_access_policy" ON public."script_results";
--   scripts
DROP POLICY IF EXISTS "scripts_access_policy" ON public."scripts";
DROP POLICY IF EXISTS "service_role_all_scripts" ON public."scripts";
--   system_device_metrics
DROP POLICY IF EXISTS "system_device_metrics_access_policy" ON public."system_device_metrics";
--   system_incident
DROP POLICY IF EXISTS "system_incident_access_policy" ON public."system_incident";
--   system_metrics
DROP POLICY IF EXISTS "system_metrics_access_policy" ON public."system_metrics";
--   tags
DROP POLICY IF EXISTS "service_role_all_tags" ON public."tags";
DROP POLICY IF EXISTS "tags_access_policy" ON public."tags";
--   teams
DROP POLICY IF EXISTS "teams_access_policy" ON public."teams";
--   test_cases
DROP POLICY IF EXISTS "test_cases_access_policy" ON public."test_cases";
--   test_executions
DROP POLICY IF EXISTS "test_executions_access_policy" ON public."test_executions";
--   test_results
DROP POLICY IF EXISTS "test_results_access_policy" ON public."test_results";
--   testcase_definitions
DROP POLICY IF EXISTS "service_role_all_testcase_definitions" ON public."testcase_definitions";
DROP POLICY IF EXISTS "testcase_definitions_access_policy" ON public."testcase_definitions";
--   testcase_definitions_history
DROP POLICY IF EXISTS "service_role_all_testcase_history" ON public."testcase_definitions_history";
DROP POLICY IF EXISTS "testcase_history_access_policy" ON public."testcase_definitions_history";
--   testcase_requirements
DROP POLICY IF EXISTS "service_role_all_testcase_requirements" ON public."testcase_requirements";
DROP POLICY IF EXISTS "testcase_requirements_access_policy" ON public."testcase_requirements";
--   userinterfaces
DROP POLICY IF EXISTS "userinterfaces_open_access" ON public."userinterfaces";
--   verifications_references
DROP POLICY IF EXISTS "verifications_references_access_policy" ON public."verifications_references";
--   workspace_members
DROP POLICY IF EXISTS "workspace_members_access_policy" ON public."workspace_members";
--   workspaces
DROP POLICY IF EXISTS "workspaces_access_policy" ON public."workspaces";
--   zap_results
DROP POLICY IF EXISTS "zap_results_access_policy" ON public."zap_results";

-- 2. Revoke table privileges. anon loses everything; authenticated keeps only
--    profiles + team_members (the browser's sole direct reads, scoped by real policy).
REVOKE ALL ON public."active_incidents_summary" FROM anon;
REVOKE ALL ON public."agent_benchmark_results" FROM anon;
REVOKE ALL ON public."agent_benchmark_runs" FROM anon;
REVOKE ALL ON public."agent_benchmarks" FROM anon;
REVOKE ALL ON public."agent_event_triggers" FROM anon;
REVOKE ALL ON public."agent_execution_history" FROM anon;
REVOKE ALL ON public."agent_feedback" FROM anon;
REVOKE ALL ON public."agent_instances" FROM anon;
REVOKE ALL ON public."agent_leaderboard" FROM anon;
REVOKE ALL ON public."agent_metrics" FROM anon;
REVOKE ALL ON public."agent_registry" FROM anon;
REVOKE ALL ON public."agent_scores" FROM anon;
REVOKE ALL ON public."ai_analysis_cache" FROM anon;
REVOKE ALL ON public."ai_graph_cache" FROM anon;
REVOKE ALL ON public."ai_prompt_disambiguation" FROM anon;
REVOKE ALL ON public."alerts" FROM anon;
REVOKE ALL ON public."campaign_executions" FROM anon;
REVOKE ALL ON public."campaigns" FROM anon;
REVOKE ALL ON public."campaigns_history" FROM anon;
REVOKE ALL ON public."deployment_executions" FROM anon;
REVOKE ALL ON public."deployments" FROM anon;
REVOKE ALL ON public."device" FROM anon;
REVOKE ALL ON public."device_availability_summary" FROM anon;
REVOKE ALL ON public."device_flags" FROM anon;
REVOKE ALL ON public."device_models" FROM anon;
REVOKE ALL ON public."edge_metrics" FROM anon;
REVOKE ALL ON public."environment_profiles" FROM anon;
REVOKE ALL ON public."event_log" FROM anon;
REVOKE ALL ON public."executable_tags" FROM anon;
REVOKE ALL ON public."execution_results" FROM anon;
REVOKE ALL ON public."folders" FROM anon;
REVOKE ALL ON public."heatmaps" FROM anon;
REVOKE ALL ON public."library_visibility" FROM anon;
REVOKE ALL ON public."navigation_edges" FROM anon;
REVOKE ALL ON public."navigation_nodes" FROM anon;
REVOKE ALL ON public."navigation_trees" FROM anon;
REVOKE ALL ON public."navigation_trees_history" FROM anon;
REVOKE ALL ON public."node_metrics" FROM anon;
REVOKE ALL ON public."profiles" FROM anon;
REVOKE ALL ON public."requirements" FROM anon;
REVOKE ALL ON public."requirements_coverage_summary" FROM anon;
REVOKE ALL ON public."resource_lock_queue" FROM anon;
REVOKE ALL ON public."resource_locks" FROM anon;
REVOKE ALL ON public."scheduled_events" FROM anon;
REVOKE ALL ON public."script_requirements" FROM anon;
REVOKE ALL ON public."script_results" FROM anon;
REVOKE ALL ON public."scripts" FROM anon;
REVOKE ALL ON public."system_device_metrics" FROM anon;
REVOKE ALL ON public."system_incident" FROM anon;
REVOKE ALL ON public."system_metrics" FROM anon;
REVOKE ALL ON public."tags" FROM anon;
REVOKE ALL ON public."team_members" FROM anon;
REVOKE ALL ON public."teams" FROM anon;
REVOKE ALL ON public."test_cases" FROM anon;
REVOKE ALL ON public."test_executions" FROM anon;
REVOKE ALL ON public."test_results" FROM anon;
REVOKE ALL ON public."testcase_definitions" FROM anon;
REVOKE ALL ON public."testcase_definitions_history" FROM anon;
REVOKE ALL ON public."testcase_requirements" FROM anon;
REVOKE ALL ON public."uncovered_requirements" FROM anon;
REVOKE ALL ON public."userinterfaces" FROM anon;
REVOKE ALL ON public."verifications_references" FROM anon;
REVOKE ALL ON public."workspace_members" FROM anon;
REVOKE ALL ON public."workspaces" FROM anon;
REVOKE ALL ON public."zap_results" FROM anon;

REVOKE ALL ON public."active_incidents_summary" FROM authenticated;
REVOKE ALL ON public."agent_benchmark_results" FROM authenticated;
REVOKE ALL ON public."agent_benchmark_runs" FROM authenticated;
REVOKE ALL ON public."agent_benchmarks" FROM authenticated;
REVOKE ALL ON public."agent_event_triggers" FROM authenticated;
REVOKE ALL ON public."agent_execution_history" FROM authenticated;
REVOKE ALL ON public."agent_feedback" FROM authenticated;
REVOKE ALL ON public."agent_instances" FROM authenticated;
REVOKE ALL ON public."agent_leaderboard" FROM authenticated;
REVOKE ALL ON public."agent_metrics" FROM authenticated;
REVOKE ALL ON public."agent_registry" FROM authenticated;
REVOKE ALL ON public."agent_scores" FROM authenticated;
REVOKE ALL ON public."ai_analysis_cache" FROM authenticated;
REVOKE ALL ON public."ai_graph_cache" FROM authenticated;
REVOKE ALL ON public."ai_prompt_disambiguation" FROM authenticated;
REVOKE ALL ON public."alerts" FROM authenticated;
REVOKE ALL ON public."campaign_executions" FROM authenticated;
REVOKE ALL ON public."campaigns" FROM authenticated;
REVOKE ALL ON public."campaigns_history" FROM authenticated;
REVOKE ALL ON public."deployment_executions" FROM authenticated;
REVOKE ALL ON public."deployments" FROM authenticated;
REVOKE ALL ON public."device" FROM authenticated;
REVOKE ALL ON public."device_availability_summary" FROM authenticated;
REVOKE ALL ON public."device_flags" FROM authenticated;
REVOKE ALL ON public."device_models" FROM authenticated;
REVOKE ALL ON public."edge_metrics" FROM authenticated;
REVOKE ALL ON public."environment_profiles" FROM authenticated;
REVOKE ALL ON public."event_log" FROM authenticated;
REVOKE ALL ON public."executable_tags" FROM authenticated;
REVOKE ALL ON public."execution_results" FROM authenticated;
REVOKE ALL ON public."folders" FROM authenticated;
REVOKE ALL ON public."heatmaps" FROM authenticated;
REVOKE ALL ON public."library_visibility" FROM authenticated;
REVOKE ALL ON public."navigation_edges" FROM authenticated;
REVOKE ALL ON public."navigation_nodes" FROM authenticated;
REVOKE ALL ON public."navigation_trees" FROM authenticated;
REVOKE ALL ON public."navigation_trees_history" FROM authenticated;
REVOKE ALL ON public."node_metrics" FROM authenticated;
REVOKE ALL ON public."requirements" FROM authenticated;
REVOKE ALL ON public."requirements_coverage_summary" FROM authenticated;
REVOKE ALL ON public."resource_lock_queue" FROM authenticated;
REVOKE ALL ON public."resource_locks" FROM authenticated;
REVOKE ALL ON public."scheduled_events" FROM authenticated;
REVOKE ALL ON public."script_requirements" FROM authenticated;
REVOKE ALL ON public."script_results" FROM authenticated;
REVOKE ALL ON public."scripts" FROM authenticated;
REVOKE ALL ON public."system_device_metrics" FROM authenticated;
REVOKE ALL ON public."system_incident" FROM authenticated;
REVOKE ALL ON public."system_metrics" FROM authenticated;
REVOKE ALL ON public."tags" FROM authenticated;
REVOKE ALL ON public."teams" FROM authenticated;
REVOKE ALL ON public."test_cases" FROM authenticated;
REVOKE ALL ON public."test_executions" FROM authenticated;
REVOKE ALL ON public."test_results" FROM authenticated;
REVOKE ALL ON public."testcase_definitions" FROM authenticated;
REVOKE ALL ON public."testcase_definitions_history" FROM authenticated;
REVOKE ALL ON public."testcase_requirements" FROM authenticated;
REVOKE ALL ON public."uncovered_requirements" FROM authenticated;
REVOKE ALL ON public."userinterfaces" FROM authenticated;
REVOKE ALL ON public."verifications_references" FROM authenticated;
REVOKE ALL ON public."workspace_members" FROM authenticated;
REVOKE ALL ON public."workspaces" FROM authenticated;
REVOKE ALL ON public."zap_results" FROM authenticated;

-- 3. Materialized view(s): backend reads via service_role; close to app roles.
REVOKE SELECT ON public."mv_full_navigation_trees" FROM anon, authenticated;

-- 4. Close future tables/sequences so a new app table is not silently reopened.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;

COMMIT;
