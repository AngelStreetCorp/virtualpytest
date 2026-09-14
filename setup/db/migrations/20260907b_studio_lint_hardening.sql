-- Supabase Studio advisor hardening (security + performance lints)
-- ------------------------------------------------------------------
-- Clears the actionable findings of Studio's advisor (splinter lints) on the
-- production DB, without changing the platform's access model (RLS on, open
-- policy, authorization in the server layer — see SERVER_AUTH.md). BUG-0053.
--
--   A. security_definer_view (ERROR x5)  → views run as the caller (security_invoker)
--   B. *_security_definer_function_executable (WARN)  → revoke EXECUTE from anon /
--      authenticated on SECURITY DEFINER functions nobody calls over the API:
--      13 trigger functions (triggers keep firing — verified: fire-time does not
--      check EXECUTE) + 3 RPCs with no caller in the codebase.
--      Kept callable (backend uses them with the anon key): delete_all_alerts,
--      get_all_profiles, get_team_member_count, get_team_members_with_profiles,
--      get_user_team_memberships, get_user_workspaces, get_tree_metrics_optimized,
--      get_full_tree_from_mv, is_admin (used inside RLS policies).
--   C. function_search_path_mutable (WARN x50)  → pin search_path to what the
--      session default already resolves to (public, auth, extensions): zero
--      behaviour change, but no longer hijackable.
--   D. auth_rls_initplan (WARN x60)  → the open policies were written as
--      `(auth.uid() IS NULL) OR (auth.role()=...) OR true`, which calls auth.*
--      per row for a result that is always true. Rewritten as `USING (true)`
--      (same semantics, same roles, same commands; generated from pg_policy).
--      NOTE: this moves them from the performance tab to the security tab's
--      "RLS Policy Always True" — that one is the documented platform model.
--   E. multiple_permissive_policies (WARN x18)  → profiles: the "own profile"
--      SELECT policy was already subsumed by the admin one; the two UPDATE
--      policies are merged into one. team_members: one SELECT policy and
--      per-command manage policies instead of SELECT + ALL overlapping — and
--      the self-referencing sub-selects that made EVERY read of team_members
--      fail with 'infinite recursion' (BUG-0054) are replaced by SECURITY
--      DEFINER helpers is_team_member()/is_team_owner().
--      auth.uid() wrapped in (select ...) so it is evaluated once per query.
--   F. unindexed_foreign_keys (INFO)  → only the two FKs on tables with real
--      row counts / join paths; the rest are on (near-)empty tables.
--
-- Not fixed on purpose: pg_graphql exposure (196 WARN — the extension is wired
-- into DDL event triggers; disable it as a separate decision), materialized
-- view in API (backend reads mv_full_navigation_trees directly), unused
-- indexes (224 INFO, 84 MB — needs a usage review, not a blind drop).
-- Idempotent — safe to re-run.

BEGIN;

-- ---------------------------------------------------------------- A. views
ALTER VIEW public.device_info_corrected    SET (security_invoker = on);
ALTER VIEW public.device_info_key_status   SET (security_invoker = on);
ALTER VIEW public.gateway_info_corrected   SET (security_invoker = on);
ALTER VIEW public.gateway_info_key_status  SET (security_invoker = on);
ALTER VIEW public.edge_navigation_metrics  SET (security_invoker = on);

-- ------------------------------------------- B. SECURITY DEFINER functions
-- trigger functions: never called directly, only fired by triggers
REVOKE EXECUTE ON FUNCTION public.auto_set_edge_label_on_insert()            FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.auto_update_edge_labels_on_node_change()   FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.create_default_navigation_tree()           FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.handle_new_user()                          FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.prevent_protected_edge_deletion()          FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.prevent_protected_node_deletion()          FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.prevent_readonly_node_update()             FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.refresh_tree_materialized_view()           FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.sync_profile_role_to_auth()                FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.trigger_update_agent_score_on_benchmark()  FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.trigger_update_agent_score_on_execution()  FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.trigger_update_agent_score_on_feedback()   FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.update_node_subtree_counts()               FROM PUBLIC, anon, authenticated;
-- RPCs with no caller in backend_server / backend_host / shared / frontend / features
REVOKE EXECUTE ON FUNCTION public.get_full_navigation_tree(uuid, uuid)       FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.get_tree_metrics_from_mv(uuid, uuid)       FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.get_user_effective_permissions(uuid)       FROM PUBLIC, anon, authenticated;

