-- Add logs_r2_path and logs_r2_url columns to campaign_executions
-- These columns store the orchestrator logs artifact URLs (matching script_results pattern)
ALTER TABLE campaign_executions ADD COLUMN IF NOT EXISTS logs_r2_path text;
ALTER TABLE campaign_executions ADD COLUMN IF NOT EXISTS logs_r2_url text;
