-- Agent Registry Tables for Multi-Agent Platform
-- Phase 1: Agent Configuration & Versioning
-- Created: 2025-12-06

-- Drop existing tables if they exist (for clean recreation)
DROP TABLE IF EXISTS agent_execution_history CASCADE;
DROP TABLE IF EXISTS agent_instances CASCADE;
DROP TABLE IF EXISTS agent_event_triggers CASCADE;
DROP TABLE IF EXISTS agent_registry CASCADE;

-- ============================================================================
-- AGENT REGISTRY TABLE
-- Stores agent definitions, versions, and configurations
-- ============================================================================

CREATE TABLE agent_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(255) NOT NULL,          -- Unique agent identifier (e.g., 'qa-manager')
    name VARCHAR(255) NOT NULL,              -- Human-readable name
    version VARCHAR(50) NOT NULL,            -- Semantic version (e.g., '2.1.0')
    author VARCHAR(255) NOT NULL,            -- Creator/owner
    description TEXT,
    goal_type VARCHAR(50) NOT NULL,          -- 'continuous' or 'on-demand'
    goal_description TEXT NOT NULL,
    definition JSONB NOT NULL,               -- Full agent definition (YAML as JSON)
    status VARCHAR(50) DEFAULT 'draft',      -- 'draft', 'published', 'deprecated'
    team_id VARCHAR(255) NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255),
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],     -- Tags for categorization
    metadata JSONB DEFAULT '{}'::jsonb,      -- Additional metadata
    
    -- Unique constraint: one version per agent
    UNIQUE(agent_id, version)
);

-- Indexes for agent registry
CREATE INDEX idx_agent_registry_agent_id ON agent_registry(agent_id);
CREATE INDEX idx_agent_registry_version ON agent_registry(version);
CREATE INDEX idx_agent_registry_status ON agent_registry(status);
CREATE INDEX idx_agent_registry_team ON agent_registry(team_id);
CREATE INDEX idx_agent_registry_goal_type ON agent_registry(goal_type);
CREATE INDEX idx_agent_registry_tags ON agent_registry USING GIN(tags);
CREATE INDEX idx_agent_registry_created ON agent_registry(created_at DESC);

-- Add comments
COMMENT ON TABLE agent_registry IS 'Registry of all agent definitions and versions';
COMMENT ON COLUMN agent_registry.agent_id IS 'Unique identifier for the agent (e.g., qa-manager, explorer)';
COMMENT ON COLUMN agent_registry.version IS 'Semantic version (e.g., 1.0.0, 2.1.0)';
COMMENT ON COLUMN agent_registry.goal_type IS 'continuous: always running, on-demand: triggered';
COMMENT ON COLUMN agent_registry.definition IS 'Complete agent configuration as JSONB';
COMMENT ON COLUMN agent_registry.status IS 'draft, published, deprecated';

-- ============================================================================
-- AGENT EVENT TRIGGERS TABLE
-- Maps which events trigger which agents
-- ============================================================================

CREATE TABLE agent_event_triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(255) NOT NULL,          -- References agent_registry.agent_id (soft reference)
    event_type VARCHAR(255) NOT NULL,        -- Event type pattern (e.g., 'alert.*', 'build.deployed')
    priority VARCHAR(50) NOT NULL,           -- 'critical', 'high', 'normal', 'low'
    filters JSONB DEFAULT '{}'::jsonb,       -- Additional event filtering criteria
    team_id VARCHAR(255) NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    
    -- Note: No FK constraint - agent_id is not unique in agent_registry (agent_id+version is)
    -- Triggers apply to all versions of an agent, constraint enforced at application level
);

-- Indexes for event trigger lookup
CREATE INDEX idx_agent_triggers_event ON agent_event_triggers(event_type);
CREATE INDEX idx_agent_triggers_agent ON agent_event_triggers(agent_id);
CREATE INDEX idx_agent_triggers_priority ON agent_event_triggers(priority);
CREATE INDEX idx_agent_triggers_team ON agent_event_triggers(team_id);

-- Add comments
COMMENT ON TABLE agent_event_triggers IS 'Maps which events activate which agents';
COMMENT ON COLUMN agent_event_triggers.event_type IS 'Event type or pattern (supports wildcards)';
COMMENT ON COLUMN agent_event_triggers.filters IS 'Additional JSON filters for event matching';

-- ============================================================================
-- AGENT INSTANCES TABLE
-- Tracks running agent instances
-- ============================================================================