-- ------------------------------------------------ C. function search_path
ALTER FUNCTION public.backfill_agent_scores() SET search_path = public, auth, extensions;
ALTER FUNCTION public.cleanup_ai_graph_cache(uuid, integer, numeric) SET search_path = public, auth, extensions;
ALTER FUNCTION public.cleanup_expired_locks() SET search_path = public, auth, extensions;
ALTER FUNCTION public.cleanup_old_disambiguations(integer, integer) SET search_path = public, auth, extensions;
ALTER FUNCTION public.cleanup_old_resolved_alerts() SET search_path = public, auth, extensions;
ALTER FUNCTION public.create_default_device_models(uuid) SET search_path = public, auth, extensions;
ALTER FUNCTION public.delete_all_alerts() SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_agents_for_event(character varying, character varying) SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_descendant_trees(uuid) SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_devices_by_flag(text, text) SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_disambiguation(uuid, character varying, text) SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_enabled_agents(character varying) SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_full_navigation_tree(uuid, uuid) SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_latest_agent_version(character varying) SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_resource_lock_status(character varying) SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_tree_metrics_from_mv(uuid, uuid) SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_tree_path(uuid) SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_user_effective_permissions(uuid) SET search_path = public, auth, extensions;
ALTER FUNCTION public.get_user_workspaces(uuid) SET search_path = public, auth, extensions;
ALTER FUNCTION public.handle_new_user() SET search_path = public, auth, extensions;
ALTER FUNCTION public.handle_team_members_updated_at() SET search_path = public, auth, extensions;
ALTER FUNCTION public.handle_updated_at() SET search_path = public, auth, extensions;
ALTER FUNCTION public.prevent_protected_edge_deletion() SET search_path = public, auth, extensions;
ALTER FUNCTION public.prevent_protected_node_deletion() SET search_path = public, auth, extensions;
ALTER FUNCTION public.prevent_readonly_node_update() SET search_path = public, auth, extensions;
ALTER FUNCTION public.preview_cleanup_old_alerts() SET search_path = public, auth, extensions;
ALTER FUNCTION public.recalculate_agent_score(character varying, character varying, character varying) SET search_path = public, auth, extensions;
ALTER FUNCTION public.record_disambiguation(uuid, character varying, text, character varying) SET search_path = public, auth, extensions;
ALTER FUNCTION public.save_testcase_version_history() SET search_path = public, auth, extensions;
ALTER FUNCTION public.save_virtual_script_version_history() SET search_path = public, auth, extensions;
ALTER FUNCTION public.set_agent_enabled(character varying, boolean, character varying) SET search_path = public, auth, extensions;
ALTER FUNCTION public.trigger_create_default_device_models() SET search_path = public, auth, extensions;
ALTER FUNCTION public.trigger_update_agent_score_on_benchmark() SET search_path = public, auth, extensions;
ALTER FUNCTION public.trigger_update_agent_score_on_execution() SET search_path = public, auth, extensions;
ALTER FUNCTION public.trigger_update_agent_score_on_feedback() SET search_path = public, auth, extensions;
ALTER FUNCTION public.update_agent_registry_updated_at() SET search_path = public, auth, extensions;
ALTER FUNCTION public.update_ai_graph_metrics(character varying, boolean, integer, uuid) SET search_path = public, auth, extensions;
ALTER FUNCTION public.update_campaign_updated_at() SET search_path = public, auth, extensions;
ALTER FUNCTION public.update_device_flags(text, text, text[]) SET search_path = public, auth, extensions;
ALTER FUNCTION public.update_requirements_updated_at() SET search_path = public, auth, extensions;
ALTER FUNCTION public.update_system_incident_updated_at() SET search_path = public, auth, extensions;
ALTER FUNCTION public.update_testcase_updated_at() SET search_path = public, auth, extensions;
ALTER FUNCTION public.update_virtual_scripts_updated_at() SET search_path = public, auth, extensions;
ALTER FUNCTION public.upsert_device_flags(text, text, text) SET search_path = public, auth, extensions;
ALTER FUNCTION retention.cleanup_adhoc_deployment_receipts() SET search_path = retention, public, extensions;
ALTER FUNCTION retention.cleanup_alerts() SET search_path = retention, public, extensions;
ALTER FUNCTION retention.cleanup_all() SET search_path = retention, public, extensions;
ALTER FUNCTION retention.cleanup_quality_metrics() SET search_path = retention, public, extensions;
ALTER FUNCTION retention.cleanup_system_device_metrics() SET search_path = retention, public, extensions;
ALTER FUNCTION retention.cleanup_system_metrics() SET search_path = retention, public, extensions;

