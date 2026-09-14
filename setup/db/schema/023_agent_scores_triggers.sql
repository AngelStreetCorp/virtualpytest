-- =====================================================
-- Agent Scores Automatic Triggers
-- =====================================================
-- Similar to node_metrics/edge_metrics pattern:
-- - Automatically update agent_scores when benchmark completes
-- - Automatically update agent_scores when feedback is submitted
-- - No Python code needed - database handles everything!
-- =====================================================

-- =====================================================
-- 1. Trigger Function: Update Agent Score on Benchmark Complete
-- =====================================================

CREATE OR REPLACE FUNCTION trigger_update_agent_score_on_benchmark()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    -- Only trigger when benchmark run completes
    IF NEW.status = 'completed' AND (OLD IS NULL OR OLD.status != 'completed') THEN
        PERFORM recalculate_agent_score(
            NEW.agent_id,
            NEW.agent_version,
            NEW.team_id
        );
    END IF;
    
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION trigger_update_agent_score_on_benchmark() IS 
'Automatically recalculates agent score when a benchmark run completes.
Triggered by INSERT or UPDATE on agent_benchmark_runs where status becomes completed.';

-- =====================================================
-- 2. Trigger Function: Update Agent Score on Feedback
-- =====================================================

CREATE OR REPLACE FUNCTION trigger_update_agent_score_on_feedback()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    -- Recalculate score whenever feedback is submitted
    PERFORM recalculate_agent_score(
        NEW.agent_id,
        NEW.agent_version,
        NEW.team_id
    );
    
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION trigger_update_agent_score_on_feedback() IS 
'Automatically recalculates agent score when user feedback is submitted.
Triggered by INSERT on agent_feedback.';

-- =====================================================
-- 3. Trigger Function: Update Agent Score on Execution History
-- =====================================================

CREATE OR REPLACE FUNCTION trigger_update_agent_score_on_execution()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    -- Recalculate score when execution completes
    IF NEW.status IN ('completed', 'failed', 'error') THEN
        PERFORM recalculate_agent_score(
            NEW.agent_id,
            NEW.version,
            NEW.team_id
        );
    END IF;
    
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION trigger_update_agent_score_on_execution() IS 
'Automatically recalculates agent score when an agent execution completes.
Updates success_rate_score component.';

-- =====================================================
-- 4. Create Triggers
-- =====================================================

-- Drop existing triggers if any
DROP TRIGGER IF EXISTS trigger_agent_score_on_benchmark ON agent_benchmark_runs;
DROP TRIGGER IF EXISTS trigger_agent_score_on_feedback ON agent_feedback;
DROP TRIGGER IF EXISTS trigger_agent_score_on_execution ON agent_execution_history;

-- Trigger on benchmark runs (when status changes to completed)
CREATE TRIGGER trigger_agent_score_on_benchmark
    AFTER INSERT OR UPDATE OF status ON agent_benchmark_runs
    FOR EACH ROW
    EXECUTE FUNCTION trigger_update_agent_score_on_benchmark();

-- Trigger on feedback (when new feedback is submitted)
CREATE TRIGGER trigger_agent_score_on_feedback
    AFTER INSERT ON agent_feedback
    FOR EACH ROW
    EXECUTE FUNCTION trigger_update_agent_score_on_feedback();

-- Trigger on execution history (when execution completes)
-- Note: Only if agent_execution_history table exists
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'agent_execution_history') THEN
        EXECUTE 'CREATE TRIGGER trigger_agent_score_on_execution
            AFTER INSERT OR UPDATE OF status ON agent_execution_history
            FOR EACH ROW
            EXECUTE FUNCTION trigger_update_agent_score_on_execution()';
    END IF;
END $$;

-- =====================================================
-- 5. Grant Permissions
-- =====================================================

GRANT EXECUTE ON FUNCTION trigger_update_agent_score_on_benchmark() TO authenticated;
GRANT EXECUTE ON FUNCTION trigger_update_agent_score_on_benchmark() TO service_role;
GRANT EXECUTE ON FUNCTION trigger_update_agent_score_on_feedback() TO authenticated;
GRANT EXECUTE ON FUNCTION trigger_update_agent_score_on_feedback() TO service_role;
GRANT EXECUTE ON FUNCTION trigger_update_agent_score_on_execution() TO authenticated;
GRANT EXECUTE ON FUNCTION trigger_update_agent_score_on_execution() TO service_role;

-- =====================================================
-- 6. Backfill existing data (one-time)
-- =====================================================
-- Call this to populate agent_scores from existing benchmark runs and feedback

CREATE OR REPLACE FUNCTION backfill_agent_scores()
RETURNS TABLE(
    agents_updated INTEGER,
    message TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER := 0;
    r RECORD;
BEGIN
    -- Get all unique agent/version/team combinations from benchmarks and feedback
    FOR r IN (
        SELECT DISTINCT agent_id, agent_version, team_id
        FROM (
            SELECT agent_id, agent_version, team_id FROM agent_benchmark_runs
            UNION
            SELECT agent_id, agent_version, team_id FROM agent_feedback
        ) all_agents
    ) LOOP
        PERFORM recalculate_agent_score(r.agent_id, r.agent_version, r.team_id);
        v_count := v_count + 1;
    END LOOP;
    
    agents_updated := v_count;
    message := 'Successfully backfilled ' || v_count || ' agent scores';
    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION backfill_agent_scores() IS 
'One-time function to populate agent_scores from existing benchmark runs and feedback.
Run this after creating the triggers to populate historical data.';

GRANT EXECUTE ON FUNCTION backfill_agent_scores() TO service_role;

