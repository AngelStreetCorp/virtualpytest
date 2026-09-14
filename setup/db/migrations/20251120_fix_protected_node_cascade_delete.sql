-- Migration: Fix protected node and edge deletion to allow CASCADE deletes
-- Date: 2025-11-20
-- Issue: Protected nodes (entry-node) and edges block CASCADE delete when deleting userinterface/tree
-- Solution: Modify triggers to allow deletion when parent tree is being deleted (CASCADE context)

-- Drop existing trigger function
DROP TRIGGER IF EXISTS trigger_prevent_protected_node_deletion ON navigation_nodes;
DROP FUNCTION IF EXISTS prevent_protected_node_deletion();

-- Recreate function that allows CASCADE deletes
CREATE OR REPLACE FUNCTION prevent_protected_node_deletion()
RETURNS TRIGGER AS $$
DECLARE
    tree_exists BOOLEAN;
BEGIN
    -- Only enforce protection if this is a direct delete, not a CASCADE delete
    -- Check if the parent tree still exists - if not, this is a CASCADE delete
    SELECT EXISTS(
        SELECT 1 FROM navigation_trees WHERE id = OLD.tree_id
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
$$ LANGUAGE plpgsql;

-- Recreate trigger
CREATE TRIGGER trigger_prevent_protected_node_deletion
    BEFORE DELETE ON navigation_nodes
    FOR EACH ROW
    EXECUTE FUNCTION prevent_protected_node_deletion();

-- ========================================
-- FIX PROTECTED EDGE DELETION
-- ========================================

-- Drop existing edge trigger function
DROP TRIGGER IF EXISTS trigger_prevent_protected_edge_deletion ON navigation_edges;
DROP FUNCTION IF EXISTS prevent_protected_edge_deletion();

-- Recreate function that allows CASCADE deletes for edges
CREATE OR REPLACE FUNCTION prevent_protected_edge_deletion()
RETURNS TRIGGER AS $$
DECLARE
    tree_exists BOOLEAN;
BEGIN
    -- Only enforce protection if this is a direct delete, not a CASCADE delete
    -- Check if the parent tree still exists - if not, this is a CASCADE delete
    SELECT EXISTS(
        SELECT 1 FROM navigation_trees WHERE id = OLD.tree_id
    ) INTO tree_exists;
    
    -- If tree exists and edge is protected, this is a direct delete - block it
    IF tree_exists AND OLD.is_system_protected = true THEN
        RAISE EXCEPTION 'Cannot delete system-protected edge: % (edge_id: %)', OLD.label, OLD.edge_id
            USING HINT = 'This edge is essential for navigation tree structure and cannot be deleted.';
    END IF;
    
    -- Otherwise allow deletion (CASCADE or unprotected edge)
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- Recreate trigger for edges
CREATE TRIGGER trigger_prevent_protected_edge_deletion
    BEFORE DELETE ON navigation_edges
    FOR EACH ROW
    EXECUTE FUNCTION prevent_protected_edge_deletion();

-- Test: Verify the triggers exist
SELECT 
    trigger_name,
    event_manipulation,
    event_object_table,
    action_timing,
    action_statement
FROM information_schema.triggers
WHERE trigger_name IN ('trigger_prevent_protected_node_deletion', 'trigger_prevent_protected_edge_deletion')
ORDER BY trigger_name;

