-- 027_library_visibility.sql
-- Unified visibility controls for scripts, testcases, and campaigns.
-- Hidden items get an explicit row; missing row means visible by default.

CREATE TABLE library_visibility (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    entity_type VARCHAR(32) NOT NULL,
    entity_key TEXT NOT NULL,
    is_visible BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(255),

    CONSTRAINT library_visibility_entity_type_check
        CHECK (entity_type IN ('script', 'testcase', 'campaign')),
    CONSTRAINT unique_library_visibility_per_team
        UNIQUE (team_id, entity_type, entity_key)
);

CREATE INDEX idx_library_visibility_team_type
    ON library_visibility(team_id, entity_type);

CREATE INDEX idx_library_visibility_team_visible
    ON library_visibility(team_id, is_visible);

CREATE INDEX idx_library_visibility_entity_lookup
    ON library_visibility(team_id, entity_type, entity_key);

COMMENT ON TABLE library_visibility IS 'Team-scoped visibility overrides for scripts, testcases, and campaigns';
COMMENT ON COLUMN library_visibility.entity_type IS 'One of: script, testcase, campaign';
COMMENT ON COLUMN library_visibility.entity_key IS 'Stable executable identifier (script path, testcase_id, or campaign_id/path)';
COMMENT ON COLUMN library_visibility.is_visible IS 'Hidden items are stored with false; missing row means visible by default';

ALTER TABLE library_visibility ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_library_visibility"
ON library_visibility
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

CREATE POLICY "library_visibility_access_policy"
ON library_visibility
FOR ALL
TO public
USING (true);
