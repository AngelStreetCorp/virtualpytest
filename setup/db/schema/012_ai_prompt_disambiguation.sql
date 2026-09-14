-- 011_ai_prompt_disambiguation.sql
-- AI Prompt Disambiguation System
-- Stores mappings between user phrases and resolved navigation nodes
-- Clean implementation with no backward compatibility

-- Drop existing table if it exists (for clean recreation)
DROP TABLE IF EXISTS ai_prompt_disambiguation CASCADE;

-- Create the ai_prompt_disambiguation table
CREATE TABLE ai_prompt_disambiguation (
    -- Primary identification
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    
    -- Team context (for multi-tenancy)
    team_id UUID NOT NULL REFERENCES teams(id),
    
    -- User interface context
    userinterface_name VARCHAR NOT NULL,
    
    -- Prompt mapping
    user_phrase TEXT NOT NULL,
    resolved_node VARCHAR NOT NULL,
    
    -- Usage tracking
    usage_count INTEGER DEFAULT 1,
    last_used_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Unique constraint to prevent duplicate mappings
    UNIQUE(team_id, userinterface_name, user_phrase)
);

-- Create indexes for performance
CREATE INDEX idx_ai_prompt_disambiguation_team ON ai_prompt_disambiguation(team_id);
CREATE INDEX idx_ai_prompt_disambiguation_interface ON ai_prompt_disambiguation(userinterface_name);
CREATE INDEX idx_ai_prompt_disambiguation_phrase ON ai_prompt_disambiguation(user_phrase);
CREATE INDEX idx_ai_prompt_disambiguation_lookup ON ai_prompt_disambiguation(team_id, userinterface_name, user_phrase);
CREATE INDEX idx_ai_prompt_disambiguation_usage ON ai_prompt_disambiguation(usage_count DESC, last_used_at DESC);

-- Enable Row Level Security
ALTER TABLE ai_prompt_disambiguation ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Open access for all (matches system monitoring pattern)
CREATE POLICY ai_prompt_disambiguation_access_policy ON ai_prompt_disambiguation
    FOR ALL USING (true);

-- Function to record or update a disambiguation mapping
CREATE OR REPLACE FUNCTION record_disambiguation(
    p_team_id UUID,
    p_userinterface_name VARCHAR,
    p_user_phrase TEXT,
    p_resolved_node VARCHAR
) RETURNS VOID AS $$
BEGIN
    INSERT INTO ai_prompt_disambiguation (
        team_id,
        userinterface_name,
        user_phrase,
        resolved_node,
        usage_count,
        last_used_at
    )
    VALUES (
        p_team_id,
        p_userinterface_name,
        p_user_phrase,
        p_resolved_node,
        1,
        NOW()
    )
    ON CONFLICT (team_id, userinterface_name, user_phrase)
    DO UPDATE SET
        usage_count = ai_prompt_disambiguation.usage_count + 1,
        last_used_at = NOW(),
        resolved_node = EXCLUDED.resolved_node;
END;
$$ LANGUAGE plpgsql;

-- Function to get disambiguation for a phrase
CREATE OR REPLACE FUNCTION get_disambiguation(
    p_team_id UUID,
    p_userinterface_name VARCHAR,
    p_user_phrase TEXT
) RETURNS VARCHAR AS $$
DECLARE
    v_resolved_node VARCHAR;
BEGIN
    SELECT resolved_node INTO v_resolved_node
    FROM ai_prompt_disambiguation
    WHERE team_id = p_team_id
      AND userinterface_name = p_userinterface_name
      AND user_phrase = p_user_phrase
    ORDER BY usage_count DESC, last_used_at DESC
    LIMIT 1;
    
    RETURN v_resolved_node;
END;
$$ LANGUAGE plpgsql;

-- Function to cleanup old unused disambiguations
CREATE OR REPLACE FUNCTION cleanup_old_disambiguations(
    p_days_old INTEGER DEFAULT 180,
    p_min_usage_count INTEGER DEFAULT 2
) RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM ai_prompt_disambiguation
    WHERE last_used_at < NOW() - INTERVAL '1 day' * p_days_old
      AND usage_count < p_min_usage_count;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Grant necessary permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_prompt_disambiguation TO authenticated;
GRANT EXECUTE ON FUNCTION record_disambiguation TO authenticated;
GRANT EXECUTE ON FUNCTION get_disambiguation TO authenticated;
GRANT EXECUTE ON FUNCTION cleanup_old_disambiguations TO authenticated;

-- Add comments for documentation
COMMENT ON TABLE ai_prompt_disambiguation IS 'AI Prompt Disambiguation - stores mappings between user phrases and resolved navigation nodes';
COMMENT ON COLUMN ai_prompt_disambiguation.team_id IS 'Team identifier for multi-tenancy isolation';
COMMENT ON COLUMN ai_prompt_disambiguation.userinterface_name IS 'User interface context where the phrase was used';
COMMENT ON COLUMN ai_prompt_disambiguation.user_phrase IS 'Original user phrase or prompt that needed disambiguation';
COMMENT ON COLUMN ai_prompt_disambiguation.resolved_node IS 'Navigation node that the phrase was resolved to';
COMMENT ON COLUMN ai_prompt_disambiguation.usage_count IS 'Number of times this mapping has been used';
COMMENT ON COLUMN ai_prompt_disambiguation.last_used_at IS 'Timestamp of last usage for cache invalidation';
COMMENT ON FUNCTION record_disambiguation IS 'Records a new disambiguation or updates usage count if it exists';
COMMENT ON FUNCTION get_disambiguation IS 'Retrieves the most frequently used disambiguation for a phrase';
COMMENT ON FUNCTION cleanup_old_disambiguations IS 'Removes old, rarely used disambiguations to keep the table clean';

