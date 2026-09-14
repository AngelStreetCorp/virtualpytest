-- =====================================================
-- Studio advisor hardening — runs LAST (schema files are ordered)
-- =====================================================
-- Function-level settings that live outside any single table file. See
-- setup/db/migrations/20260907b_studio_lint_hardening.sql for the rationale
-- and docs/agent/infra/DATABASE.md for the conventions new tables/functions
-- must follow so these lints do not come back.
--
-- NOTE: CREATE OR REPLACE FUNCTION resets a function's SET clauses. A later
-- migration that redefines one of the functions below must repeat its
-- `SET search_path = public, auth, extensions` (or be followed by re-running
-- this file).

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

-- ------------------------------------------------------ F. FK indexes
CREATE INDEX IF NOT EXISTS idx_deployment_executions_script_result_id ON public.deployment_executions(script_result_id);
CREATE INDEX IF NOT EXISTS idx_test_results_test_id                    ON public.test_results(test_id);

