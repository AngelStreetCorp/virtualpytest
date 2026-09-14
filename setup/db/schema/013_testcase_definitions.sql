-- 013_testcase_definitions.sql
-- TestCase Definitions Table
-- Stores visual test case graphs created in TestCase Builder
-- Execution results stored in existing script_results table
-- Clean implementation with no backward compatibility

-- Drop existing tables and functions if they exist (for clean recreation)
DROP TABLE IF EXISTS testcase_definitions CASCADE;
DROP FUNCTION IF EXISTS update_testcase_updated_at();

CREATE TABLE testcase_definitions (
    testcase_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    testcase_name VARCHAR(255) NOT NULL,  -- Used as script_name in script_results
    description TEXT,
    userinterface_name VARCHAR(255),  -- Required navigation tree
    graph_json JSONB NOT NULL,  -- Stores nodes/edges (React Flow format)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255),
    
    -- Environment management
    environment VARCHAR(10) DEFAULT 'dev' CHECK (environment IN ('dev', 'test', 'prod')),
    
    -- Creation metadata
    creation_method VARCHAR(10) DEFAULT 'visual' CHECK (creation_method IN ('visual', 'ai')),
    ai_prompt TEXT,  -- Original prompt if AI-generated
    ai_analysis TEXT,  -- AI reasoning if AI-generated
    
    -- Unique constraint: One test case name per team per environment
    CONSTRAINT unique_testcase_per_team_env UNIQUE (team_id, testcase_name, environment)
);

-- Indexes for performance
CREATE INDEX idx_testcase_team ON testcase_definitions(team_id);
CREATE INDEX idx_testcase_name ON testcase_definitions(testcase_name);
CREATE INDEX idx_testcase_ui ON testcase_definitions(userinterface_name);
CREATE INDEX idx_testcase_environment ON testcase_definitions(environment);

-- Updated timestamp trigger function
CREATE OR REPLACE FUNCTION update_testcase_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
CREATE TRIGGER testcase_definitions_updated_at
    BEFORE UPDATE ON testcase_definitions
    FOR EACH ROW
    EXECUTE FUNCTION update_testcase_updated_at();

-- Comments
COMMENT ON TABLE testcase_definitions IS 'Test case definitions from TestCase Builder (visual or AI-generated)';
COMMENT ON COLUMN testcase_definitions.graph_json IS 'React Flow graph: {nodes: [...], edges: [...]}';
COMMENT ON COLUMN testcase_definitions.testcase_name IS 'Used as script_name in script_results for unified tracking';
COMMENT ON COLUMN testcase_definitions.environment IS 'Deployment environment: dev (default), test, or prod';
COMMENT ON COLUMN testcase_definitions.creation_method IS 'How test case was created: visual (drag-drop) or ai (prompt)';
COMMENT ON COLUMN testcase_definitions.ai_prompt IS 'Original natural language prompt if AI-generated';
COMMENT ON COLUMN testcase_definitions.ai_analysis IS 'AI reasoning and analysis if AI-generated';

-- ================================================
-- Row Level Security (RLS)
-- ================================================

-- Enable RLS
ALTER TABLE testcase_definitions ENABLE ROW LEVEL SECURITY;

-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_testcase_definitions"
ON testcase_definitions
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Public access policy (allows backend with anon key to access)
-- Matches the pattern used in navigation_trees for consistency
CREATE POLICY "testcase_definitions_access_policy"
ON testcase_definitions
FOR ALL
TO public
USING (true);


