-- 032_campaigns_history.sql
-- Campaign definition version snapshots
-- Stores full snapshots of the live campaign definition on create/update/restore

CREATE TABLE IF NOT EXISTS campaigns_history (
    history_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    campaign_name VARCHAR(255) NOT NULL,
    modification_type VARCHAR(20) NOT NULL CHECK (modification_type IN ('create', 'update', 'restore')),
    modified_by VARCHAR(255),
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    changes_summary TEXT,
    restored_from_version INTEGER,
    campaign_data JSONB NOT NULL,

    CONSTRAINT unique_campaign_history_version UNIQUE (campaign_id, version_number)
);

CREATE INDEX idx_campaigns_history_campaign_id ON campaigns_history(campaign_id);
CREATE INDEX idx_campaigns_history_team_id ON campaigns_history(team_id);
CREATE INDEX idx_campaigns_history_version ON campaigns_history(campaign_id, version_number DESC);

ALTER TABLE campaigns_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY service_role_all_campaigns_history ON campaigns_history
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY campaigns_history_access_policy ON campaigns_history
  FOR ALL
  TO public
  USING (true);

COMMENT ON TABLE campaigns_history IS 'Version snapshots for campaign definitions';