-- ------------------------------- D. open policies: drop the per-row auth.* calls
-- (generated from pg_policy on 2026-09-07; every qual ended in `OR true`)
DROP POLICY IF EXISTS agent_benchmark_results_access_policy ON public.agent_benchmark_results;
CREATE POLICY agent_benchmark_results_access_policy ON public.agent_benchmark_results FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS agent_benchmark_runs_access_policy ON public.agent_benchmark_runs;
CREATE POLICY agent_benchmark_runs_access_policy ON public.agent_benchmark_runs FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS agent_benchmarks_access_policy ON public.agent_benchmarks;
CREATE POLICY agent_benchmarks_access_policy ON public.agent_benchmarks FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS agent_event_triggers_access_policy ON public.agent_event_triggers;
CREATE POLICY agent_event_triggers_access_policy ON public.agent_event_triggers FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS agent_execution_history_access_policy ON public.agent_execution_history;
CREATE POLICY agent_execution_history_access_policy ON public.agent_execution_history FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS agent_feedback_access_policy ON public.agent_feedback;
CREATE POLICY agent_feedback_access_policy ON public.agent_feedback FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS agent_instances_access_policy ON public.agent_instances;
CREATE POLICY agent_instances_access_policy ON public.agent_instances FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS agent_registry_access_policy ON public.agent_registry;
CREATE POLICY agent_registry_access_policy ON public.agent_registry FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS agent_scores_access_policy ON public.agent_scores;
CREATE POLICY agent_scores_access_policy ON public.agent_scores FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS ai_analysis_cache_access_policy ON public.ai_analysis_cache;
CREATE POLICY ai_analysis_cache_access_policy ON public.ai_analysis_cache FOR ALL TO public USING (true);
DROP POLICY IF EXISTS ai_graph_cache_access_policy ON public.ai_graph_cache;
CREATE POLICY ai_graph_cache_access_policy ON public.ai_graph_cache FOR ALL TO public USING (true);
DROP POLICY IF EXISTS ai_userinterface_fingerprints_access_policy ON public.ai_userinterface_fingerprints;
CREATE POLICY ai_userinterface_fingerprints_access_policy ON public.ai_userinterface_fingerprints FOR ALL TO public USING (true);
DROP POLICY IF EXISTS ai_userinterface_known_hardware_access_policy ON public.ai_userinterface_known_hardware;
CREATE POLICY ai_userinterface_known_hardware_access_policy ON public.ai_userinterface_known_hardware FOR ALL TO public USING (true);
DROP POLICY IF EXISTS ai_userinterface_quirks_access_policy ON public.ai_userinterface_quirks;
CREATE POLICY ai_userinterface_quirks_access_policy ON public.ai_userinterface_quirks FOR ALL TO public USING (true);
DROP POLICY IF EXISTS ai_userinterface_screens_access_policy ON public.ai_userinterface_screens;
CREATE POLICY ai_userinterface_screens_access_policy ON public.ai_userinterface_screens FOR ALL TO public USING (true);
DROP POLICY IF EXISTS ai_userinterfaces_access_policy ON public.ai_userinterfaces;
CREATE POLICY ai_userinterfaces_access_policy ON public.ai_userinterfaces FOR ALL TO public USING (true);
DROP POLICY IF EXISTS ai_userinterfaces_history_access_policy ON public.ai_userinterfaces_history;
CREATE POLICY ai_userinterfaces_history_access_policy ON public.ai_userinterfaces_history FOR ALL TO public USING (true);
DROP POLICY IF EXISTS campaign_executions_access_policy ON public.campaign_executions;
CREATE POLICY campaign_executions_access_policy ON public.campaign_executions FOR ALL TO public USING (true);
DROP POLICY IF EXISTS campaigns_access_policy ON public.campaigns;
CREATE POLICY campaigns_access_policy ON public.campaigns FOR ALL TO public USING (true);
DROP POLICY IF EXISTS campaigns_history_access_policy ON public.campaigns_history;
CREATE POLICY campaigns_history_access_policy ON public.campaigns_history FOR ALL TO public USING (true);
DROP POLICY IF EXISTS deployment_executions_access_policy ON public.deployment_executions;
CREATE POLICY deployment_executions_access_policy ON public.deployment_executions FOR ALL TO public USING (true);
DROP POLICY IF EXISTS deployments_access_policy ON public.deployments;
CREATE POLICY deployments_access_policy ON public.deployments FOR ALL TO public USING (true);
DROP POLICY IF EXISTS device_access_policy ON public.device;
CREATE POLICY device_access_policy ON public.device FOR ALL TO public USING (true);
DROP POLICY IF EXISTS device_flags_access_policy ON public.device_flags;
CREATE POLICY device_flags_access_policy ON public.device_flags FOR ALL TO public USING (true);
DROP POLICY IF EXISTS device_info_overrides_access_policy ON public.device_info_overrides;
CREATE POLICY device_info_overrides_access_policy ON public.device_info_overrides FOR ALL TO public USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS device_models_access_policy ON public.device_models;
CREATE POLICY device_models_access_policy ON public.device_models FOR ALL TO public USING (true);
DROP POLICY IF EXISTS edge_metrics_access_policy ON public.edge_metrics;
CREATE POLICY edge_metrics_access_policy ON public.edge_metrics FOR ALL TO public USING (true);
DROP POLICY IF EXISTS environment_profiles_access_policy ON public.environment_profiles;
CREATE POLICY environment_profiles_access_policy ON public.environment_profiles FOR ALL TO public USING (true);
DROP POLICY IF EXISTS event_log_access_policy ON public.event_log;
CREATE POLICY event_log_access_policy ON public.event_log FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS execution_results_access_policy ON public.execution_results;
CREATE POLICY execution_results_access_policy ON public.execution_results FOR ALL TO public USING (true);
DROP POLICY IF EXISTS heatmaps_access_policy ON public.heatmaps;
CREATE POLICY heatmaps_access_policy ON public.heatmaps FOR ALL TO public USING (true);
DROP POLICY IF EXISTS library_visibility_access_policy ON public.library_visibility;
CREATE POLICY library_visibility_access_policy ON public.library_visibility FOR ALL TO public USING (true);
DROP POLICY IF EXISTS navigation_edges_access_policy ON public.navigation_edges;
CREATE POLICY navigation_edges_access_policy ON public.navigation_edges FOR ALL TO public USING (true);
DROP POLICY IF EXISTS navigation_nodes_access_policy ON public.navigation_nodes;
CREATE POLICY navigation_nodes_access_policy ON public.navigation_nodes FOR ALL TO public USING (true);
DROP POLICY IF EXISTS navigation_trees_access_policy ON public.navigation_trees;
CREATE POLICY navigation_trees_access_policy ON public.navigation_trees FOR ALL TO public USING (true);
DROP POLICY IF EXISTS navigation_trees_history_access_policy ON public.navigation_trees_history;
CREATE POLICY navigation_trees_history_access_policy ON public.navigation_trees_history FOR ALL TO public USING (true);
DROP POLICY IF EXISTS node_metrics_access_policy ON public.node_metrics;
CREATE POLICY node_metrics_access_policy ON public.node_metrics FOR ALL TO public USING (true);
DROP POLICY IF EXISTS requirements_access_policy ON public.requirements;
CREATE POLICY requirements_access_policy ON public.requirements FOR ALL TO public USING (true);
DROP POLICY IF EXISTS resource_lock_queue_access_policy ON public.resource_lock_queue;
CREATE POLICY resource_lock_queue_access_policy ON public.resource_lock_queue FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS resource_locks_access_policy ON public.resource_locks;
CREATE POLICY resource_locks_access_policy ON public.resource_locks FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS scheduled_events_access_policy ON public.scheduled_events;
CREATE POLICY scheduled_events_access_policy ON public.scheduled_events FOR ALL TO authenticated USING (true);
DROP POLICY IF EXISTS script_requirements_access_policy ON public.script_requirements;
CREATE POLICY script_requirements_access_policy ON public.script_requirements FOR ALL TO public USING (true);
DROP POLICY IF EXISTS script_results_access_policy ON public.script_results;
CREATE POLICY script_results_access_policy ON public.script_results FOR ALL TO public USING (true);
DROP POLICY IF EXISTS test_cases_access_policy ON public.test_cases;
CREATE POLICY test_cases_access_policy ON public.test_cases FOR ALL TO public USING (true);
DROP POLICY IF EXISTS test_executions_access_policy ON public.test_executions;
CREATE POLICY test_executions_access_policy ON public.test_executions FOR ALL TO public USING (true);
DROP POLICY IF EXISTS test_results_access_policy ON public.test_results;
CREATE POLICY test_results_access_policy ON public.test_results FOR ALL TO public USING (true);
DROP POLICY IF EXISTS testcase_definitions_access_policy ON public.testcase_definitions;
CREATE POLICY testcase_definitions_access_policy ON public.testcase_definitions FOR ALL TO public USING (true);
DROP POLICY IF EXISTS testcase_history_access_policy ON public.testcase_definitions_history;
CREATE POLICY testcase_history_access_policy ON public.testcase_definitions_history FOR ALL TO public USING (true);
DROP POLICY IF EXISTS testcase_requirements_access_policy ON public.testcase_requirements;
CREATE POLICY testcase_requirements_access_policy ON public.testcase_requirements FOR ALL TO public USING (true);
DROP POLICY IF EXISTS verifications_reference_versions_access_policy ON public.verifications_reference_versions;
CREATE POLICY verifications_reference_versions_access_policy ON public.verifications_reference_versions FOR ALL TO public USING (true);
DROP POLICY IF EXISTS verifications_references_access_policy ON public.verifications_references;
CREATE POLICY verifications_references_access_policy ON public.verifications_references FOR ALL TO public USING (true);
DROP POLICY IF EXISTS virtual_scripts_access_policy ON public.virtual_scripts;
CREATE POLICY virtual_scripts_access_policy ON public.virtual_scripts FOR ALL TO public USING (true);
DROP POLICY IF EXISTS virtual_scripts_history_access_policy ON public.virtual_scripts_history;
CREATE POLICY virtual_scripts_history_access_policy ON public.virtual_scripts_history FOR ALL TO public USING (true);
DROP POLICY IF EXISTS workspace_members_access_policy ON public.workspace_members;
CREATE POLICY workspace_members_access_policy ON public.workspace_members FOR ALL TO public USING (true);
DROP POLICY IF EXISTS workspaces_access_policy ON public.workspaces;
CREATE POLICY workspaces_access_policy ON public.workspaces FOR ALL TO public USING (true);
DROP POLICY IF EXISTS zap_results_access_policy ON public.zap_results;
CREATE POLICY zap_results_access_policy ON public.zap_results FOR ALL TO public USING (true);

