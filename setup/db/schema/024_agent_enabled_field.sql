-- Add enabled field to agent_registry for auto-start support
-- Agents with enabled=TRUE auto-start when backend runtime starts
-- Created: 2025-12-07

-- ============================================================================
-- ADD ENABLED COLUMN TO AGENT_REGISTRY
-- ============================================================================

ALTER TABLE agent_registry 
ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE;

-- Index for quick lookup of enabled agents
CREATE INDEX IF NOT EXISTS idx_agent_registry_enabled 
ON agent_registry(enabled) 
WHERE enabled = TRUE;

-- Add comment
COMMENT ON COLUMN agent_registry.enabled IS 'Whether agent auto-starts on backend runtime start';

-- ============================================================================
-- FUNCTION TO GET ENABLED AGENTS
-- Returns all enabled published agents for auto-start
-- ============================================================================

CREATE OR REPLACE FUNCTION get_enabled_agents(p_team_id VARCHAR(255) DEFAULT 'default')
RETURNS TABLE (
    agent_id VARCHAR(255),
    version VARCHAR(50),
    definition JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT ON (ar.agent_id)
        ar.agent_id,
        ar.version,
        ar.definition
    FROM agent_registry ar
    WHERE ar.enabled = TRUE
    AND ar.status = 'published'
    AND ar.team_id = p_team_id
    ORDER BY ar.agent_id, ar.created_at DESC;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_enabled_agents IS 'Get all enabled published agents for auto-start on backend boot';

-- ============================================================================
-- FUNCTION TO SET AGENT ENABLED STATUS
-- ============================================================================

CREATE OR REPLACE FUNCTION set_agent_enabled(
    p_agent_id VARCHAR(255),
    p_enabled BOOLEAN,
    p_team_id VARCHAR(255) DEFAULT 'default'
)
RETURNS BOOLEAN AS $$
DECLARE
    rows_updated INTEGER;
BEGIN
    UPDATE agent_registry
    SET enabled = p_enabled,
        updated_at = NOW()
    WHERE agent_id = p_agent_id
    AND team_id = p_team_id;
    
    GET DIAGNOSTICS rows_updated = ROW_COUNT;
    RETURN rows_updated > 0;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_agent_enabled IS 'Enable or disable agent auto-start';

-- ============================================================================
-- GRANT PERMISSIONS
-- ============================================================================

GRANT EXECUTE ON FUNCTION get_enabled_agents TO authenticated;
GRANT EXECUTE ON FUNCTION set_agent_enabled TO authenticated;

