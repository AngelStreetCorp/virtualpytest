-- 017_requirements_management.sql
-- Requirements Management System
-- Links requirements to testcases and scripts for coverage tracking
-- Follows existing RLS policy patterns from testcase_definitions

-- ================================================
-- 1. Requirements Table
-- ================================================

CREATE TABLE IF NOT EXISTS requirements (
    requirement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    
    -- Requirement identification
    requirement_code VARCHAR(50) NOT NULL,  -- e.g., "REQ_PLAYBACK_001", "REQ_AUTH_005"
    requirement_name TEXT NOT NULL,         -- e.g., "Basic Video Playback"
    category VARCHAR(50),                   -- e.g., "playback", "auth", "navigation", "settings"
    priority VARCHAR(10),                   -- e.g., "P1" (Critical), "P2" (High), "P3" (Medium)
    
    -- Requirement details
    description TEXT,                       -- Full requirement description
    acceptance_criteria JSONB,              -- Array of acceptance criteria
    
    -- Categorization
    app_type VARCHAR(50),                   -- e.g., "streaming", "social", "news", "all"
    device_model VARCHAR(50),               -- e.g., "android_mobile", "android_tv", "web", "all"
    
    -- Lifecycle
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'deprecated', 'draft')),
    source_document VARCHAR(255),           -- Link to original requirement spec/doc
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255),
    
    -- Unique constraint: One requirement code per team
    CONSTRAINT unique_requirement_per_team UNIQUE (team_id, requirement_code)
);

-- Indexes for performance
CREATE INDEX idx_requirements_team ON requirements(team_id);
CREATE INDEX idx_requirements_code ON requirements(requirement_code);
CREATE INDEX idx_requirements_category ON requirements(category);
CREATE INDEX idx_requirements_priority ON requirements(priority);
CREATE INDEX idx_requirements_app_type ON requirements(app_type);
CREATE INDEX idx_requirements_device_model ON requirements(device_model);
CREATE INDEX idx_requirements_status ON requirements(status);

-- Updated timestamp trigger
CREATE OR REPLACE FUNCTION update_requirements_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER requirements_updated_at
    BEFORE UPDATE ON requirements
    FOR EACH ROW
    EXECUTE FUNCTION update_requirements_updated_at();

-- Comments
COMMENT ON TABLE requirements IS 'Requirements management for testcase and script coverage tracking';
COMMENT ON COLUMN requirements.requirement_code IS 'Unique requirement identifier (e.g., REQ_PLAYBACK_001)';
COMMENT ON COLUMN requirements.acceptance_criteria IS 'JSON array of acceptance criteria strings';
COMMENT ON COLUMN requirements.app_type IS 'Target application type - use "all" for generic requirements';
COMMENT ON COLUMN requirements.device_model IS 'Target device model - use "all" for cross-platform requirements';
COMMENT ON COLUMN requirements.status IS 'Lifecycle status: active (current), deprecated (obsolete), draft (pending)';

-- ================================================
-- 2. TestCase Requirements Junction Table
-- ================================================

CREATE TABLE IF NOT EXISTS testcase_requirements (
    id SERIAL PRIMARY KEY,
    testcase_id UUID NOT NULL REFERENCES testcase_definitions(testcase_id) ON DELETE CASCADE,
    requirement_id UUID NOT NULL REFERENCES requirements(requirement_id) ON DELETE CASCADE,
    
    -- Coverage metadata
    coverage_type VARCHAR(20) DEFAULT 'full' CHECK (coverage_type IN ('full', 'partial', 'negative')),
    coverage_notes TEXT,  -- Optional notes about coverage (e.g., "Only tests happy path")
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255),
    
    -- Unique constraint: One testcase can't link to same requirement twice
    CONSTRAINT unique_testcase_requirement UNIQUE (testcase_id, requirement_id)
);

-- Indexes
CREATE INDEX idx_testcase_req_testcase ON testcase_requirements(testcase_id);
CREATE INDEX idx_testcase_req_requirement ON testcase_requirements(requirement_id);

-- Comments
COMMENT ON TABLE testcase_requirements IS 'Links testcases to requirements for coverage tracking';
COMMENT ON COLUMN testcase_requirements.coverage_type IS 'full: complete coverage, partial: incomplete, negative: tests failure scenarios';
COMMENT ON COLUMN testcase_requirements.coverage_notes IS 'Optional notes about what aspects are covered';

-- ================================================
-- 3. Script Requirements Junction Table
-- ================================================

CREATE TABLE IF NOT EXISTS script_requirements (
    id SERIAL PRIMARY KEY,
    script_name VARCHAR(255) NOT NULL,  -- Links to scripts.name or direct script file
    requirement_id UUID NOT NULL REFERENCES requirements(requirement_id) ON DELETE CASCADE,
    
    -- Coverage metadata
    coverage_type VARCHAR(20) DEFAULT 'full' CHECK (coverage_type IN ('full', 'partial', 'negative')),
    coverage_notes TEXT,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255),
    
    -- Unique constraint: One script can't link to same requirement twice
    CONSTRAINT unique_script_requirement UNIQUE (script_name, requirement_id)
);

