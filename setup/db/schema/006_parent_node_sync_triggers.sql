-- Migration 006: Parent Node Sync Triggers
-- Date: 2024-01-XX
-- Description: Add automatic sync triggers for parent node label/screenshot/verifications changes
--              and cascade delete for subtrees when parent node is deleted

-- Drop existing triggers and functions if they exist (for clean recreation)
DROP TRIGGER IF EXISTS cascade_delete_subtrees_trigger ON navigation_nodes;
DROP TRIGGER IF EXISTS sync_parent_node_to_subtrees_trigger ON navigation_nodes;
DROP TRIGGER IF EXISTS sync_parent_label_screenshot_trigger ON navigation_nodes;
DROP FUNCTION IF EXISTS cascade_delete_subtrees() CASCADE;
DROP FUNCTION IF EXISTS sync_parent_node_to_subtrees() CASCADE;
DROP FUNCTION IF EXISTS sync_parent_label_screenshot() CASCADE;

-- ==============================================================================
-- SYNC TRIGGERS FOR NESTED NAVIGATION
-- ==============================================================================

-- 1. Function to sync parent node label, screenshot, and verifications to subtrees
-- NOTE: navigation_nodes does NOT have a userinterface_id column. Resolve it from
-- navigation_trees via NEW.tree_id; PL/pgSQL is lazy-parsed so the NEW.userinterface_id
-- form here used to compile but error at runtime once a node had any subtree.
CREATE OR REPLACE FUNCTION sync_parent_node_to_subtrees()
RETURNS TRIGGER AS $$
DECLARE
    v_userinterface_id uuid;
BEGIN
    SELECT userinterface_id INTO v_userinterface_id
    FROM public.navigation_trees WHERE id = NEW.tree_id;

    -- Only sync if this node is referenced as a parent by subtrees in the SAME userinterface
    IF EXISTS(
        SELECT 1 FROM public.navigation_trees nt
        JOIN public.navigation_trees parent_tree ON nt.parent_tree_id = parent_tree.id
        WHERE nt.parent_node_id = NEW.node_id
        AND nt.team_id = NEW.team_id
        AND parent_tree.userinterface_id = v_userinterface_id  -- ✅ Userinterface isolation
    ) THEN
        -- Update label, screenshot, and verifications in subtree duplicates within SAME userinterface
        UPDATE public.navigation_nodes
        SET
            label = NEW.label,
            data = COALESCE(data, '{}'::jsonb) || jsonb_build_object(
                'screenshot', NEW.data->>'screenshot'
            ),
            verifications = NEW.verifications,
            updated_at = NOW()
        WHERE
            node_id = NEW.node_id
            AND team_id = NEW.team_id
            AND tree_id IN (
                SELECT nt.id FROM public.navigation_trees nt
                JOIN public.navigation_trees parent_tree ON nt.parent_tree_id = parent_tree.id
                WHERE nt.parent_node_id = NEW.node_id
                AND nt.team_id = NEW.team_id
                AND parent_tree.userinterface_id = v_userinterface_id  -- ✅ Userinterface isolation
            );

        RAISE NOTICE 'Synced label/screenshot/verifications for parent node % to % subtrees in userinterface %',
                     NEW.node_id,
                     (SELECT COUNT(*) FROM public.navigation_trees nt
                      JOIN public.navigation_trees parent_tree ON nt.parent_tree_id = parent_tree.id
                      WHERE nt.parent_node_id = NEW.node_id AND nt.team_id = NEW.team_id
                      AND parent_tree.userinterface_id = v_userinterface_id),
                     v_userinterface_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path TO public, pg_temp;

-- 2. Function to cascade delete subtrees when parent node is deleted
CREATE OR REPLACE FUNCTION cascade_delete_subtrees()
RETURNS TRIGGER AS $$
DECLARE
    subtree_count INTEGER;
    v_userinterface_id uuid;
BEGIN
    -- Resolve userinterface_id from the deleted node's tree (navigation_nodes has no UI column).
    SELECT userinterface_id INTO v_userinterface_id
    FROM navigation_trees WHERE id = OLD.tree_id;

    -- Count subtrees before deletion for logging (only within same userinterface)
    SELECT COUNT(*) INTO subtree_count
    FROM navigation_trees nt
    JOIN navigation_trees parent_tree ON nt.parent_tree_id = parent_tree.id
    WHERE nt.parent_node_id = OLD.node_id
    AND nt.team_id = OLD.team_id
    AND parent_tree.userinterface_id = v_userinterface_id;  -- ✅ Userinterface isolation

    -- When a parent node is deleted, delete all its subtrees within the SAME userinterface
    -- This prevents deleting subtrees from other userinterfaces when duplicating/deleting
    DELETE FROM navigation_trees
    WHERE parent_node_id = OLD.node_id
    AND team_id = OLD.team_id
    AND userinterface_id = v_userinterface_id;  -- ✅ Userinterface isolation

    -- Log cascade delete for debugging
    IF subtree_count > 0 THEN
        RAISE NOTICE 'Cascade deleted % subtrees for parent node % in userinterface %', subtree_count, OLD.node_id, v_userinterface_id;
    END IF;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql SET search_path TO public, pg_temp;

