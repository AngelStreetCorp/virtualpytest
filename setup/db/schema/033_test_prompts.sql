-- ============================================================================
-- Test Prompts — AI-driven test prompt lifecycle (dev → prod → graph)
-- ============================================================================

-- Drop existing objects
DROP TABLE IF EXISTS test_prompt_executions CASCADE;
DROP TABLE IF EXISTS test_prompts CASCADE;

-- ============================================================================
-- test_prompts: Versioned AI test prompts with dev/prod lifecycle
-- ============================================================================
CREATE TABLE test_prompts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    prompt TEXT NOT NULL,
    acceptance_criteria TEXT NOT NULL,
    target_screen_node_id VARCHAR(255),
    target_screen_label VARCHAR(255),
    userinterface_name VARCHAR(255) NOT NULL,

    -- Versioning: v1 has parent_id=NULL, v2 points to v1, v3 points to v2
    version INT NOT NULL DEFAULT 1,
    parent_id UUID REFERENCES test_prompts(id) ON DELETE SET NULL,

    -- Lifecycle
    mode VARCHAR(10) NOT NULL DEFAULT 'dev' CHECK (mode IN ('dev', 'prod')),
    testcase_id UUID,  -- linked TestCase graph after conversion (no FK to avoid circular deps)

    -- Metadata
    created_by VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (team_id, name, version)
);

CREATE INDEX idx_test_prompts_team_id ON test_prompts(team_id);
CREATE INDEX idx_test_prompts_parent_id ON test_prompts(parent_id);
CREATE INDEX idx_test_prompts_mode ON test_prompts(team_id, mode);

ALTER TABLE test_prompts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "test_prompts_access_policy" ON test_prompts
    FOR ALL TO public
    USING (true);

COMMENT ON TABLE test_prompts IS 'AI test prompts with versioning and dev/prod lifecycle';
COMMENT ON COLUMN test_prompts.parent_id IS 'Previous version — walk chain for full history';
COMMENT ON COLUMN test_prompts.mode IS 'dev = iterating, prod = validated and stable';
COMMENT ON COLUMN test_prompts.testcase_id IS 'Linked TestCase graph after AI conversion from prod prompt';

-- ============================================================================
-- test_prompt_executions: Execution history with human feedback loop
-- ============================================================================
CREATE TABLE test_prompt_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_prompt_id UUID NOT NULL REFERENCES test_prompts(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    host_name VARCHAR(255) NOT NULL,
    device_id VARCHAR(255) NOT NULL,

    -- Execution result
    status VARCHAR(20) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'passed', 'failed', 'error')),
    script_result_id UUID,  -- links to script_results for report/logs
    report_url TEXT,
    logs_url TEXT,
    execution_time_ms INT,

    -- Feedback loop
    human_feedback TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    executed_by VARCHAR(255)
);

CREATE INDEX idx_test_prompt_executions_prompt_id ON test_prompt_executions(test_prompt_id);
CREATE INDEX idx_test_prompt_executions_team_id ON test_prompt_executions(team_id);

ALTER TABLE test_prompt_executions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "test_prompt_executions_access_policy" ON test_prompt_executions
    FOR ALL TO public
    USING (true);

COMMENT ON TABLE test_prompt_executions IS 'Execution history for test prompts with human feedback for AI iteration';
COMMENT ON COLUMN test_prompt_executions.human_feedback IS 'User feedback after reviewing execution — fed to AI for prompt revision';
COMMENT ON COLUMN test_prompt_executions.script_result_id IS 'Links to script_results table for HTML report and logs artifacts';
