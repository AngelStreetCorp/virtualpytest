-- Migration: Add missing columns to zap_results table
-- Date: 2025-12-15
-- Description: Add action_params, time_since_action_ms, and total_zap_duration_ms columns to zap_results table

-- ==================================================
-- ADD MISSING COLUMNS TO ZAP_RESULTS TABLE
-- ==================================================

-- Add action_params column to store action parameters (e.g., {"key": "CHANNEL_UP"})
ALTER TABLE zap_results ADD COLUMN IF NOT EXISTS action_params jsonb;

-- Add time_since_action_ms column to track time from action to blackscreen end
ALTER TABLE zap_results ADD COLUMN IF NOT EXISTS time_since_action_ms integer;

-- Add total_zap_duration_ms column to track total zap duration
ALTER TABLE zap_results ADD COLUMN IF NOT EXISTS total_zap_duration_ms integer;

-- ==================================================
-- ADD INDEXES FOR NEW COLUMNS
-- ==================================================

-- Index for action_params (useful for filtering by specific action types)
CREATE INDEX IF NOT EXISTS idx_zap_results_action_params ON zap_results USING gin(action_params);

-- Index for time_since_action_ms (useful for performance analysis)
CREATE INDEX IF NOT EXISTS idx_zap_results_time_since_action_ms ON zap_results(time_since_action_ms);

-- Index for total_zap_duration_ms (useful for duration-based queries)
CREATE INDEX IF NOT EXISTS idx_zap_results_total_zap_duration_ms ON zap_results(total_zap_duration_ms);

-- ==================================================
-- ADD COMMENTS FOR NEW COLUMNS
-- ==================================================

COMMENT ON COLUMN zap_results.action_params IS 'Action parameters for the zap iteration (e.g., {"key": "CHANNEL_UP"})';
COMMENT ON COLUMN zap_results.time_since_action_ms IS 'Time in milliseconds from action execution to blackscreen end';
COMMENT ON COLUMN zap_results.total_zap_duration_ms IS 'Total zap duration in milliseconds (action start to completion)';

-- ==================================================
-- VERIFICATION QUERIES
-- ==================================================

-- Check that columns were added successfully
DO $$
BEGIN
    RAISE NOTICE 'Migration completed successfully';
    RAISE NOTICE 'Added columns: action_params, time_since_action_ms, total_zap_duration_ms';
    RAISE NOTICE 'Added indexes for performance optimization';

    -- Verify columns exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'zap_results' AND column_name = 'action_params'
    ) THEN
        RAISE EXCEPTION 'action_params column was not added';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'zap_results' AND column_name = 'time_since_action_ms'
    ) THEN
        RAISE EXCEPTION 'time_since_action_ms column was not added';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'zap_results' AND column_name = 'total_zap_duration_ms'
    ) THEN
        RAISE EXCEPTION 'total_zap_duration_ms column was not added';
    END IF;

END $$;
