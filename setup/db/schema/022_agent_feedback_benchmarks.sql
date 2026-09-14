-- =====================================================
-- Agent Feedback & Benchmarking System
-- =====================================================
-- Provides:
-- 1. User feedback collection per task
-- 2. Benchmark test definitions
-- 3. Benchmark run tracking
-- 4. Aggregated agent scores
-- =====================================================

-- Drop existing tables if any (for clean schema updates)
DROP TABLE IF EXISTS agent_benchmark_results CASCADE;
DROP TABLE IF EXISTS agent_benchmark_runs CASCADE;
DROP TABLE IF EXISTS agent_benchmarks CASCADE;
DROP TABLE IF EXISTS agent_feedback CASCADE;
DROP TABLE IF EXISTS agent_scores CASCADE;

-- =====================================================
-- 1. Agent Feedback Table
-- =====================================================
-- Stores user ratings after task completion

CREATE TABLE agent_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Agent reference
    agent_id VARCHAR(100) NOT NULL,
    agent_version VARCHAR(20) NOT NULL,
    
    -- Task reference (from agent_execution_history)
    execution_id UUID,
    task_description TEXT,
    
    -- Rating (1-5 stars)
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    
    -- Optional feedback text
    comment TEXT,
    
    -- Categorization
    feedback_type VARCHAR(50) DEFAULT 'task_completion',  -- task_completion, bug_report, suggestion
    
    -- Metadata
    team_id VARCHAR(100) NOT NULL DEFAULT 'default',
    user_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for feedback queries
CREATE INDEX idx_agent_feedback_agent ON agent_feedback(agent_id, agent_version);
CREATE INDEX idx_agent_feedback_team ON agent_feedback(team_id);
CREATE INDEX idx_agent_feedback_created ON agent_feedback(created_at DESC);
CREATE INDEX idx_agent_feedback_rating ON agent_feedback(rating);

-- =====================================================
-- 2. Benchmark Definitions Table
-- =====================================================
-- Defines test cases with fixed inputs and expected outputs

CREATE TABLE agent_benchmarks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Test identification
    test_id VARCHAR(50) UNIQUE NOT NULL,  -- e.g., 'bench_001_navigation'
    name VARCHAR(200) NOT NULL,
    description TEXT,
    
    -- Test category
    category VARCHAR(50) NOT NULL,  -- navigation, detection, execution, analysis, recovery
    
    -- Test definition
    input_prompt TEXT NOT NULL,           -- The task/prompt given to agent
    expected_output JSONB NOT NULL,       -- Expected result (can be partial match)
    validation_type VARCHAR(50) NOT NULL, -- exact, contains, regex, custom
    
    -- Scoring
    max_points DECIMAL(5,2) DEFAULT 1.0,
    timeout_seconds INTEGER DEFAULT 60,
    
    -- Applicability
    applicable_agent_types TEXT[],  -- Which agent types can run this test
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_benchmarks_category ON agent_benchmarks(category);
CREATE INDEX idx_benchmarks_active ON agent_benchmarks(is_active);

-- =====================================================
-- 3. Benchmark Runs Table
-- =====================================================
-- Tracks each benchmark execution

CREATE TABLE agent_benchmark_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Agent being tested
    agent_id VARCHAR(100) NOT NULL,
    agent_version VARCHAR(20) NOT NULL,
    
    -- Run status
    status VARCHAR(20) DEFAULT 'pending',  -- pending, running, completed, failed, cancelled
    
    -- Progress
    total_tests INTEGER DEFAULT 0,
    completed_tests INTEGER DEFAULT 0,
    passed_tests INTEGER DEFAULT 0,
    failed_tests INTEGER DEFAULT 0,
    
    -- Scores
    score_percent DECIMAL(5,2),  -- 0-100
    
    -- Timing
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    
    -- Error info
    error_message TEXT,
    
    -- Metadata
    team_id VARCHAR(100) NOT NULL DEFAULT 'default',
    triggered_by UUID,  -- User who started the benchmark
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_benchmark_runs_agent ON agent_benchmark_runs(agent_id, agent_version);
CREATE INDEX idx_benchmark_runs_status ON agent_benchmark_runs(status);
CREATE INDEX idx_benchmark_runs_team ON agent_benchmark_runs(team_id);
CREATE INDEX idx_benchmark_runs_created ON agent_benchmark_runs(created_at DESC);

-- =====================================================
-- 4. Benchmark Results Table
-- =====================================================
-- Individual test results within a run
-- NOTE: benchmark_id is nullable for file-based tests (YAML)

