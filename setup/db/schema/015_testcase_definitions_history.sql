-- 015_testcase_definitions_history.sql
-- TestCase Definitions History Table
-- Stores version history for test case definitions (like navigation_trees_history)
-- Allows reverting to previous versions

CREATE TABLE IF NOT EXISTS testcase_definitions_history (
    history_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    testcase_id UUID NOT NULL REFERENCES testcase_definitions(testcase_id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    testcase_name VARCHAR(255) NOT NULL,
    description TEXT,
    userinterface_name VARCHAR(255),
    graph_json JSONB NOT NULL,
    created_by VARCHAR(255),
    creation_method VARCHAR(10) DEFAULT 'visual' CHECK (creation_method IN ('visual', 'ai')),
    ai_prompt TEXT,
    ai_analysis TEXT,
    snapshot_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    change_description TEXT,
    
    -- Ensure unique version numbers per test case
    CONSTRAINT unique_testcase_version UNIQUE (testcase_id, version_number)
);

-- Indexes for performance
CREATE INDEX idx_testcase_history_testcase_id ON testcase_definitions_history(testcase_id);
CREATE INDEX idx_testcase_history_team_id ON testcase_definitions_history(team_id);
CREATE INDEX idx_testcase_history_timestamp ON testcase_definitions_history(snapshot_timestamp DESC);
CREATE INDEX idx_testcase_history_version ON testcase_definitions_history(testcase_id, version_number DESC);

-- Function to save testcase version to history before update
CREATE OR REPLACE FUNCTION save_testcase_version_history()
RETURNS TRIGGER AS $$
DECLARE
    next_version INTEGER;
BEGIN
    -- Get the next version number for this test case
    SELECT COALESCE(MAX(version_number), 0) + 1 INTO next_version
    FROM testcase_definitions_history
    WHERE testcase_id = OLD.testcase_id;
    
    -- Save the OLD version to history before updating
    INSERT INTO testcase_definitions_history (
        testcase_id,
        team_id,
        version_number,
        testcase_name,
        description,
        userinterface_name,
        graph_json,
        created_by,
        creation_method,
        ai_prompt,
        ai_analysis,
        snapshot_timestamp,
        change_description
    ) VALUES (
        OLD.testcase_id,
        OLD.team_id,
        next_version,
        OLD.testcase_name,
        OLD.description,
        OLD.userinterface_name,
        OLD.graph_json,
        OLD.created_by,
        OLD.creation_method,
        OLD.ai_prompt,
        OLD.ai_analysis,
        OLD.updated_at,
        'Auto-saved before update'
    );
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to save version before update
CREATE TRIGGER save_testcase_history_before_update
    BEFORE UPDATE ON testcase_definitions
    FOR EACH ROW
    WHEN (OLD.graph_json IS DISTINCT FROM NEW.graph_json OR 
          OLD.description IS DISTINCT FROM NEW.description)
    EXECUTE FUNCTION save_testcase_version_history();

-- RLS Policies (match testcase_definitions pattern)
ALTER TABLE testcase_definitions_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY service_role_all_testcase_history ON testcase_definitions_history
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY testcase_history_access_policy ON testcase_definitions_history
  FOR ALL
  TO public
  USING (true);

-- Comments
COMMENT ON TABLE testcase_definitions_history IS 'Version history for test case definitions - allows reverting to previous versions';
COMMENT ON COLUMN testcase_definitions_history.version_number IS 'Sequential version number for this test case (1, 2, 3...)';
COMMENT ON COLUMN testcase_definitions_history.change_description IS 'Optional description of what changed in this version';
COMMENT ON COLUMN testcase_definitions_history.snapshot_timestamp IS 'When this version was created';
COMMENT ON FUNCTION save_testcase_version_history() IS 'Automatically saves test case version to history before updates';

