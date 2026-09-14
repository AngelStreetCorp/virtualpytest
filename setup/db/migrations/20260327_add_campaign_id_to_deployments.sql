-- Add campaign_id column to deployments table
-- Allows reliable distinction between test deployments and campaign deployments
-- NULL means test deployment, non-NULL means campaign deployment

ALTER TABLE deployments ADD COLUMN IF NOT EXISTS campaign_id TEXT;

COMMENT ON COLUMN deployments.campaign_id IS 'Campaign ID if this deployment runs a campaign (NULL for test deployments)';