CREATE TABLE agent_benchmark_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Parent run
    run_id UUID NOT NULL REFERENCES agent_benchmark_runs(id) ON DELETE CASCADE,
    
    -- Test reference (benchmark_id nullable for file-based tests)
    benchmark_id UUID REFERENCES agent_benchmarks(id),
    test_id VARCHAR(50) NOT NULL,
    
    -- Result
    passed BOOLEAN NOT NULL,
    points_earned DECIMAL(5,2) DEFAULT 0,
    points_possible DECIMAL(5,2) DEFAULT 1.0,
    
    -- Execution details
    actual_output JSONB,
    duration_seconds DECIMAL(10,3),
    
    -- Failure info
    failure_reason TEXT,
    
    -- Metadata
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_benchmark_results_run ON agent_benchmark_results(run_id);
CREATE INDEX idx_benchmark_results_test ON agent_benchmark_results(test_id);
CREATE INDEX idx_benchmark_results_passed ON agent_benchmark_results(passed);

-- =====================================================
-- 5. Agent Scores Table
-- =====================================================
-- Aggregated scores per agent/version (cached for performance)

CREATE TABLE agent_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Agent reference
    agent_id VARCHAR(100) NOT NULL,
    agent_version VARCHAR(20) NOT NULL,
    
    -- Component scores (0-100)
    benchmark_score DECIMAL(5,2) DEFAULT 0,      -- From benchmark runs
    user_rating_score DECIMAL(5,2) DEFAULT 0,    -- From feedback (1-5 → 0-100)
    success_rate_score DECIMAL(5,2) DEFAULT 0,   -- From execution history
    cost_efficiency_score DECIMAL(5,2) DEFAULT 0, -- Tokens/complexity ratio
    
    -- Overall weighted score
    overall_score DECIMAL(5,2) DEFAULT 0,
    
    -- Raw metrics
    total_executions INTEGER DEFAULT 0,
    successful_executions INTEGER DEFAULT 0,
    total_feedback_count INTEGER DEFAULT 0,
    avg_user_rating DECIMAL(3,2) DEFAULT 0,  -- 1-5 scale
    avg_duration_seconds DECIMAL(10,2) DEFAULT 0,
    total_cost_usd DECIMAL(10,4) DEFAULT 0,
    
    -- Benchmark metrics
    last_benchmark_run_id UUID,
    last_benchmark_score DECIMAL(5,2),
    benchmark_run_count INTEGER DEFAULT 0,
    
    -- Ranking
    rank_overall INTEGER,
    rank_in_category INTEGER,
    
    -- Trend (compared to previous period)
    score_trend VARCHAR(10),  -- up, down, stable
    score_change DECIMAL(5,2) DEFAULT 0,
    
    -- Metadata
    team_id VARCHAR(100) NOT NULL DEFAULT 'default',
    calculated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Unique constraint
    UNIQUE(agent_id, agent_version, team_id)
);

-- Indexes
CREATE INDEX idx_agent_scores_agent ON agent_scores(agent_id, agent_version);
CREATE INDEX idx_agent_scores_team ON agent_scores(team_id);
CREATE INDEX idx_agent_scores_overall ON agent_scores(overall_score DESC);
CREATE INDEX idx_agent_scores_rank ON agent_scores(rank_overall);

