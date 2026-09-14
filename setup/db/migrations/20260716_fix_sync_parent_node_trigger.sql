-- Fix sync_parent_node_to_subtrees: it referenced NEW.userinterface_id, but
-- navigation_nodes has no userinterface_id column, so EVERY UPDATE that changed
-- label/data/verifications on a node errored with
--   record "new" has no field "userinterface_id"  (42703)
-- (first hit live by push_autobuild_to_db.py updating the home node, 2026-07-16).
-- Derive the userinterface from the node's tree instead — the same pattern its
-- sibling function sync_subtree_to_parent_node already uses.

CREATE OR REPLACE FUNCTION public.sync_parent_node_to_subtrees()
RETURNS TRIGGER AS $$
DECLARE
    v_userinterface_id UUID;
BEGIN
    SELECT userinterface_id INTO v_userinterface_id
    FROM public.navigation_trees WHERE id = NEW.tree_id;

    -- Only sync if this node is referenced as a parent by subtrees in the SAME userinterface
    IF EXISTS(
        SELECT 1 FROM public.navigation_trees nt
        JOIN public.navigation_trees parent_tree ON nt.parent_tree_id = parent_tree.id
        WHERE nt.parent_node_id = NEW.node_id
        AND nt.team_id = NEW.team_id
        AND parent_tree.userinterface_id = v_userinterface_id
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
                AND parent_tree.userinterface_id = v_userinterface_id
            );

        RAISE NOTICE 'Synced label/screenshot/verifications for parent node % to subtrees in userinterface %',
                     NEW.node_id, v_userinterface_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- sync_subtree_to_parent_node had one UNQUALIFIED navigation_trees reference; it was
-- masked because its sibling trigger (alphabetically earlier) always errored first.
-- Under PostgREST's restricted search_path an unqualified relation fails with 42P01,
-- so qualify it like every other reference in the function already is.

CREATE OR REPLACE FUNCTION public.sync_subtree_to_parent_node()
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
       AND v_parent_userinterface_id = (SELECT userinterface_id FROM public.navigation_trees WHERE id = NEW.tree_id) THEN
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
$$ LANGUAGE plpgsql;