CREATE TABLE agent_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id VARCHAR(255) UNIQUE NOT NULL,  -- Unique instance identifier
    agent_id VARCHAR(255) NOT NULL,             -- References agent_registry.agent_id
    version VARCHAR(50) NOT NULL,               -- Agent version being run
    state VARCHAR(50) NOT NULL DEFAULT 'idle',  -- 'idle', 'running', 'paused', 'error'
    current_task VARCHAR(255),                  -- Description of current task
    task_id VARCHAR(255),                       -- ID of current task/event
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    stopped_at TIMESTAMP WITH TIME ZONE,
    team_id VARCHAR(255) NOT NULL DEFAULT 'default',
    metadata JSONB DEFAULT '{}'::jsonb,
    
    -- Foreign key to agent_registry
    FOREIGN KEY (agent_id, version) REFERENCES agent_registry(agent_id, version)
);

-- Indexes for instance tracking
CREATE INDEX idx_agent_instances_agent ON agent_instances(agent_id);
CREATE INDEX idx_agent_instances_state ON agent_instances(state);
CREATE INDEX idx_agent_instances_team ON agent_instances(team_id);
CREATE INDEX idx_agent_instances_started ON agent_instances(started_at DESC);

-- Add comments
COMMENT ON TABLE agent_instances IS 'Tracks currently running agent instances';
COMMENT ON COLUMN agent_instances.state IS 'idle, running, paused, error';
COMMENT ON COLUMN agent_instances.current_task IS 'Description of what agent is doing';

-- ============================================================================
-- AGENT EXECUTION HISTORY TABLE
-- Records all agent task executions for evaluation
-- ============================================================================

CREATE TABLE agent_execution_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id VARCHAR(255) NOT NULL,
    agent_id VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL,
    task_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(255),
    event_id VARCHAR(255),
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_seconds FLOAT,
    status VARCHAR(50) NOT NULL,              -- 'success', 'failed', 'aborted'
    error_message TEXT,
    token_usage INTEGER,
    cost_usd DECIMAL(10, 4),
    tool_calls INTEGER DEFAULT 0,
    user_rating INTEGER,                      -- 1-5 rating from user
    user_feedback TEXT,                       -- Optional feedback text
    team_id VARCHAR(255) NOT NULL DEFAULT 'default',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for execution history
CREATE INDEX idx_execution_history_instance ON agent_execution_history(instance_id);
CREATE INDEX idx_execution_history_agent ON agent_execution_history(agent_id, version);
CREATE INDEX idx_execution_history_task ON agent_execution_history(task_id);
CREATE INDEX idx_execution_history_status ON agent_execution_history(status);
CREATE INDEX idx_execution_history_team ON agent_execution_history(team_id);
CREATE INDEX idx_execution_history_started ON agent_execution_history(started_at DESC);

-- Add comments
COMMENT ON TABLE agent_execution_history IS 'Historical record of all agent task executions';
COMMENT ON COLUMN agent_execution_history.status IS 'success, failed, aborted';
COMMENT ON COLUMN agent_execution_history.user_rating IS 'User satisfaction rating (1-5)';

-- ============================================================================
-- AGENT METRICS VIEW
-- Aggregated performance metrics per agent version
-- ============================================================================

CREATE OR REPLACE VIEW agent_metrics
WITH (security_invoker = true) AS
SELECT
    agent_id,
    version,
    COUNT(*) as total_executions,
    COUNT(*) FILTER (WHERE status = 'success') as successful_executions,
    COUNT(*) FILTER (WHERE status = 'failed') as failed_executions,
    COUNT(*) FILTER (WHERE status = 'aborted') as aborted_executions,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'success') / NULLIF(COUNT(*), 0),
        2
    ) as success_rate_percent,
    ROUND(AVG(duration_seconds)::numeric, 2) as avg_duration_seconds,
    ROUND(AVG(token_usage)::numeric, 0) as avg_token_usage,
    ROUND(SUM(cost_usd)::numeric, 2) as total_cost_usd,
    ROUND(AVG(cost_usd)::numeric, 4) as avg_cost_per_task_usd,
    ROUND(AVG(user_rating)::numeric, 2) as avg_user_rating,
    MAX(started_at) as last_execution,
    team_id
FROM agent_execution_history
GROUP BY agent_id, version, team_id;

-- Add comment
COMMENT ON VIEW agent_metrics IS 'Aggregated performance metrics per agent version';

