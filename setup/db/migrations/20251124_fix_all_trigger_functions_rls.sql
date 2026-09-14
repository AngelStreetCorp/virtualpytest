-- Migration: Fix ALL trigger functions to bypass RLS
-- Date: 2025-11-24
-- Issue: Multiple trigger functions access navigation_trees but lack SECURITY DEFINER
--        causing "relation navigation_trees does not exist" errors when using ANON_KEY
-- Solution: Add SECURITY DEFINER to ALL trigger functions that access navigation_trees
-- Reference: commit a4c56652ef158f2a6475523563116cb7ee28d287

-- ============================================================================
-- Fix update_node_subtree_counts (triggered on navigation_trees INSERT/DELETE)
-- ============================================================================

CREATE OR REPLACE FUNCTION update_node_subtree_counts()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- ✅ Run with postgres privileges to bypass RLS
SET search_path TO public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Update parent node's subtree information
        UPDATE public.navigation_nodes 
        SET 
            has_subtree = true,
            subtree_count = (
                SELECT COUNT(*) 
                FROM public.navigation_trees 
                WHERE parent_tree_id = NEW.parent_tree_id 
                AND parent_node_id = NEW.parent_node_id
            )
        WHERE tree_id = NEW.parent_tree_id 
        AND node_id = NEW.parent_node_id;
        
        RETURN NEW;
    END IF;
    
    IF TG_OP = 'DELETE' THEN
        -- Update parent node's subtree information
        UPDATE public.navigation_nodes 
        SET 
            subtree_count = (
                SELECT COUNT(*) 
                FROM public.navigation_trees 
                WHERE parent_tree_id = OLD.parent_tree_id 
                AND parent_node_id = OLD.parent_node_id
            )
        WHERE tree_id = OLD.parent_tree_id 
        AND node_id = OLD.parent_node_id;
        
        -- If no more subtrees, set has_subtree to false
        UPDATE public.navigation_nodes 
        SET has_subtree = false
        WHERE tree_id = OLD.parent_tree_id 
        AND node_id = OLD.parent_node_id
        AND subtree_count = 0;
        
        RETURN OLD;
    END IF;
    
    RETURN NULL;
END;
$$;

-- ============================================================================
-- Fix sync_parent_label_screenshot (triggered on navigation_nodes UPDATE)
-- ============================================================================

CREATE OR REPLACE FUNCTION sync_parent_label_screenshot()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- ✅ Run with postgres privileges to bypass RLS
SET search_path TO public, pg_temp
AS $$
BEGIN
    -- Only sync if this node is referenced as a parent by subtrees
    IF EXISTS(
        SELECT 1 FROM public.navigation_trees 
        WHERE parent_node_id = NEW.node_id 
        AND team_id = NEW.team_id
    ) THEN
        -- Update label and screenshot in all subtree duplicates
        UPDATE public.navigation_nodes 
        SET 
            label = NEW.label,
            data = jsonb_set(
                COALESCE(data, '{}'), 
                '{screenshot}', 
                to_jsonb(NEW.data->>'screenshot')
            ),
            updated_at = NOW()
        WHERE 
            node_id = NEW.node_id
            AND team_id = NEW.team_id
            AND tree_id IN (
                SELECT id FROM public.navigation_trees 
                WHERE parent_node_id = NEW.node_id 
                AND team_id = NEW.team_id
            );
    END IF;
    
    RETURN NEW;
END;
$$;

-- ============================================================================
-- Fix cascade_delete_subtrees (triggered on navigation_nodes DELETE)
-- ============================================================================

CREATE OR REPLACE FUNCTION cascade_delete_subtrees()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- ✅ Run with postgres privileges to bypass RLS
SET search_path TO public, pg_temp
AS $$
BEGIN
    -- When a parent node is deleted, delete all its subtrees
    DELETE FROM public.navigation_trees 
    WHERE parent_node_id = OLD.node_id 
    AND team_id = OLD.team_id;
    
    RETURN OLD;
END;
$$;

-- ============================================================================
-- Fix refresh_tree_materialized_view (triggered on all table changes)
-- ============================================================================

