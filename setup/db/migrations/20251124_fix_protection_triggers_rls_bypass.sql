-- Migration: Fix protection trigger functions to bypass RLS
-- Date: 2025-11-24
-- Issue: prevent_protected_edge_deletion and prevent_protected_node_deletion
--        were failing with "relation navigation_trees does not exist" when
--        using ANON_KEY due to RLS policies blocking trigger access
-- Solution: Add SECURITY DEFINER to run triggers with postgres privileges

-- ============================================================================
-- Fix prevent_protected_node_deletion trigger function
-- ============================================================================

CREATE OR REPLACE FUNCTION public.prevent_protected_node_deletion()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- ✅ Run with postgres privileges to bypass RLS
AS $$
DECLARE
    tree_exists BOOLEAN;
BEGIN
    -- Only enforce protection if this is a direct delete, not a CASCADE delete
    -- Check if the parent tree still exists - if not, this is a CASCADE delete
    SELECT EXISTS(
        SELECT 1 FROM public.navigation_trees WHERE id = OLD.tree_id  -- ✅ Explicit schema qualification
    ) INTO tree_exists;
    
    -- If tree exists and node is protected, this is a direct delete - block it
    -- Protect: 1) system-protected flag, 2) entry-node, 3) home
    IF tree_exists AND (OLD.is_system_protected = true OR OLD.node_id IN ('entry-node', 'home')) THEN
        RAISE EXCEPTION 'Cannot delete system-protected node: % (node_id: %)', OLD.label, OLD.node_id
            USING HINT = 'This node is essential for navigation tree structure and cannot be deleted.';
    END IF;
    
    -- Otherwise allow deletion (CASCADE or unprotected node)
    RETURN OLD;
END;
$$;

-- ============================================================================
-- Fix prevent_protected_edge_deletion trigger function
-- ============================================================================

CREATE OR REPLACE FUNCTION public.prevent_protected_edge_deletion()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- ✅ Run with postgres privileges to bypass RLS
AS $$
DECLARE
    tree_exists BOOLEAN;
BEGIN
    -- Only enforce protection if this is a direct delete, not a CASCADE delete
    -- Check if the parent tree still exists - if not, this is a CASCADE delete
    SELECT EXISTS(
        SELECT 1 FROM public.navigation_trees WHERE id = OLD.tree_id  -- ✅ Explicit schema qualification
    ) INTO tree_exists;
    
    -- If tree exists and edge is protected, this is a direct delete - block it
    IF tree_exists AND OLD.is_system_protected = true THEN
        RAISE EXCEPTION 'Cannot delete system-protected edge: % (edge_id: %)', OLD.label, OLD.edge_id
            USING HINT = 'This edge is essential for navigation tree structure and cannot be deleted.';
    END IF;
    
    -- Otherwise allow deletion (CASCADE or unprotected edge)
    RETURN OLD;
END;
$$;

-- ============================================================================
-- Verification
-- ============================================================================

-- Verify both functions now have SECURITY DEFINER
DO $$
DECLARE
    edge_func_sec_def BOOLEAN;
    node_func_sec_def BOOLEAN;
BEGIN
    -- Check prevent_protected_edge_deletion
    SELECT prosecdef INTO edge_func_sec_def
    FROM pg_proc
    WHERE proname = 'prevent_protected_edge_deletion';
    
    -- Check prevent_protected_node_deletion
    SELECT prosecdef INTO node_func_sec_def
    FROM pg_proc
    WHERE proname = 'prevent_protected_node_deletion';
    
    IF NOT edge_func_sec_def THEN
        RAISE EXCEPTION 'prevent_protected_edge_deletion is not SECURITY DEFINER!';
    END IF;
    
    IF NOT node_func_sec_def THEN
        RAISE EXCEPTION 'prevent_protected_node_deletion is not SECURITY DEFINER!';
    END IF;
    
    RAISE NOTICE '✅ Migration successful: Both protection functions now have SECURITY DEFINER';
    RAISE NOTICE '   - prevent_protected_edge_deletion: SECURITY DEFINER = %', edge_func_sec_def;
    RAISE NOTICE '   - prevent_protected_node_deletion: SECURITY DEFINER = %', node_func_sec_def;
END;
$$;

