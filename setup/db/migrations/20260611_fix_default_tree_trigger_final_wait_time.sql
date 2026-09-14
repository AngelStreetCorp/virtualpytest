-- Regression fix: migration 20260507_e dropped navigation_edges.final_wait_time
-- (it now lives per-direction inside each action_sets element) but left two
-- DDL objects still referencing the old column:
--
--   1. create_default_navigation_tree()  — the AFTER INSERT trigger on
--      userinterfaces. It INSERTs the default Entry→home edge WITH the
--      final_wait_time column, so EVERY new userinterface (manual create AND
--      duplicate) raised: column "final_wait_time" of relation
--      "navigation_edges" does not exist  → 500 on the UserInterface page.
--   2. get_full_navigation_tree()  — SELECTs the dropped column.
--
-- This migration recreates both functions with final_wait_time removed from the
-- edge columns and folded into the default action_set (new per-direction model).
-- Idempotent: pure CREATE OR REPLACE.

BEGIN;

-- 1. Default-tree trigger: put final_wait_time inside the action_set, not the column.
CREATE OR REPLACE FUNCTION create_default_navigation_tree()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- Run with postgres privileges to bypass RLS
SET search_path TO public, pg_temp
AS $$
DECLARE
    v_tree_id UUID;
    v_action_set_id TEXT;
BEGIN
    -- Generate a unique action set ID
    v_action_set_id := 'actionset-' || EXTRACT(EPOCH FROM now())::bigint::text;

    -- 1. Create root navigation tree for this interface
    INSERT INTO public.navigation_trees (
        name, description, userinterface_id, team_id,
        is_root_tree, tree_depth, parent_tree_id, parent_node_id,
        viewport_x, viewport_y, viewport_zoom
    ) VALUES (
        NEW.name || '_navigation',
        'Navigation tree for ' || NEW.name,
        NEW.id,
        NEW.team_id,
        true,    -- is_root_tree
        0,       -- tree_depth
        NULL,    -- parent_tree_id
        NULL,    -- parent_node_id
        0, 0, 1  -- viewport defaults
    )
    RETURNING id INTO v_tree_id;

    -- 2. Create entry node (system-protected)
    INSERT INTO public.navigation_nodes (
        tree_id, node_id, label, node_type,
        position_x, position_y,
        data, style, verifications,
        is_system_protected, is_read_only,
        team_id
    ) VALUES (
        v_tree_id,
        'entry-node',
        'Entry',
        'entry',
        100, 200,
        '{"type": "entry", "label": "Entry", "description": "Entry point for navigation", "is_root": true}'::jsonb,
        '{}'::jsonb,
        '[]'::jsonb,
        true,   -- is_system_protected
        false,  -- is_read_only
        NEW.team_id
    );

    -- 3. Create home node (system-protected)
    INSERT INTO public.navigation_nodes (
        tree_id, node_id, label, node_type,
        position_x, position_y,
        data, style, verifications,
        is_system_protected, is_read_only,
        team_id
    ) VALUES (
        v_tree_id,
        'home',
        'home',
        'screen',
        300, 200,
        '{"type": "screen", "label": "home", "description": "Home screen - main landing page", "is_root": true}'::jsonb,
        '{}'::jsonb,
        '[]'::jsonb,
        true,   -- is_system_protected
        false,  -- is_read_only
        NEW.team_id
    );

    -- 4. Create edge connecting entry-node → home (system-protected).
    --    final_wait_time now lives inside the action_set (per-direction model).
    INSERT INTO public.navigation_edges (
        tree_id, edge_id,
        source_node_id, target_node_id,
        label, edge_type,
        action_sets, default_action_set_id,
        data, style,
        is_system_protected,
        team_id
    ) VALUES (
        v_tree_id,
        'edge-entry-node-to-home',
        'entry-node',
        'home',
        'Entry→home',
        'default',
        jsonb_build_array(
            jsonb_build_object(
                'id', v_action_set_id,
                'label', 'Entry→home',
                'actions', '[]'::jsonb,
                'retry_actions', '[]'::jsonb,
                'failure_actions', '[]'::jsonb,
                'priority', 1,
                'final_wait_time', 2000
            )
        ),
        v_action_set_id,
        '{"priority": "p3", "sourceHandle": "right-source", "targetHandle": "left-target"}'::jsonb,
        '{}'::jsonb,
        true,   -- is_system_protected
        NEW.team_id
    );

    -- Update tree root_node_id to point to entry-node
    UPDATE public.navigation_trees
    SET root_node_id = (
        SELECT id FROM public.navigation_nodes
        WHERE tree_id = v_tree_id AND node_id = 'entry-node'
    )
    WHERE id = v_tree_id;

    RAISE NOTICE 'Auto-created navigation tree % with entry-node and home for userinterface %', v_tree_id, NEW.name;

    RETURN NEW;
END;
$$;

-- 2. get_full_navigation_tree: drop the removed column from the edge SELECT.
CREATE OR REPLACE FUNCTION get_full_navigation_tree(
    p_tree_id UUID,
    p_team_id UUID
)
RETURNS JSON
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_result JSON;
BEGIN
    SELECT json_build_object(
        'success', true,
        'tree', (
            SELECT row_to_json(t)
            FROM (
                SELECT
                    id,
                    name,
                    team_id,
                    userinterface_id,
                    parent_tree_id,
                    parent_node_id,
                    viewport_x,
                    viewport_y,
                    viewport_zoom,
                    created_at,
                    updated_at
                FROM navigation_trees
                WHERE id = p_tree_id
                AND team_id = p_team_id
            ) t
        ),
        'nodes', (
            SELECT COALESCE(json_agg(n ORDER BY created_at), '[]'::json)
            FROM (
                SELECT
                    id,
                    tree_id,
                    node_id,
                    node_type,
                    label,
                    position_x,
                    position_y,
                    data,
                    style,
                    team_id,
                    has_subtree,
                    subtree_count,
                    verifications,
                    created_at,
                    updated_at
                FROM navigation_nodes
                WHERE tree_id = p_tree_id
                AND team_id = p_team_id
            ) n
        ),
        'edges', (
            SELECT COALESCE(json_agg(e ORDER BY created_at), '[]'::json)
            FROM (
                SELECT
                    id,
                    tree_id,
                    edge_id,
                    source_node_id,
                    target_node_id,
                    label,
                    data,
                    team_id,
                    action_sets,
                    default_action_set_id,
                    created_at,
                    updated_at
                FROM navigation_edges
                WHERE tree_id = p_tree_id
                AND team_id = p_team_id
            ) e
        )
    ) INTO v_result;

    RETURN v_result;
END;
$$;

COMMIT;
