-- 009_ai_graph_cache.sql
-- AI Graph Cache System
-- Stores AI-generated test case graphs for reuse (NO PLANS, NO LEGACY CODE)

-- Drop existing table if it exists (for clean recreation)
DROP TABLE IF EXISTS ai_graph_cache CASCADE;
DROP TABLE IF EXISTS ai_plan_generation CASCADE; -- Remove old naming

-- Create the ai_graph_cache table
CREATE TABLE ai_graph_cache (
    -- Primary identification
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    fingerprint VARCHAR(64) UNIQUE NOT NULL,  -- Changed from VARCHAR(32) to support SHA-256
    
    -- Prompt information
    original_prompt TEXT NOT NULL,
    normalized_prompt VARCHAR(255) NOT NULL,
    
    -- Context signature
    device_model VARCHAR(100) NOT NULL,
    userinterface_name VARCHAR(100) NOT NULL,
    available_nodes JSONB NOT NULL,
    
    -- Graph data (renamed from 'plan')
    graph JSONB NOT NULL,
    
    -- AI analysis
    analysis TEXT,
    
    -- Performance metrics
    success_rate DECIMAL(5,4) NOT NULL DEFAULT 0.0000,
    execution_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    
    -- Usage tracking
    use_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_used TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Team context (for multi-tenancy)
    team_id UUID NOT NULL REFERENCES teams(id)
);

-- Create indexes for performance
CREATE INDEX idx_ai_graph_cache_fingerprint ON ai_graph_cache(fingerprint);
CREATE INDEX idx_ai_graph_cache_normalized_prompt ON ai_graph_cache(normalized_prompt);
CREATE INDEX idx_ai_graph_cache_device_interface ON ai_graph_cache(device_model, userinterface_name);
CREATE INDEX idx_ai_graph_cache_team ON ai_graph_cache(team_id);
CREATE INDEX idx_ai_graph_cache_success_rate ON ai_graph_cache(success_rate DESC, execution_count DESC);
CREATE INDEX idx_ai_graph_cache_last_used ON ai_graph_cache(last_used DESC);
CREATE INDEX idx_ai_graph_cache_lookup ON ai_graph_cache(normalized_prompt, device_model, userinterface_name, success_rate DESC);
CREATE INDEX idx_ai_graph_cache_available_nodes ON ai_graph_cache USING GIN(available_nodes);
CREATE INDEX idx_ai_graph_cache_graph ON ai_graph_cache USING GIN(graph);

-- Enable Row Level Security
ALTER TABLE ai_graph_cache ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Match existing table pattern
CREATE POLICY "ai_graph_cache_access_policy" ON ai_graph_cache
    FOR ALL USING (true);

-- Function to update graph metrics after execution
CREATE OR REPLACE FUNCTION update_ai_graph_metrics(
    p_fingerprint VARCHAR(64),  -- Changed from VARCHAR(32) to support SHA-256
    p_success BOOLEAN,
    p_execution_time_ms INTEGER,
    p_team_id UUID
) RETURNS VOID AS $$
BEGIN
    UPDATE ai_graph_cache 
    SET 
        execution_count = execution_count + 1,
        success_count = CASE WHEN p_success THEN success_count + 1 ELSE success_count END,
        success_rate = (CASE WHEN p_success THEN success_count + 1 ELSE success_count END)::DECIMAL / (execution_count + 1),
        last_used = NOW()
    WHERE fingerprint = p_fingerprint AND team_id = p_team_id;
END;
$$ LANGUAGE plpgsql;

-- Function to cleanup old graphs
CREATE OR REPLACE FUNCTION cleanup_ai_graph_cache(
    p_team_id UUID,
    p_days_old INTEGER DEFAULT 90,
    p_min_success_rate DECIMAL DEFAULT 0.3
) RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- Delete old graphs with low success rates
    DELETE FROM ai_graph_cache 
    WHERE team_id = p_team_id
    AND last_used < NOW() - INTERVAL '1 day' * p_days_old
    AND success_rate < p_min_success_rate;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Grant necessary permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_graph_cache TO authenticated;
GRANT EXECUTE ON FUNCTION update_ai_graph_metrics TO authenticated;
GRANT EXECUTE ON FUNCTION cleanup_ai_graph_cache TO authenticated;

-- Add comments for documentation
COMMENT ON TABLE ai_graph_cache IS 'AI Graph Cache - stores successful AI-generated graphs for reuse';
COMMENT ON COLUMN ai_graph_cache.fingerprint IS 'SHA-256 hash (64 chars) of normalized prompt + context signature for fast lookups';
COMMENT ON COLUMN ai_graph_cache.normalized_prompt IS 'Standardized prompt format for semantic matching';
COMMENT ON COLUMN ai_graph_cache.available_nodes IS 'JSON array of navigation nodes available during graph generation';
COMMENT ON COLUMN ai_graph_cache.graph IS 'Complete AI-generated graph with nodes and edges';
COMMENT ON COLUMN ai_graph_cache.analysis IS 'AI reasoning and analysis (Goal + Thinking)';
COMMENT ON COLUMN ai_graph_cache.success_rate IS 'Calculated success rate (success_count / execution_count)';
COMMENT ON FUNCTION update_ai_graph_metrics IS 'Updates graph performance metrics after execution';
COMMENT ON FUNCTION cleanup_ai_graph_cache IS 'Removes old graphs with poor performance';

