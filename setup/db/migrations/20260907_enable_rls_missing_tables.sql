-- Enable RLS on the five public tables that were created without it.
-- ------------------------------------------------------------------
-- Supabase Studio flags any PostgREST-exposed table in `public` that has RLS
-- disabled. These tables were created by incremental migrations (or schema
-- files) that omitted the standard ENABLE + open-policy boilerplate:
--   - ai_userinterface_tasks / _transitions / _verifications
--       (20260424_ai_userinterface_pack_5layer.sql; canonical 033 has it)
--   - device_control_sessions (20260715_device_control_sessions.sql / 039)
--   - quality_metrics          (039_quality_metrics.sql)
--
-- Policy model is the platform default: RLS on, single permissive
-- `USING (true)` policy. The backend writes with the anon key, so any
-- restrictive policy here would lock the server out. Authorization is
-- enforced in the Flask layer (see docs/agent/platform/SERVER_AUTH.md).
-- Idempotent — safe to re-run.

BEGIN;

ALTER TABLE ai_userinterface_tasks          ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterface_transitions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterface_verifications  ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_control_sessions         ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_metrics                 ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "ai_userinterface_tasks_access_policy"         ON ai_userinterface_tasks;
DROP POLICY IF EXISTS "ai_userinterface_transitions_access_policy"   ON ai_userinterface_transitions;
DROP POLICY IF EXISTS "ai_userinterface_verifications_access_policy" ON ai_userinterface_verifications;
DROP POLICY IF EXISTS "device_control_sessions_access_policy"        ON device_control_sessions;
DROP POLICY IF EXISTS "quality_metrics_access_policy"                ON quality_metrics;

CREATE POLICY "ai_userinterface_tasks_access_policy" ON ai_userinterface_tasks
FOR ALL TO public USING (true);
CREATE POLICY "ai_userinterface_transitions_access_policy" ON ai_userinterface_transitions
FOR ALL TO public USING (true);
CREATE POLICY "ai_userinterface_verifications_access_policy" ON ai_userinterface_verifications
FOR ALL TO public USING (true);
CREATE POLICY "device_control_sessions_access_policy" ON device_control_sessions
FOR ALL TO public USING (true);
CREATE POLICY "quality_metrics_access_policy" ON quality_metrics
FOR ALL TO public USING (true);

COMMIT;
