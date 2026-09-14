-- 026_campaign_definitions.sql
-- Campaign Definitions Table
-- Stores campaign definitions (collections of testcases/scripts) created in Campaign Builder
-- Campaign executions are tracked in existing campaign_executions table
-- Clean implementation with no backward compatibility

-- Drop existing tables and functions if they exist (for clean recreation)
DROP TABLE IF EXISTS campaigns CASCADE;

CREATE TABLE campaigns (
    campaign_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    campaign_name VARCHAR(255) NOT NULL,  -- Used as identifier for executions
    description TEXT,

    -- Navigation and execution context
    userinterface_name VARCHAR(255),  -- Navigation tree to use
    host_name VARCHAR(255),          -- Default host for execution
    device_name VARCHAR(255),        -- Default device for execution

    -- Configuration
    execution_config JSONB DEFAULT '{}'::jsonb,  -- Execution settings (timeout, parallel, etc.)
    script_configurations JSONB DEFAULT '[]'::jsonb,  -- Array of scripts/testcases to run

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255),
    folder_id INTEGER DEFAULT 0,  -- Folder for organization (matches testcase_definitions)

    -- Constraints
    CONSTRAINT unique_campaign_per_team UNIQUE (team_id, campaign_name)
);

-- Indexes for performance
CREATE INDEX idx_campaign_team ON campaigns(team_id);
CREATE INDEX idx_campaign_name ON campaigns(campaign_name);
CREATE INDEX idx_campaign_ui ON campaigns(userinterface_name);

-- Updated timestamp trigger function
CREATE OR REPLACE FUNCTION update_campaign_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
CREATE TRIGGER campaigns_updated_at
    BEFORE UPDATE ON campaigns
    FOR EACH ROW
    EXECUTE FUNCTION update_campaign_updated_at();

-- Comments
COMMENT ON TABLE campaigns IS 'Campaign definitions from Campaign Builder (collections of testcases/scripts)';
COMMENT ON COLUMN campaigns.campaign_name IS 'Used as identifier in campaign_executions for unified tracking';
COMMENT ON COLUMN campaigns.execution_config IS 'JSON configuration: {continue_on_failure, timeout_minutes, parallel}';
COMMENT ON COLUMN campaigns.script_configurations IS 'JSON array of scripts: [{script_name, parameters, order}]';

-- ================================================
-- Row Level Security (RLS)
-- ================================================

-- Enable RLS
ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY;

-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_campaigns"
ON campaigns
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Public access policy (allows backend with anon key to access)
-- Matches the pattern used in navigation_trees for consistency
CREATE POLICY "campaigns_access_policy"
ON campaigns
FOR ALL
TO public
USING (true);
