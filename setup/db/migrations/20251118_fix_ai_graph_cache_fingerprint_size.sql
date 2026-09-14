-- ============================================================================
-- Migration: Fix ai_graph_cache fingerprint column size for SHA-256 hashes
-- ============================================================================
-- Date: 2025-11-18
-- 
-- Purpose:
--   Increase fingerprint column size from VARCHAR(32) to VARCHAR(64) to
--   support SHA-256 hashes instead of MD5.
--
-- Problem Solved:
--   Code uses SHA-256 (64 chars) but database column was VARCHAR(32),
--   causing "value too long for type character varying(32)" errors.
--   This prevented graph caching from working, forcing redundant AI calls.
--
-- Impact:
--   - Fixes graph caching storage failures
--   - Reduces AI API calls by enabling cache hits
--   - Improves performance and reduces costs
--   - Uses more secure SHA-256 instead of MD5
-- ============================================================================

-- Alter the fingerprint column to support SHA-256 (64 characters)
ALTER TABLE ai_graph_cache 
ALTER COLUMN fingerprint TYPE VARCHAR(64);

-- Update the function signature to match new fingerprint size
DROP FUNCTION IF EXISTS update_ai_graph_metrics(VARCHAR(32), BOOLEAN, INTEGER, UUID);

CREATE OR REPLACE FUNCTION update_ai_graph_metrics(
    p_fingerprint VARCHAR(64),  -- Changed from VARCHAR(32) to VARCHAR(64)
    p_success BOOLEAN,
    p_execution_time_ms INTEGER,
    p_team_id UUID
) RETURNS VOID AS $$
BEGIN
    UPDATE ai_graph_cache 
    SET 
        execution_count = execution_count + 1,
        success_count = CASE WHEN p_success THEN success_count + 1 ELSE success_count END,
        success_rate = (CASE WHEN p_success THEN success_count + 1 ELSE success_count END)::DECIMAL / (execution_count + 1),
        last_used = NOW()
    WHERE fingerprint = p_fingerprint AND team_id = p_team_id;
END;
$$ LANGUAGE plpgsql;

-- Update table comment to reflect SHA-256 usage
COMMENT ON COLUMN ai_graph_cache.fingerprint IS 'SHA-256 hash (64 chars) of normalized prompt + context signature for fast lookups';

-- Grant necessary permissions (ensure they're still set)
GRANT EXECUTE ON FUNCTION update_ai_graph_metrics TO authenticated;

-- ============================================================================
-- Verification Query (run after migration to test)
-- ============================================================================
-- Check that the column type was updated correctly:
-- SELECT column_name, data_type, character_maximum_length 
-- FROM information_schema.columns 
-- WHERE table_name = 'ai_graph_cache' AND column_name = 'fingerprint';
-- 
-- Expected result:
--   column_name: fingerprint
--   data_type: character varying
--   character_maximum_length: 64
-- ============================================================================

