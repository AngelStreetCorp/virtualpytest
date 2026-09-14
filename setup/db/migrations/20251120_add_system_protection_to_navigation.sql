-- Migration: Add system protection flags to navigation nodes and edges
-- Purpose: Protect essential nodes (entry-node, home) and edges (entry→home) from deletion/editing
-- Date: 2025-11-20
--
-- PROTECTION RULES:
-- - entry-node: Cannot be edited, deleted, or updated
-- - home: Cannot be deleted, but CAN be updated
-- - edge-entry-node-to-home: Cannot be deleted, but CAN be updated
--

-- ========================================
-- 1. Add protection columns to navigation_nodes
-- ========================================
DO $$ 
BEGIN
    -- Add is_system_protected column (prevents deletion)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'navigation_nodes' 
        AND column_name = 'is_system_protected'
    ) THEN
        ALTER TABLE navigation_nodes 
        ADD COLUMN is_system_protected boolean DEFAULT false NOT NULL;
        
        RAISE NOTICE 'Added is_system_protected column to navigation_nodes table';
    ELSE
        RAISE NOTICE 'Column is_system_protected already exists in navigation_nodes table';
    END IF;
    
    -- Add is_read_only column (prevents any updates - stricter than is_system_protected)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'navigation_nodes' 
        AND column_name = 'is_read_only'
    ) THEN
        ALTER TABLE navigation_nodes 
        ADD COLUMN is_read_only boolean DEFAULT false NOT NULL;
        
        RAISE NOTICE 'Added is_read_only column to navigation_nodes table';
    ELSE
        RAISE NOTICE 'Column is_read_only already exists in navigation_nodes table';
    END IF;
END $$;

-- ========================================
-- 2. Add protection column to navigation_edges
-- ========================================
DO $$ 
BEGIN
    -- Add is_system_protected column (prevents deletion, but allows updates)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'navigation_edges' 
        AND column_name = 'is_system_protected'
    ) THEN
        ALTER TABLE navigation_edges 
        ADD COLUMN is_system_protected boolean DEFAULT false NOT NULL;
        
        RAISE NOTICE 'Added is_system_protected column to navigation_edges table';
    ELSE
        RAISE NOTICE 'Column is_system_protected already exists in navigation_edges table';
    END IF;
END $$;

-- ========================================
-- 3. Mark existing essential nodes as protected
-- ========================================

-- Protect entry-node: READ-ONLY (cannot delete, cannot update)
UPDATE navigation_nodes 
SET 
    is_system_protected = true,
    is_read_only = true
WHERE node_id = 'entry-node';

-- Protect home: SYSTEM-PROTECTED (cannot delete, CAN update)
UPDATE navigation_nodes 
SET 
    is_system_protected = true,
    is_read_only = false
WHERE node_id = 'home';

-- ========================================
-- 4. Mark existing essential edges as protected
-- ========================================

-- Protect entry→home edge: SYSTEM-PROTECTED (cannot delete, CAN update)
UPDATE navigation_edges 
SET is_system_protected = true
WHERE edge_id = 'edge-entry-node-to-home';

-- ========================================
-- 5. Add comments explaining the columns
-- ========================================

COMMENT ON COLUMN navigation_nodes.is_system_protected IS 
'Flag indicating if this node cannot be deleted (but may be updated unless is_read_only=true)';

COMMENT ON COLUMN navigation_nodes.is_read_only IS 
'Flag indicating if this node is completely read-only (cannot be updated or deleted). Stricter than is_system_protected.';

COMMENT ON COLUMN navigation_edges.is_system_protected IS 
'Flag indicating if this edge cannot be deleted (but may be updated via action sets)';

-- ========================================
-- 6. Create database triggers to enforce protection
-- ========================================

-- Trigger function to prevent deletion of protected nodes
CREATE OR REPLACE FUNCTION prevent_protected_node_deletion()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.is_system_protected = true THEN
        RAISE EXCEPTION 'Cannot delete system-protected node: % (node_id: %)', OLD.label, OLD.node_id
            USING HINT = 'This node is essential for navigation tree structure and cannot be deleted.';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- Trigger function to prevent updates to read-only nodes
CREATE OR REPLACE FUNCTION prevent_readonly_node_update()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.is_read_only = true THEN
        -- Allow updating updated_at timestamp only
        IF NEW.label != OLD.label 
           OR NEW.node_id != OLD.node_id 
           OR NEW.position_x != OLD.position_x 
           OR NEW.position_y != OLD.position_y 
           OR NEW.node_type != OLD.node_type 
           OR NEW.data::text != OLD.data::text 
           OR NEW.verifications::text != OLD.verifications::text THEN
            RAISE EXCEPTION 'Cannot update read-only node: % (node_id: %)', OLD.label, OLD.node_id
                USING HINT = 'This node is read-only and cannot be modified.';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger function to prevent deletion of protected edges
CREATE OR REPLACE FUNCTION prevent_protected_edge_deletion()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.is_system_protected = true THEN
        RAISE EXCEPTION 'Cannot delete system-protected edge: % (edge_id: %)', OLD.label, OLD.edge_id
            USING HINT = 'This edge is essential for navigation tree structure and cannot be deleted.';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- Drop existing triggers if they exist (idempotent)
DROP TRIGGER IF EXISTS trigger_prevent_protected_node_deletion ON navigation_nodes;
DROP TRIGGER IF EXISTS trigger_prevent_readonly_node_update ON navigation_nodes;
DROP TRIGGER IF EXISTS trigger_prevent_protected_edge_deletion ON navigation_edges;

-- Create triggers
CREATE TRIGGER trigger_prevent_protected_node_deletion
    BEFORE DELETE ON navigation_nodes
    FOR EACH ROW
    EXECUTE FUNCTION prevent_protected_node_deletion();

CREATE TRIGGER trigger_prevent_readonly_node_update
    BEFORE UPDATE ON navigation_nodes
    FOR EACH ROW
    EXECUTE FUNCTION prevent_readonly_node_update();

CREATE TRIGGER trigger_prevent_protected_edge_deletion
    BEFORE DELETE ON navigation_edges
    FOR EACH ROW
    EXECUTE FUNCTION prevent_protected_edge_deletion();

-- ========================================
-- 7. Display migration summary
-- ========================================
DO $$
DECLARE
    protected_nodes integer;
    readonly_nodes integer;
    protected_edges integer;
BEGIN
    SELECT COUNT(*) INTO protected_nodes FROM navigation_nodes WHERE is_system_protected = true;
    SELECT COUNT(*) INTO readonly_nodes FROM navigation_nodes WHERE is_read_only = true;
    SELECT COUNT(*) INTO protected_edges FROM navigation_edges WHERE is_system_protected = true;
    
    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Migration Complete: System Protection';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Protected nodes (cannot delete): %', protected_nodes;
    RAISE NOTICE 'Read-only nodes (cannot delete/update): %', readonly_nodes;
    RAISE NOTICE 'Protected edges (cannot delete): %', protected_edges;
    RAISE NOTICE '';
    RAISE NOTICE 'Protection Rules:';
    RAISE NOTICE '  • entry-node: READ-ONLY (cannot delete, cannot update)';
    RAISE NOTICE '  • home: PROTECTED (cannot delete, CAN update)';
    RAISE NOTICE '  • edge-entry-node-to-home: PROTECTED (cannot delete, CAN update)';
    RAISE NOTICE '========================================';
END $$;