-- =====================================================
-- 6. Default Benchmark Tests (MOVED TO YAML FILES)
-- =====================================================
-- Test definitions are now file-based for:
-- - Version control (Git)
-- - Easy editing without SQL
-- - Code review in PRs
--
-- Location: backend_server/src/agent/benchmarks/tests/*.yaml
--
-- The agent_benchmarks table remains for future dynamic tests
-- but defaults are loaded from YAML files at startup.
-- =====================================================

-- =====================================================
-- 7. View for Leaderboard
-- =====================================================

CREATE OR REPLACE VIEW agent_leaderboard
WITH (security_invoker = true) AS
SELECT
    agent_id,
    agent_version,
    overall_score,
    benchmark_score,
    user_rating_score,
    success_rate_score,
    avg_user_rating,
    total_executions,
    benchmark_run_count,
    score_trend,
    score_change,
    rank_overall,
    team_id,
    calculated_at
FROM agent_scores
WHERE overall_score > 0
ORDER BY overall_score DESC;

-- =====================================================
-- 8. Function to Recalculate Agent Scores
-- =====================================================

CREATE OR REPLACE FUNCTION recalculate_agent_score(
    p_agent_id VARCHAR(100),
    p_agent_version VARCHAR(20),
    p_team_id VARCHAR(100)
) RETURNS VOID AS $$
DECLARE
    v_benchmark_score DECIMAL(5,2);
    v_user_rating_avg DECIMAL(3,2);
    v_user_rating_score DECIMAL(5,2);
    v_success_rate DECIMAL(5,2);
    v_total_executions INTEGER;
    v_successful_executions INTEGER;
    v_feedback_count INTEGER;
    v_overall_score DECIMAL(5,2);
BEGIN
    -- Get latest benchmark score
    SELECT score_percent INTO v_benchmark_score
    FROM agent_benchmark_runs
    WHERE agent_id = p_agent_id 
      AND agent_version = p_agent_version
      AND status = 'completed'
    ORDER BY completed_at DESC
    LIMIT 1;
    
    v_benchmark_score := COALESCE(v_benchmark_score, 0);
    
    -- Get average user rating
    SELECT AVG(rating), COUNT(*) 
    INTO v_user_rating_avg, v_feedback_count
    FROM agent_feedback
    WHERE agent_id = p_agent_id 
      AND agent_version = p_agent_version
      AND team_id = p_team_id;
    
    v_user_rating_avg := COALESCE(v_user_rating_avg, 0);
    v_feedback_count := COALESCE(v_feedback_count, 0);
    -- Convert 1-5 rating to 0-100 score
    v_user_rating_score := (v_user_rating_avg - 1) * 25;
    
    -- Get success rate from execution history (if table exists)
    -- Handle gracefully if agent_execution_history doesn't exist yet
    v_total_executions := 0;
    v_successful_executions := 0;
    v_success_rate := 0;
    
    BEGIN
        EXECUTE '
            SELECT COUNT(*), COUNT(*) FILTER (WHERE status = ''completed'')
            FROM agent_execution_history
            WHERE agent_id = $1 
              AND version = $2
              AND team_id = $3'
        INTO v_total_executions, v_successful_executions
        USING p_agent_id, p_agent_version, p_team_id;
        
        v_total_executions := COALESCE(v_total_executions, 0);
        v_successful_executions := COALESCE(v_successful_executions, 0);
        
        IF v_total_executions > 0 THEN
            v_success_rate := (v_successful_executions::DECIMAL / v_total_executions) * 100;
        END IF;
    EXCEPTION
        WHEN undefined_table THEN
            -- Table doesn't exist yet, use defaults
            NULL;
    END;
    
    -- Calculate overall score (weighted)
    -- 40% benchmark + 30% user rating + 20% success rate + 10% cost efficiency (TBD)
    v_overall_score := (v_benchmark_score * 0.4) + 
                       (v_user_rating_score * 0.3) + 
                       (v_success_rate * 0.2) +
                       (0 * 0.1);  -- Cost efficiency TBD
    
    -- Upsert score
    INSERT INTO agent_scores (
        agent_id, agent_version, team_id,
        benchmark_score, user_rating_score, success_rate_score,
        overall_score, avg_user_rating, total_feedback_count,
        total_executions, successful_executions,
        calculated_at
    ) VALUES (
        p_agent_id, p_agent_version, p_team_id,
        v_benchmark_score, v_user_rating_score, v_success_rate,
        v_overall_score, v_user_rating_avg, v_feedback_count,
        v_total_executions, v_successful_executions,
        NOW()
    )
    ON CONFLICT (agent_id, agent_version, team_id) 
    DO UPDATE SET
        benchmark_score = EXCLUDED.benchmark_score,
        user_rating_score = EXCLUDED.user_rating_score,
        success_rate_score = EXCLUDED.success_rate_score,
        overall_score = EXCLUDED.overall_score,
        avg_user_rating = EXCLUDED.avg_user_rating,
        total_feedback_count = EXCLUDED.total_feedback_count,
        total_executions = EXCLUDED.total_executions,
        successful_executions = EXCLUDED.successful_executions,
        calculated_at = NOW();
        
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- ROW LEVEL SECURITY (RLS)
-- =====================================================

-- Enable Row Level Security (RLS)
ALTER TABLE agent_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_benchmarks ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_benchmark_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_benchmark_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_scores ENABLE ROW LEVEL SECURITY;

-- RLS Policies for agent_feedback
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_agent_feedback"
ON agent_feedback
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Team-based access policy
CREATE POLICY "agent_feedback_access_policy"
ON agent_feedback
FOR ALL
TO authenticated
USING (true);

-- RLS Policies for agent_benchmarks
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_agent_benchmarks"
ON agent_benchmarks
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Open access policy (no team_id column)
CREATE POLICY "agent_benchmarks_access_policy"
ON agent_benchmarks
FOR ALL
TO authenticated
USING (true);

-- RLS Policies for agent_benchmark_runs
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_agent_benchmark_runs"
ON agent_benchmark_runs
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Team-based access policy
CREATE POLICY "agent_benchmark_runs_access_policy"
ON agent_benchmark_runs
FOR ALL
TO authenticated
USING (true);

-- RLS Policies for agent_benchmark_results
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_agent_benchmark_results"
ON agent_benchmark_results
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Open access policy (no team_id column)
CREATE POLICY "agent_benchmark_results_access_policy"
ON agent_benchmark_results
FOR ALL
TO authenticated
USING (true);

-- RLS Policies for agent_scores
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_agent_scores"
ON agent_scores
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Team-based access policy
CREATE POLICY "agent_scores_access_policy"
ON agent_scores
FOR ALL
TO authenticated
USING (true);

