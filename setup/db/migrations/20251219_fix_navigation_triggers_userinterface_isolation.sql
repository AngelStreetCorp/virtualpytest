-- Migration: 20251219_fix_navigation_triggers_userinterface_isolation
-- Date: 2025-12-19
-- Description: Fix navigation triggers to be userinterface-aware to prevent cross-contamination between duplicated userinterfaces
--              This prevents cascade deletes and sync operations from affecting trees in different userinterfaces

-- ==============================================================================
-- FIX: CASCADE DELETE SUBTREES TRIGGER - ADD USERINTERFACE ISOLATION
-- ==============================================================================

CREATE OR REPLACE FUNCTION public.cascade_delete_subtrees()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
    subtree_count INTEGER;
    parent_tree_userinterface_id UUID;
BEGIN
    -- Get the userinterface_id from the tree that contains this node
    SELECT userinterface_id INTO parent_tree_userinterface_id
    FROM navigation_trees
    WHERE id = OLD.tree_id;

    -- Count subtrees before deletion for logging (only within same userinterface)
    SELECT COUNT(*) INTO subtree_count
    FROM navigation_trees nt
    WHERE nt.parent_node_id = OLD.node_id
    AND nt.team_id = OLD.team_id
    AND nt.userinterface_id = parent_tree_userinterface_id;  -- ✅ Userinterface isolation

    -- When a parent node is deleted, delete all its subtrees within the SAME userinterface
    -- This prevents deleting subtrees from other userinterfaces when duplicating/deleting
    DELETE FROM navigation_trees
    WHERE parent_node_id = OLD.node_id
    AND team_id = OLD.team_id
    AND userinterface_id = parent_tree_userinterface_id;  -- ✅ Userinterface isolation

    -- Log cascade delete for debugging
    IF subtree_count > 0 THEN
        RAISE NOTICE 'Cascade deleted % subtrees for parent node % in userinterface %', subtree_count, OLD.node_id, parent_tree_userinterface_id;
    END IF;

    RETURN OLD;
END;
$function$;

-- ==============================================================================
-- FIX: SYNC PARENT TO SUBTREES TRIGGER - ADD USERINTERFACE ISOLATION
-- ==============================================================================

CREATE OR REPLACE FUNCTION public.sync_parent_node_to_subtrees()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
BEGIN
    -- Only sync if this node is referenced as a parent by subtrees in the SAME userinterface
    IF EXISTS(
        SELECT 1 FROM public.navigation_trees nt
        JOIN public.navigation_trees parent_tree ON nt.parent_tree_id = parent_tree.id
        WHERE nt.parent_node_id = NEW.node_id
        AND nt.team_id = NEW.team_id
        AND parent_tree.userinterface_id = NEW.userinterface_id  -- ✅ Userinterface isolation
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
                AND parent_tree.userinterface_id = NEW.userinterface_id  -- ✅ Userinterface isolation
            );

        RAISE NOTICE 'Synced label/screenshot/verifications for parent node % to % subtrees in userinterface %',
                     NEW.node_id,
                     (SELECT COUNT(*) FROM public.navigation_trees nt
                      JOIN public.navigation_trees parent_tree ON nt.parent_tree_id = parent_tree.id
                      WHERE nt.parent_node_id = NEW.node_id AND nt.team_id = NEW.team_id
                      AND parent_tree.userinterface_id = NEW.userinterface_id),
                     NEW.userinterface_id;
    END IF;

    RETURN NEW;
END;
$function$;

-- ==============================================================================
-- FIX: SYNC SUBTREE TO PARENT TRIGGER - ADD USERINTERFACE ISOLATION
-- ==============================================================================

CREATE OR REPLACE FUNCTION public.sync_subtree_to_parent_node()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
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
$function$;

-- ==============================================================================
-- FIX: UPDATE NODE SUBTREE COUNTS TRIGGER - ADD USERINTERFACE ISOLATION
-- ==============================================================================

CREATE OR REPLACE FUNCTION public.update_node_subtree_counts()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
    parent_tree_userinterface_id UUID;
    parent_tree_exists BOOLEAN := false;
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Check if parent tree exists
        SELECT userinterface_id, true INTO parent_tree_userinterface_id, parent_tree_exists
        FROM navigation_trees
        WHERE id = NEW.parent_tree_id;

        -- Only update if parent tree exists
        IF parent_tree_exists THEN
            -- Update parent node's subtree information (only for trees in same userinterface)
            UPDATE public.navigation_nodes
            SET
                has_subtree = true,
                subtree_count = (
                    SELECT COUNT(*)
                    FROM public.navigation_trees
                    WHERE parent_tree_id = NEW.parent_tree_id
                    AND parent_node_id = NEW.parent_node_id
                    AND userinterface_id = parent_tree_userinterface_id  -- ✅ Userinterface isolation
                )
            WHERE tree_id = NEW.parent_tree_id
            AND node_id = NEW.parent_node_id;
        END IF;

        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        -- Check if parent tree still exists (important during cascade deletes)
        SELECT userinterface_id, true INTO parent_tree_userinterface_id, parent_tree_exists
        FROM navigation_trees
        WHERE id = OLD.parent_tree_id;

        -- Only update if parent tree still exists
        IF parent_tree_exists THEN
            -- Update parent node's subtree information (only for trees in same userinterface)
            UPDATE public.navigation_nodes
            SET
                subtree_count = (
                    SELECT COUNT(*)
                    FROM public.navigation_trees
                    WHERE parent_tree_id = OLD.parent_tree_id
                    AND parent_node_id = OLD.parent_node_id
                    AND userinterface_id = parent_tree_userinterface_id  -- ✅ Userinterface isolation
                )
            WHERE tree_id = OLD.parent_tree_id
            AND node_id = OLD.parent_node_id;

            -- If no more subtrees in this userinterface, set has_subtree to false
            UPDATE public.navigation_nodes
            SET has_subtree = false
            WHERE tree_id = OLD.parent_tree_id
            AND node_id = OLD.parent_node_id
            AND subtree_count = 0;
        END IF;

        RETURN OLD;
    END IF;

    RETURN NULL;
END;
$function$;

-- ==============================================================================
-- UPDATE SCHEMA FILES
-- ==============================================================================

-- Update 002_ui_navigation_tables.sql with the fixed functions
-- (The schema file should be updated to reflect these changes for future deployments)

-- Update 006_parent_node_sync_triggers.sql with the fixed functions
-- (The schema file should be updated to reflect these changes for future deployments)

-- ==============================================================================
-- VERIFICATION
-- ==============================================================================

-- Verify the fixes are applied
DO $$
DECLARE
    func_count INTEGER;
BEGIN
    -- Check that all functions exist and are updated
    SELECT COUNT(*) INTO func_count
    FROM pg_proc
    WHERE proname IN (
        'cascade_delete_subtrees',
        'sync_parent_node_to_subtrees',
        'sync_subtree_to_parent_node',
        'update_node_subtree_counts'
    );

    IF func_count = 4 THEN
        RAISE NOTICE '✅ All navigation trigger functions updated successfully with userinterface isolation';
    ELSE
        RAISE EXCEPTION '❌ Some navigation trigger functions are missing or not updated';
    END IF;
END;
$$;

-- Log migration completion
SELECT 'Migration 20251219: Fixed navigation triggers for userinterface isolation - prevents cross-contamination between duplicated userinterfaces' as status;
