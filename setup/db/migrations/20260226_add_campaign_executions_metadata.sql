-- Add metadata support for campaign identity mapping (prefix/display_name).
-- Safe to run multiple times.

ALTER TABLE IF EXISTS campaign_executions
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

UPDATE campaign_executions
SET metadata = '{}'::jsonb
WHERE metadata IS NULL;