-- 3. Create sync trigger (fires on label, screenshot, or verifications changes)
DROP TRIGGER IF EXISTS sync_parent_node_to_subtrees_trigger ON navigation_nodes;
CREATE TRIGGER sync_parent_node_to_subtrees_trigger
    AFTER UPDATE ON navigation_nodes
    FOR EACH ROW
    WHEN (
        -- Fire when label, data (including screenshot), or verifications changes
        OLD.label IS DISTINCT FROM NEW.label OR
        OLD.data IS DISTINCT FROM NEW.data OR
        OLD.verifications IS DISTINCT FROM NEW.verifications
    )
    EXECUTE FUNCTION sync_parent_node_to_subtrees();

-- 4. Create cascade delete trigger
DROP TRIGGER IF EXISTS cascade_delete_subtrees_trigger ON navigation_nodes;
CREATE TRIGGER cascade_delete_subtrees_trigger
    AFTER DELETE ON navigation_nodes
    FOR EACH ROW
    EXECUTE FUNCTION cascade_delete_subtrees();

-- ==============================================================================
-- BIDIRECTIONAL SYNC - SUBTREE TO PARENT
-- ==============================================================================

-- 5. Function to sync subtree entry nodes back to parent nodes (reverse direction)
CREATE OR REPLACE FUNCTION sync_subtree_to_parent_node()
RETURNS TRIGGER AS $$
DECLARE
    v_parent_tree_id UUID;
    v_parent_node_id TEXT;
    v_parent_userinterface_id UUID;
BEGIN
    -- Check if this node is an entry node in a subtree
    SELECT nt.parent_tree_id, nt.parent_node_id, pt.userinterface_id
    INTO v_parent_tree_id, v_parent_node_id, v_parent_userinterface_id
    FROM public.navigation_trees nt
    JOIN public.navigation_trees pt ON nt.parent_tree_id = pt.id
    WHERE nt.id = NEW.tree_id
    AND nt.team_id = NEW.team_id
    AND nt.parent_tree_id IS NOT NULL
    AND nt.parent_node_id IS NOT NULL;

    -- If this is a subtree entry node in the SAME userinterface, sync back to parent
    IF v_parent_tree_id IS NOT NULL AND v_parent_node_id IS NOT NULL
       AND v_parent_userinterface_id = (SELECT userinterface_id FROM navigation_trees WHERE id = NEW.tree_id) THEN
        UPDATE public.navigation_nodes
        SET
            label = NEW.label,
            data = COALESCE(data, '{}'::jsonb) || jsonb_build_object(
                'screenshot', NEW.data->>'screenshot'
            ),
            verifications = NEW.verifications,
            updated_at = NOW()
        WHERE
            node_id = NEW.node_id
            AND tree_id = v_parent_tree_id
            AND team_id = NEW.team_id;

        IF FOUND THEN
            RAISE NOTICE 'Synced screenshot/label/verifications from subtree entry node % back to parent node in tree % (same userinterface)',
                         NEW.node_id,
                         v_parent_tree_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path TO public, pg_temp;

-- 6. Create reverse sync trigger (subtree → parent)
DROP TRIGGER IF EXISTS sync_subtree_to_parent_trigger ON navigation_nodes;
CREATE TRIGGER sync_subtree_to_parent_trigger
    AFTER UPDATE ON navigation_nodes
    FOR EACH ROW
    WHEN (
        -- Fire when label, data (including screenshot), or verifications changes
        OLD.label IS DISTINCT FROM NEW.label OR
        OLD.data IS DISTINCT FROM NEW.data OR
        OLD.verifications IS DISTINCT FROM NEW.verifications
    )
    EXECUTE FUNCTION sync_subtree_to_parent_node();

-- ==============================================================================
-- ROLLBACK INSTRUCTIONS
-- ==============================================================================
-- To rollback this migration, run:
--
-- DROP TRIGGER IF EXISTS sync_parent_node_to_subtrees_trigger ON navigation_nodes;
-- DROP TRIGGER IF EXISTS sync_subtree_to_parent_trigger ON navigation_nodes;
-- DROP TRIGGER IF EXISTS cascade_delete_subtrees_trigger ON navigation_nodes;
-- DROP FUNCTION IF EXISTS sync_parent_node_to_subtrees();
-- DROP FUNCTION IF EXISTS sync_subtree_to_parent_node();
-- DROP FUNCTION IF EXISTS cascade_delete_subtrees();

-- Log migration completion
SELECT 'Migration 006: Parent node sync triggers (bidirectional) applied successfully' as status;