-- Indexes
CREATE INDEX idx_script_req_script ON script_requirements(script_name);
CREATE INDEX idx_script_req_requirement ON script_requirements(requirement_id);

-- Comments
COMMENT ON TABLE script_requirements IS 'Links Python scripts to requirements for coverage tracking';
COMMENT ON COLUMN script_requirements.script_name IS 'Script filename (e.g., device_get_info.py) - links to scripts table or direct file';

-- ================================================
-- Row Level Security (RLS)
-- ================================================

-- Enable RLS on all tables
ALTER TABLE requirements ENABLE ROW LEVEL SECURITY;
ALTER TABLE testcase_requirements ENABLE ROW LEVEL SECURITY;
ALTER TABLE script_requirements ENABLE ROW LEVEL SECURITY;

-- Requirements policies (same pattern as testcase_definitions)
CREATE POLICY "service_role_all_requirements"
ON requirements
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

CREATE POLICY "requirements_access_policy"
ON requirements
FOR ALL
TO public
USING (true);

-- TestCase Requirements policies (same pattern)
CREATE POLICY "service_role_all_testcase_requirements"
ON testcase_requirements
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

CREATE POLICY "testcase_requirements_access_policy"
ON testcase_requirements
FOR ALL
TO public
USING (true);

-- Script Requirements policies (same pattern)
CREATE POLICY "service_role_all_script_requirements"
ON script_requirements
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

CREATE POLICY "script_requirements_access_policy"
ON script_requirements
FOR ALL
TO public
USING (true);

-- ================================================
-- Helper Views for Coverage Reporting
-- ================================================

-- View 1: Requirements with coverage counts
CREATE OR REPLACE VIEW requirements_coverage_summary
WITH (security_invoker = true) AS
SELECT
    r.requirement_id,
    r.team_id,
    r.requirement_code,
    r.requirement_name,
    r.category,
    r.priority,
    r.status,
    r.app_type,
    r.device_model,
    COUNT(DISTINCT tr.testcase_id) AS testcase_count,
    COUNT(DISTINCT sr.script_name) AS script_count,
    (COUNT(DISTINCT tr.testcase_id) + COUNT(DISTINCT sr.script_name)) AS total_coverage_count
FROM requirements r
LEFT JOIN testcase_requirements tr ON r.requirement_id = tr.requirement_id
LEFT JOIN script_requirements sr ON r.requirement_id = sr.requirement_id
GROUP BY r.requirement_id, r.team_id, r.requirement_code, r.requirement_name,
         r.category, r.priority, r.status, r.app_type, r.device_model;

COMMENT ON VIEW requirements_coverage_summary IS 'Summary view showing requirement coverage counts';

-- View 2: Uncovered requirements
CREATE OR REPLACE VIEW uncovered_requirements
WITH (security_invoker = true) AS
SELECT
    r.*
FROM requirements r
LEFT JOIN testcase_requirements tr ON r.requirement_id = tr.requirement_id
LEFT JOIN script_requirements sr ON r.requirement_id = sr.requirement_id
WHERE r.status = 'active'
  AND tr.id IS NULL
  AND sr.id IS NULL;

COMMENT ON VIEW uncovered_requirements IS 'Active requirements with no testcase or script coverage';

-- ================================================
-- Sample Data (Optional - for testing)
-- ================================================

-- Example requirements for streaming apps
-- Uncomment to populate with sample data

/*
-- Sample requirements for streaming app
INSERT INTO requirements (team_id, requirement_code, requirement_name, category, priority, description, app_type, device_model, status) VALUES
('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'REQ_PLAYBACK_001', 'Basic Video Playback', 'playback', 'P1', 'User can play video content from content detail screen', 'streaming', 'all', 'active'),
('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'REQ_PLAYBACK_002', 'Pause and Resume', 'playback', 'P1', 'User can pause and resume video playback', 'streaming', 'all', 'active'),
('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'REQ_PLAYBACK_003', 'Skip Forward/Backward', 'playback', 'P2', 'User can skip video timeline forward and backward', 'streaming', 'all', 'active'),
('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'REQ_AUTH_001', 'User Login', 'authentication', 'P1', 'User can log in with valid credentials', 'all', 'all', 'active'),
('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'REQ_AUTH_002', 'User Logout', 'authentication', 'P1', 'User can log out from profile screen', 'all', 'all', 'active'),
('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'REQ_NAV_001', 'Navigate to Home', 'navigation', 'P1', 'User can navigate to home screen', 'all', 'all', 'active'),
('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'REQ_NAV_002', 'Navigate to Search', 'navigation', 'P1', 'User can navigate to search screen', 'all', 'all', 'active'),
('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'REQ_SETTINGS_001', 'Change Video Quality', 'settings', 'P2', 'User can change video quality in settings', 'streaming', 'all', 'active'),
('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'REQ_SETTINGS_002', 'Enable Subtitles', 'settings', 'P2', 'User can enable/disable subtitles in player settings', 'streaming', 'all', 'active'),
('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'REQ_DEVICE_001', 'Extract Device Info', 'device_management', 'P2', 'System can extract and store device information', 'all', 'all', 'active');
*/