-- ------------------------------------------ E. profiles / team_members
-- profiles: SELECT = own row or admin; UPDATE = own row or admin (one policy each)
DROP POLICY IF EXISTS "Users can view own profile"     ON public.profiles;
DROP POLICY IF EXISTS "Users can update own profile"   ON public.profiles;
DROP POLICY IF EXISTS "Admins can view all profiles"   ON public.profiles;
DROP POLICY IF EXISTS "Admins can update all profiles" ON public.profiles;
CREATE POLICY "Users see own profile, admins see all"
  ON public.profiles FOR SELECT
  USING ((select auth.uid()) = id OR public.is_admin());
CREATE POLICY "Users update own profile, admins update all"
  ON public.profiles FOR UPDATE
  USING      ((select auth.uid()) = id OR public.is_admin())
  WITH CHECK ((select auth.uid()) = id OR public.is_admin());

-- team_members: the old policies sub-selected team_members inside a policy ON
-- team_members, which Postgres rejects with "infinite recursion detected in
-- policy" — every direct read of team_members by anon/authenticated has been
-- failing in production (the frontend swallowed the error, so team
-- permissions were never applied — BUG-0054). Membership checks now go through
-- SECURITY DEFINER helpers (same pattern as is_admin()), and the SELECT and
-- write policies no longer overlap.
CREATE OR REPLACE FUNCTION public.is_team_member(p_team_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.team_members WHERE team_id = p_team_id AND user_id = auth.uid());
$$;
CREATE OR REPLACE FUNCTION public.is_team_owner(p_team_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.team_members WHERE team_id = p_team_id AND user_id = auth.uid() AND role = 'owner');
$$;
COMMENT ON FUNCTION public.is_team_member(uuid) IS 'RLS helper: is the calling user a member of the team (bypasses RLS to avoid policy recursion)';
COMMENT ON FUNCTION public.is_team_owner(uuid)  IS 'RLS helper: is the calling user an owner of the team (bypasses RLS to avoid policy recursion)';