CREATE OR REPLACE FUNCTION refresh_tree_materialized_view()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- ✅ Run with postgres privileges to bypass RLS
SET search_path TO public, pg_temp
AS $$
BEGIN
    -- Refresh only the affected tree (CONCURRENTLY for non-blocking updates)
    -- Note: REFRESH MATERIALIZED VIEW CONCURRENTLY requires unique index
    IF TG_OP = 'DELETE' THEN
        -- For DELETE operations, use OLD
        REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_full_navigation_trees;
        RETURN OLD;
    ELSE
        -- For INSERT/UPDATE operations, use NEW
        REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_full_navigation_trees;
        RETURN NEW;
    END IF;
END;
$$;

-- ============================================================================
-- Fix auto_set_edge_label_on_insert (BEFORE INSERT on navigation_edges)
-- ============================================================================

CREATE OR REPLACE FUNCTION auto_set_edge_label_on_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- ✅ Run with postgres privileges to bypass RLS
SET search_path TO public, pg_temp
AS $$
BEGIN
    -- Set the label for the new edge if it's not already set
    IF NEW.label IS NULL OR NEW.label = '' THEN
        SELECT source_node.label || '→' || target_node.label INTO NEW.label
        FROM public.navigation_nodes source_node, public.navigation_nodes target_node
        WHERE NEW.tree_id = source_node.tree_id 
          AND NEW.source_node_id = source_node.node_id
          AND NEW.tree_id = target_node.tree_id 
          AND NEW.target_node_id = target_node.node_id;
    END IF;
    
    RETURN NEW;
END;
$$;

-- ============================================================================
-- Fix auto_update_edge_labels_on_node_change (AFTER INSERT/UPDATE on navigation_nodes)
-- ============================================================================

CREATE OR REPLACE FUNCTION auto_update_edge_labels_on_node_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- ✅ Run with postgres privileges to bypass RLS
SET search_path TO public, pg_temp
AS $$
BEGIN
    -- Update all edges where this node is the source
    UPDATE public.navigation_edges 
    SET label = NEW.label || '→' || target_node.label,
        updated_at = now()
    FROM public.navigation_nodes target_node
    WHERE navigation_edges.tree_id = NEW.tree_id 
      AND navigation_edges.source_node_id = NEW.node_id
      AND navigation_edges.tree_id = target_node.tree_id 
      AND navigation_edges.target_node_id = target_node.node_id;
    
    -- Update all edges where this node is the target
    UPDATE public.navigation_edges 
    SET label = source_node.label || '→' || NEW.label,
        updated_at = now()
    FROM public.navigation_nodes source_node
    WHERE navigation_edges.tree_id = NEW.tree_id 
      AND navigation_edges.target_node_id = NEW.node_id
      AND navigation_edges.tree_id = source_node.tree_id 
      AND navigation_edges.source_node_id = source_node.node_id;
    
    RETURN NEW;
END;
$$;

-- ============================================================================
-- Verification
-- ============================================================================

-- Verify all functions now have SECURITY DEFINER
DO $$
DECLARE
    funcs_without_sec_def TEXT[];
BEGIN
    -- Get list of functions that should have SECURITY DEFINER but don't
    SELECT array_agg(proname)
    INTO funcs_without_sec_def
    FROM pg_proc
    WHERE proname IN (
        'update_node_subtree_counts',
        'sync_parent_label_screenshot',
        'cascade_delete_subtrees',
        'refresh_tree_materialized_view',
        'auto_set_edge_label_on_insert',
        'auto_update_edge_labels_on_node_change',
        'prevent_protected_node_deletion',
        'prevent_protected_edge_deletion'
    )
    AND prosecdef = false;
    
    IF array_length(funcs_without_sec_def, 1) > 0 THEN
        RAISE EXCEPTION 'Functions missing SECURITY DEFINER: %', funcs_without_sec_def;
    END IF;
    
    RAISE NOTICE '✅ Migration successful: All trigger functions now have SECURITY DEFINER';
    RAISE NOTICE '   - update_node_subtree_counts';
    RAISE NOTICE '   - sync_parent_label_screenshot';
    RAISE NOTICE '   - cascade_delete_subtrees';
    RAISE NOTICE '   - refresh_tree_materialized_view';
    RAISE NOTICE '   - auto_set_edge_label_on_insert';
    RAISE NOTICE '   - auto_update_edge_labels_on_node_change';
    RAISE NOTICE '   - prevent_protected_node_deletion (already fixed)';
    RAISE NOTICE '   - prevent_protected_edge_deletion (already fixed)';
END;
$$;