-- ============================================================================
-- FUNCTION TO GET LATEST AGENT VERSION
-- Returns the latest published version of an agent
-- ============================================================================

CREATE OR REPLACE FUNCTION get_latest_agent_version(p_agent_id VARCHAR(255))
RETURNS VARCHAR(50) AS $$
DECLARE
    latest_version VARCHAR(50);
BEGIN
    SELECT version INTO latest_version
    FROM agent_registry
    WHERE agent_id = p_agent_id
    AND status = 'published'
    ORDER BY created_at DESC
    LIMIT 1;
    
    RETURN latest_version;
END;
$$ LANGUAGE plpgsql;

-- Add comment
COMMENT ON FUNCTION get_latest_agent_version IS 'Get the latest published version of an agent';

-- ============================================================================
-- FUNCTION TO GET AGENTS FOR EVENT TYPE
-- Returns all agents that should handle a specific event type
-- ============================================================================

CREATE OR REPLACE FUNCTION get_agents_for_event(p_event_type VARCHAR(255), p_team_id VARCHAR(255) DEFAULT 'default')
RETURNS TABLE (
    agent_id VARCHAR(255),
    version VARCHAR(50),
    definition JSONB,
    priority VARCHAR(50)
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT
        ar.agent_id,
        ar.version,
        ar.definition,
        aet.priority
    FROM agent_registry ar
    JOIN agent_event_triggers aet ON ar.agent_id = aet.agent_id
    WHERE aet.event_type = p_event_type
    AND ar.status = 'published'
    AND ar.team_id = p_team_id
    ORDER BY 
        CASE aet.priority
            WHEN 'critical' THEN 1
            WHEN 'high' THEN 2
            WHEN 'normal' THEN 3
            WHEN 'low' THEN 4
        END;
END;
$$ LANGUAGE plpgsql;

-- Add comment
COMMENT ON FUNCTION get_agents_for_event IS 'Get all published agents that handle a specific event type';

-- ============================================================================
-- TRIGGER TO UPDATE updated_at ON agent_registry
-- ============================================================================

CREATE OR REPLACE FUNCTION update_agent_registry_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_agent_registry_updated_at
    BEFORE UPDATE ON agent_registry
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_registry_updated_at();

-- ============================================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================================

-- Enable Row Level Security (RLS)
ALTER TABLE agent_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_event_triggers ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_execution_history ENABLE ROW LEVEL SECURITY;

-- RLS Policies for agent_registry
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_agent_registry"
ON agent_registry
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Team-based access policy (allows authenticated users to access agents for their teams)
CREATE POLICY "agent_registry_access_policy"
ON agent_registry
FOR ALL
TO authenticated
USING (true);

-- RLS Policies for agent_event_triggers
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_agent_event_triggers"
ON agent_event_triggers
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Team-based access policy
CREATE POLICY "agent_event_triggers_access_policy"
ON agent_event_triggers
FOR ALL
TO authenticated
USING (true);

-- RLS Policies for agent_instances
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_agent_instances"
ON agent_instances
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Team-based access policy
CREATE POLICY "agent_instances_access_policy"
ON agent_instances
FOR ALL
TO authenticated
USING (true);

-- RLS Policies for agent_execution_history
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_agent_execution_history"
ON agent_execution_history
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Team-based access policy (read-only for authenticated users)
CREATE POLICY "agent_execution_history_access_policy"
ON agent_execution_history
FOR SELECT
TO authenticated
USING (true);

-- ============================================================================
-- GRANT PERMISSIONS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE ON agent_registry TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON agent_event_triggers TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON agent_instances TO authenticated;
GRANT SELECT, INSERT ON agent_execution_history TO authenticated;
GRANT SELECT ON agent_metrics TO authenticated;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO authenticated;

-- ============================================================================
-- SAMPLE DATA (Optional - for testing)
-- ============================================================================

-- Sample QA Manager agent definition (disabled - for reference)
/*
INSERT INTO agent_registry (
    agent_id, name, version, author, description,
    goal_type, goal_description, definition, status, team_id
) VALUES (
    'qa-manager',
    'QA Manager',
    '1.0.0',
    'system',
    'Autonomous quality validation across all userinterfaces',
    'continuous',
    'Maintain quality across all userinterfaces through continuous monitoring and testing',
    '{"metadata": {"id": "qa-manager", "name": "QA Manager", "version": "1.0.0"}}',
    'draft',
    'default'
) ON CONFLICT (agent_id, version) DO NOTHING;
*/

