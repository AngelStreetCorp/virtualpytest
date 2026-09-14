-- ============================================================================
-- Migration: Fix get_full_tree_from_mv return type
-- ============================================================================
-- Date: 2025-11-17
-- 
-- Problem:
--   The function currently RETURNS JSON (single object), but Supabase Python
--   client expects RPC functions to return SETOF JSON (array of objects).
--   This causes Pydantic validation error:
--   "Input should be a valid list [type=list_type, input_value={...}, input_type=dict]"
--
-- Solution:
--   Change RETURNS JSON to RETURNS SETOF JSON
--   This makes the function return an array with one element instead of a bare object
--
-- Impact:
--   - Frontend/Backend code already handles both formats (checks if array or object)
--   - Performance: No change (still ~10ms reads from materialized view)
--   - Breaking change: None (code is defensive and handles both cases)
-- ============================================================================

-- Drop existing function
DROP FUNCTION IF EXISTS public.get_full_tree_from_mv(UUID, UUID);

-- Recreate with correct return type
CREATE OR REPLACE FUNCTION public.get_full_tree_from_mv(
    p_tree_id UUID,
    p_team_id UUID
)
RETURNS SETOF JSON  -- Changed from RETURNS JSON to RETURNS SETOF JSON
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT full_tree_data
    FROM public.mv_full_navigation_trees
    WHERE tree_id = p_tree_id
    AND team_id = p_team_id;
$$;

COMMENT ON FUNCTION public.get_full_tree_from_mv(UUID, UUID) IS 
'Read pre-computed tree data from materialized view. 
Returns SETOF JSON (array) for compatibility with Supabase client.
Extremely fast (~10ms) because data is pre-aggregated.
Uses fully qualified table names to work with empty search_path security setting.';

-- Grant permissions
GRANT EXECUTE ON FUNCTION public.get_full_tree_from_mv(UUID, UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_full_tree_from_mv(UUID, UUID) TO service_role;

-- ============================================================================
-- Verification Query (run after migration to test)
-- ============================================================================
-- SELECT get_full_tree_from_mv(
--     'a1e05da1-ec92-4cd4-9162-dd1c60334857'::uuid,
--     '7fdeb4bb-3639-4ec3-959f-b54769a219ce'::uuid
-- );
-- 
-- Expected: Should return array with one JSON object
-- ============================================================================