DROP POLICY IF EXISTS "Users can view team members of their teams"     ON public.team_members;
DROP POLICY IF EXISTS "Admins and team owners can manage team members" ON public.team_members;
DROP POLICY IF EXISTS "Team members and admins can view team members"  ON public.team_members;
DROP POLICY IF EXISTS "Admins and team owners can add team members"    ON public.team_members;
DROP POLICY IF EXISTS "Admins and team owners can update team members" ON public.team_members;
DROP POLICY IF EXISTS "Admins and team owners can remove team members" ON public.team_members;
CREATE POLICY "Team members and admins can view team members"
  ON public.team_members FOR SELECT
  USING (public.is_team_member(team_id) OR public.is_admin());
CREATE POLICY "Admins and team owners can add team members"
  ON public.team_members FOR INSERT
  WITH CHECK (public.is_admin() OR public.is_team_owner(team_id));
CREATE POLICY "Admins and team owners can update team members"
  ON public.team_members FOR UPDATE
  USING (public.is_admin() OR public.is_team_owner(team_id));
CREATE POLICY "Admins and team owners can remove team members"
  ON public.team_members FOR DELETE
  USING (public.is_admin() OR public.is_team_owner(team_id));

-- ------------------------------------------------------ F. FK indexes
CREATE INDEX IF NOT EXISTS idx_deployment_executions_script_result_id ON public.deployment_executions(script_result_id);
CREATE INDEX IF NOT EXISTS idx_test_results_test_id                    ON public.test_results(test_id);

COMMIT;
