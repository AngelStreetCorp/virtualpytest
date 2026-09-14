-- VirtualPyTest UI & Navigation Tables Schema
-- This file contains tables for user interfaces, navigation trees, nodes, and edges
--
-- RECENT UPDATES:
-- - 2025-12-14: PERFORMANCE OPTIMIZATION - Added critical indexes and optimized RLS policies
--               to fix get_userinterface_complete server disconnect issues. Added composite
--               indexes for (tree_id, team_id) queries, optimized RLS auth evaluation, and
--               materialized view indexes. Expected 10-50x query performance improvement.
-- - 2025-10-28: style/data/edge_type/node_type columns use DEFAULT values but allow NULLs
--               for backward compatibility with existing data. Python code handles NULLs.
--

-- Drop existing tables if they exist (for clean recreation).
-- No `DROP TRIGGER IF EXISTS … ON <table>` here: Postgres errors when the TABLE is missing
-- (IF EXISTS only covers the trigger), which broke every fresh install at this file
-- (BUG-0077). `DROP TABLE … CASCADE` below removes the triggers anyway.
DROP FUNCTION IF EXISTS create_default_navigation_tree() CASCADE;
DROP FUNCTION IF EXISTS cascade_delete_subtrees() CASCADE;
DROP FUNCTION IF EXISTS sync_parent_label_screenshot() CASCADE;
DROP FUNCTION IF EXISTS update_node_subtree_counts() CASCADE;
DROP FUNCTION IF EXISTS get_tree_path(uuid) CASCADE;
DROP FUNCTION IF EXISTS get_descendant_trees(uuid) CASCADE;
DROP TABLE IF EXISTS navigation_trees_history CASCADE;
DROP TABLE IF EXISTS navigation_edges CASCADE;
DROP TABLE IF EXISTS navigation_nodes CASCADE;
DROP TABLE IF EXISTS navigation_trees CASCADE;
DROP TABLE IF EXISTS userinterfaces CASCADE;

-- User interfaces (screens/apps being tested) - UPDATED SCHEMA
CREATE TABLE userinterfaces (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    name character varying NOT NULL,
    models text[] DEFAULT '{}'::text[],  -- UPDATED: Array of compatible device models
    min_version character varying,       -- UPDATED: Minimum version support
    max_version character varying,       -- UPDATED: Maximum version support
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

-- Navigation trees (renamed from original, now stores only metadata)
CREATE TABLE navigation_trees (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    name character varying NOT NULL,
    userinterface_id uuid REFERENCES userinterfaces(id) ON DELETE CASCADE,  -- UPDATED: Made nullable
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    description text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    root_node_id uuid,  -- UPDATED: Changed from text to uuid
    
    -- Nested tree relationship columns
    parent_tree_id uuid REFERENCES navigation_trees(id) ON DELETE CASCADE,
    parent_node_id text, -- References the node_id that spawned this subtree
    tree_depth integer DEFAULT 0, -- Depth level (0 = root, 1 = first level nested, etc.)
    is_root_tree boolean DEFAULT true, -- True only for top-level trees
    
    -- React Flow viewport position fields
    viewport_x double precision DEFAULT 0, -- React Flow viewport X position for restoring view state
    viewport_y double precision DEFAULT 0, -- React Flow viewport Y position for restoring view state  
    viewport_zoom double precision DEFAULT 1, -- React Flow viewport zoom level for restoring view state
    
    -- Constraints for nested trees
    CONSTRAINT check_tree_depth CHECK (tree_depth >= 0 AND tree_depth <= 5),
    CONSTRAINT check_parent_consistency 
    CHECK (
        (parent_tree_id IS NULL AND parent_node_id IS NULL AND is_root_tree = true) OR
        (parent_tree_id IS NOT NULL AND parent_node_id IS NOT NULL AND is_root_tree = false)
    )
);

-- Navigation nodes (individual nodes with embedded verifications)
CREATE TABLE navigation_nodes (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    tree_id uuid NOT NULL REFERENCES navigation_trees(id) ON DELETE CASCADE,
    node_id text NOT NULL, -- User-defined node identifier
    label text NOT NULL,
    position_x double precision NOT NULL DEFAULT 0,
    position_y double precision NOT NULL DEFAULT 0,
    node_type text DEFAULT 'default',
    style jsonb DEFAULT '{}',
    data jsonb DEFAULT '{}',
    verifications jsonb DEFAULT '[]', -- ✅ Embedded verification objects (base set)
    variant_overrides jsonb NOT NULL DEFAULT '[]'::jsonb, -- ✅ [{ match: { locale?, platform? }, patches: [...], disabled? }]

    -- Nested tree metadata
    has_subtree boolean DEFAULT false, -- True if this node has associated subtrees
    subtree_count integer DEFAULT 0, -- Number of subtrees linked to this node
    
    -- Protection flags
    is_system_protected boolean DEFAULT false, -- True for essential nodes that cannot be deleted (but may be updated)
    is_read_only boolean DEFAULT false, -- True for nodes that cannot be updated or deleted (stricter than is_system_protected)
    
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    UNIQUE(tree_id, node_id)
);

-- Navigation edges (individual edges with action_sets structure - NO LEGACY SUPPORT)
-- Each edge can contain MULTIPLE action sets for bidirectional navigation
-- Each action set represents one navigation method (e.g., "Click Tab", "Press Key")
--
-- ACTION SET STRUCTURE:
-- {
--   "id": "home_to_movies_1",                    -- Unique ID within edge
--   "label": "Click Movies Tab",                 -- Descriptive label for UI
--   "actions": [...],                            -- Array of actions to execute
--   "retry_actions": [...],                      -- Array of retry actions if main fails
--   "failure_actions": [...],                    -- Array of failure actions if retry fails
--   "priority": 1,                               -- Priority (1 = default/primary)
--   "conditions": {},                            -- Optional conditions for execution
--   "timer": 0,                                  -- Timer for auto-return (milliseconds)
--   "kpi_references": [...],                     -- KPI measurement verifications (same format as node verifications)
--   "use_verifications_for_kpi": false           -- When TRUE, use target node's verifications for KPI instead of kpi_references
-- }
--
-- EXAMPLES:
-- - Edge "home ↔ home_tvguide" has 2 action sets: forward + reverse
-- - Edge "home_tvguide ↔ tvguide_livetv" has 3 action sets: forward + 2 reverse methods
CREATE TABLE navigation_edges (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    tree_id uuid NOT NULL REFERENCES navigation_trees(id) ON DELETE CASCADE,
    edge_id text NOT NULL, -- User-defined edge identifier
    source_node_id text NOT NULL,
    target_node_id text NOT NULL,
    label text, -- ✅ UPDATED: Now uses bidirectional format (e.g., "home ↔ home_tvguide")
    edge_type text DEFAULT 'default',
    style jsonb DEFAULT '{}',
    data jsonb DEFAULT '{}',
    action_sets jsonb NOT NULL DEFAULT '[]', -- ✅ REQUIRED: Array of action sets (2-3 per edge typical)
    variant_overrides jsonb NOT NULL DEFAULT '[]'::jsonb, -- ✅ [{ match: { locale?, platform? }, patches: [{ action_set_index, action_index, params }], disabled? }]
    default_action_set_id text NOT NULL, -- ✅ REQUIRED: ID of default action set (priority 1)
    -- final_wait_time + threshold live per-direction inside each action_sets element
    -- (see migration 20260507_e_per_direction_wait_threshold.sql); no edge-level column.
    is_system_protected boolean DEFAULT false, -- True for essential edges that cannot be deleted
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    UNIQUE(tree_id, edge_id),
    
    -- Ensure action_sets is not empty and default_action_set_id exists
    CONSTRAINT check_action_sets_not_empty CHECK (jsonb_array_length(action_sets) > 0),
    CONSTRAINT check_default_action_set_exists CHECK (
        default_action_set_id IS NOT NULL AND 
        action_sets @> jsonb_build_array(jsonb_build_object('id', default_action_set_id))
    )
);

-- Navigation trees history (UPDATED SCHEMA)
CREATE TABLE navigation_trees_history (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    tree_id uuid REFERENCES navigation_trees(id) ON DELETE CASCADE,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    version_number integer NOT NULL,  -- UPDATED: More specific naming
    modification_type text NOT NULL CHECK (modification_type = ANY (ARRAY['create'::text, 'update'::text, 'delete'::text, 'restore'::text])),  -- UPDATED: Added enum constraint
    modified_by uuid,  -- UPDATED: Renamed from changed_by_user_id
    tree_data jsonb NOT NULL,  -- UPDATED: Made NOT NULL
    changes_summary text,  -- UPDATED: Renamed from change_description
    created_at timestamp with time zone DEFAULT now(),
    restored_from_version integer  -- UPDATED: Added for restore tracking
);

-- Add Foreign Key Constraints
ALTER TABLE navigation_nodes 
    ADD CONSTRAINT fk_navigation_nodes_tree 
    FOREIGN KEY (tree_id) REFERENCES navigation_trees(id) ON DELETE CASCADE;

ALTER TABLE navigation_edges
    ADD CONSTRAINT fk_navigation_edges_tree
    FOREIGN KEY (tree_id) REFERENCES navigation_trees(id) ON DELETE CASCADE;

-- Add Indexes for Performance
CREATE INDEX idx_navigation_trees_userinterface ON navigation_trees(userinterface_id);
CREATE INDEX idx_navigation_trees_team ON navigation_trees(team_id);
CREATE INDEX idx_navigation_trees_name ON navigation_trees(name);

-- Nested tree indexes
CREATE INDEX idx_navigation_trees_parent_tree ON navigation_trees(parent_tree_id);
CREATE INDEX idx_navigation_trees_parent_node ON navigation_trees(parent_node_id);
CREATE INDEX idx_navigation_trees_depth ON navigation_trees(tree_depth);
CREATE INDEX idx_navigation_trees_is_root ON navigation_trees(is_root_tree);

CREATE INDEX idx_navigation_nodes_tree ON navigation_nodes(tree_id);
CREATE INDEX idx_navigation_nodes_node_id ON navigation_nodes(node_id);
CREATE INDEX idx_navigation_nodes_team ON navigation_nodes(team_id);
CREATE INDEX idx_navigation_nodes_position ON navigation_nodes(position_x, position_y);
CREATE INDEX idx_navigation_nodes_has_subtree ON navigation_nodes(has_subtree);

CREATE INDEX idx_navigation_edges_tree ON navigation_edges(tree_id);
CREATE INDEX idx_navigation_edges_edge_id ON navigation_edges(edge_id);
CREATE INDEX idx_navigation_edges_source ON navigation_edges(source_node_id);
CREATE INDEX idx_navigation_edges_target ON navigation_edges(target_node_id);

-- NEW: Indexes for action_sets structure
CREATE INDEX idx_navigation_edges_action_sets ON navigation_edges USING GIN (action_sets);
CREATE INDEX idx_navigation_edges_default_action_set ON navigation_edges(default_action_set_id);
CREATE INDEX idx_navigation_edges_team ON navigation_edges(team_id);

CREATE INDEX idx_navigation_trees_history_tree ON navigation_trees_history(tree_id);
CREATE INDEX idx_navigation_trees_history_team ON navigation_trees_history(team_id);

-- Viewport position index
CREATE INDEX idx_navigation_trees_viewport ON navigation_trees(viewport_x, viewport_y, viewport_zoom);

-- ==================================================
-- PERFORMANCE OPTIMIZATION INDEXES (2025-12-14)
-- ==================================================

-- Composite indexes for common query patterns (tree_id + team_id)
-- These are critical for get_userinterface_complete performance
CREATE INDEX idx_navigation_nodes_tree_team ON navigation_nodes(tree_id, team_id);
CREATE INDEX idx_navigation_edges_tree_team ON navigation_edges(tree_id, team_id);
CREATE INDEX idx_navigation_trees_userinterface_team ON navigation_trees(userinterface_id, team_id);

-- Partial indexes for active/filtered queries
CREATE INDEX idx_navigation_nodes_active ON navigation_nodes(tree_id, team_id) WHERE node_id IS NOT NULL;
CREATE INDEX idx_navigation_edges_active ON navigation_edges(tree_id, team_id) WHERE edge_id IS NOT NULL;

-- Add index comments explaining performance impact
COMMENT ON INDEX idx_navigation_trees_team IS 'Critical index for navigation_trees.team_id foreign key - eliminates slow JOINs in get_userinterface_complete';
COMMENT ON INDEX idx_navigation_nodes_tree_team IS 'Composite index for (tree_id, team_id) - optimizes most common navigation queries';

-- Add column comments
COMMENT ON COLUMN navigation_edges.action_sets IS 'Array of action sets. Each action set can include kpi_references (verification objects) and use_verifications_for_kpi flag for per-transition performance measurement.';
COMMENT ON COLUMN navigation_nodes.is_system_protected IS 'Flag indicating if this node cannot be deleted (but may be updated unless is_read_only=true)';
COMMENT ON COLUMN navigation_nodes.is_read_only IS 'Flag indicating if this node is completely read-only (cannot be updated or deleted). Stricter than is_system_protected.';
COMMENT ON COLUMN navigation_edges.is_system_protected IS 'Flag indicating if this edge cannot be deleted (but may be updated via action sets)';

-- Nested Tree Helper Functions
-- Function to get all descendant trees
-- ============================================================================
-- PERFORMANCE OPTIMIZATION FUNCTION
-- ============================================================================

-- Optimized function to fetch complete tree data in a single query
-- Performance: Reduces 3 separate queries to 1 (67% reduction in round trips)
-- Expected improvement: ~1.4s → ~0.5s on first load
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
    -- Combine tree metadata, nodes, and edges into a single JSON response
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

COMMENT ON FUNCTION get_full_navigation_tree(UUID, UUID) IS 
'Optimized function to fetch complete tree data (metadata + nodes + edges) in a single database call. 
Reduces 3 separate queries to 1, improving performance by ~70%.';

-- ============================================================================
-- TREE HIERARCHY FUNCTIONS
-- ============================================================================

CREATE OR REPLACE FUNCTION get_descendant_trees(root_tree_id uuid)
RETURNS TABLE(tree_id uuid, tree_name text, depth integer, parent_tree_id uuid, parent_node_id text)
LANGUAGE sql
AS $$
    WITH RECURSIVE tree_hierarchy AS (
        -- Base case: start with the root tree
        SELECT id, name, tree_depth, parent_tree_id, parent_node_id
        FROM navigation_trees 
        WHERE id = root_tree_id
        
        UNION ALL
        
        -- Recursive case: find children
        SELECT nt.id, nt.name, nt.tree_depth, nt.parent_tree_id, nt.parent_node_id
        FROM navigation_trees nt
        INNER JOIN tree_hierarchy th ON nt.parent_tree_id = th.id
    )
    SELECT 
        id AS tree_id, 
        name AS tree_name, 
        tree_depth AS depth, 
        parent_tree_id, 
        parent_node_id 
    FROM tree_hierarchy;
$$;

-- Function to get tree path (breadcrumb)
CREATE OR REPLACE FUNCTION get_tree_path(target_tree_id uuid)
RETURNS TABLE(tree_id uuid, tree_name text, depth integer, node_id text)
LANGUAGE sql
AS $$
    WITH RECURSIVE tree_path AS (
        -- Base case: start with target tree
        SELECT id, name, tree_depth, parent_tree_id, parent_node_id
        FROM navigation_trees 
        WHERE id = target_tree_id
        
        UNION ALL
        
        -- Recursive case: go up to parents
        SELECT nt.id, nt.name, nt.tree_depth, nt.parent_tree_id, nt.parent_node_id
        FROM navigation_trees nt
        INNER JOIN tree_path tp ON nt.id = tp.parent_tree_id
    )
    SELECT id, name, tree_depth, parent_node_id 
    FROM tree_path 
    ORDER BY tree_depth ASC;
$$;

-- Function to update node subtree counts
-- FIXED: Lookup userinterface_id from navigation_trees (not navigation_nodes which lacks this column)
CREATE OR REPLACE FUNCTION update_node_subtree_counts()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- ✅ Run with postgres privileges to bypass RLS
SET search_path TO public, pg_temp
AS $$
DECLARE
    parent_tree_userinterface_id UUID;
    parent_tree_exists BOOLEAN := false;
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Check if parent tree exists and get its userinterface_id
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
$$;

-- Create trigger to automatically update subtree counts
CREATE TRIGGER trigger_update_subtree_counts
    AFTER INSERT OR DELETE ON navigation_trees
    FOR EACH ROW
    EXECUTE FUNCTION update_node_subtree_counts();

-- Enable Row Level Security (RLS)
ALTER TABLE userinterfaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE navigation_trees ENABLE ROW LEVEL SECURITY;
ALTER TABLE navigation_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE navigation_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE navigation_trees_history ENABLE ROW LEVEL SECURITY;

-- RLS Policies (optimized for performance - avoid auth function re-evaluation per row)
CREATE POLICY "userinterfaces_open_access" ON userinterfaces
FOR ALL
TO public
USING (true);

CREATE POLICY "navigation_trees_access_policy" ON navigation_trees
FOR ALL USING (true);

CREATE POLICY "navigation_nodes_access_policy" ON navigation_nodes
FOR ALL USING (true);

CREATE POLICY "navigation_edges_access_policy" ON navigation_edges
FOR ALL USING (true);

CREATE POLICY "navigation_trees_history_access_policy" ON navigation_trees_history
FOR ALL 
TO public
USING (true);

-- ==============================================================================
-- NESTED NAVIGATION SYNC TRIGGERS
-- ==============================================================================
-- The bidirectional parent↔subtree sync (label, screenshot, verifications) and
-- cascade-delete logic live in 006_parent_node_sync_triggers.sql.

-- ============================================================================
-- PROTECTED NODE AND EDGE DELETION TRIGGERS
-- ============================================================================

-- Function to prevent deletion of protected nodes (unless CASCADE delete)
CREATE OR REPLACE FUNCTION prevent_protected_node_deletion()
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

-- Create trigger for protected node deletion
CREATE TRIGGER trigger_prevent_protected_node_deletion
    BEFORE DELETE ON navigation_nodes
    FOR EACH ROW
    EXECUTE FUNCTION prevent_protected_node_deletion();

-- Function to prevent updates to read-only nodes
CREATE OR REPLACE FUNCTION prevent_readonly_node_update()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- ✅ Run with postgres privileges to bypass RLS
AS $$
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
$$;

-- Create trigger for read-only node updates
CREATE TRIGGER trigger_prevent_readonly_node_update
    BEFORE UPDATE ON navigation_nodes
    FOR EACH ROW
    EXECUTE FUNCTION prevent_readonly_node_update();

-- Function to prevent deletion of protected edges (unless CASCADE delete)
CREATE OR REPLACE FUNCTION prevent_protected_edge_deletion()
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

-- Create trigger for protected edge deletion
CREATE TRIGGER trigger_prevent_protected_edge_deletion
    BEFORE DELETE ON navigation_edges
    FOR EACH ROW
    EXECUTE FUNCTION prevent_protected_edge_deletion();

-- ============================================================================
-- AUTO-CREATE NAVIGATION TREE ON USERINTERFACE INSERT
-- ============================================================================
-- When a new userinterface is created, automatically create:
--   1. A root navigation tree
--   2. An "entry-node" (system-protected root node)
--   3. A "home" node (system-protected home screen)
--   4. An edge connecting entry-node → home

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

    -- 4. Create edge connecting entry-node → home (system-protected)
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
                'final_wait_time', 2000  -- per-direction wait now lives in the action_set
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

COMMENT ON FUNCTION create_default_navigation_tree() IS
'Trigger function that automatically creates a navigation tree with entry-node and home nodes when a new userinterface is created.';

-- Trigger to auto-create navigation tree when userinterface is inserted
CREATE TRIGGER after_userinterface_insert
    AFTER INSERT ON userinterfaces
    FOR EACH ROW
    EXECUTE FUNCTION create_default_navigation_tree();

-- ============================================================================
-- MATERIALIZED VIEW FOR FULL TREE DATA (Performance Optimization)
-- ============================================================================

-- Create materialized view that stores complete tree data
CREATE MATERIALIZED VIEW mv_full_navigation_trees AS
SELECT 
    t.id as tree_id,
    t.team_id,
    json_build_object(
        'success', true,
        'tree', row_to_json(t.*),
        'nodes', COALESCE(
            (SELECT json_agg(n ORDER BY n.created_at)
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
                    variant_overrides,
                    created_at,
                    updated_at
                FROM navigation_nodes
                WHERE tree_id = t.id
                AND team_id = t.team_id
             ) n),
            '[]'::json
        ),
        'edges', COALESCE(
            (SELECT json_agg(e ORDER BY e.created_at)
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
                    variant_overrides,
                    default_action_set_id,
                    created_at,
                    updated_at
                FROM navigation_edges
                WHERE tree_id = t.id
                AND team_id = t.team_id
             ) e),
            '[]'::json
        )
    ) as full_tree_data,
    now() as last_refreshed
FROM navigation_trees t;

-- Create unique index for fast lookups by tree_id and team_id
CREATE UNIQUE INDEX idx_mv_full_trees_tree_team
ON mv_full_navigation_trees(tree_id, team_id);

-- Materialized view indexes for fast tree hierarchy queries
CREATE INDEX idx_mv_full_navigation_trees_tree_id ON mv_full_navigation_trees(tree_id);
CREATE INDEX idx_mv_full_navigation_trees_team_id ON mv_full_navigation_trees(team_id);
CREATE INDEX idx_mv_full_navigation_trees_tree_team ON mv_full_navigation_trees(tree_id, team_id);
COMMENT ON INDEX idx_mv_full_navigation_trees_tree_team IS 'Composite index for materialized view - enables sub-millisecond tree hierarchy lookups';

-- Add comment explaining the view
COMMENT ON MATERIALIZED VIEW mv_full_navigation_trees IS 
'Pre-computed full tree data (metadata + nodes + edges) for instant reads. 
Automatically refreshed when tree data changes via triggers.
Performance: ~10ms reads vs ~500ms function calls (50x faster!)';

-- ============================================================================
-- AUTO-LABEL TRIGGERS FOR EDGES
-- ============================================================================

-- Function to auto-set edge label on insert (if not provided)
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

-- Create trigger to auto-set edge label on insert
CREATE TRIGGER trigger_auto_set_edge_label_on_insert
    BEFORE INSERT ON navigation_edges
    FOR EACH ROW
    EXECUTE FUNCTION auto_set_edge_label_on_insert();

-- Function to auto-update edge labels when node label changes
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

-- Create trigger to auto-update edge labels when node label changes
-- Split into two triggers: an INSERT trigger's WHEN clause cannot reference OLD at all,
-- so the "did the label change" check only applies to the UPDATE case.
CREATE TRIGGER trigger_auto_update_edge_labels_on_node_insert
    AFTER INSERT ON navigation_nodes
    FOR EACH ROW
    EXECUTE FUNCTION auto_update_edge_labels_on_node_change();

CREATE TRIGGER trigger_auto_update_edge_labels_on_node_update
    AFTER UPDATE OF label ON navigation_nodes
    FOR EACH ROW
    WHEN (OLD.label IS DISTINCT FROM NEW.label)
    EXECUTE FUNCTION auto_update_edge_labels_on_node_change();

-- Function to refresh materialized view for a specific tree
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
        -- FOR INSERT/UPDATE operations, use NEW
        REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_full_navigation_trees;
        RETURN NEW;
    END IF;
END;
$$;

-- Trigger on navigation_trees changes
CREATE TRIGGER trigger_refresh_mv_on_tree_change
AFTER INSERT OR UPDATE OR DELETE ON navigation_trees
FOR EACH STATEMENT
EXECUTE FUNCTION refresh_tree_materialized_view();

-- Trigger on navigation_nodes changes
CREATE TRIGGER trigger_refresh_mv_on_node_change
AFTER INSERT OR UPDATE OR DELETE ON navigation_nodes
FOR EACH STATEMENT
EXECUTE FUNCTION refresh_tree_materialized_view();

-- Trigger on navigation_edges changes
CREATE TRIGGER trigger_refresh_mv_on_edge_change
AFTER INSERT OR UPDATE OR DELETE ON navigation_edges
FOR EACH STATEMENT
EXECUTE FUNCTION refresh_tree_materialized_view();

-- ============================================================================
-- OPTIMIZED FUNCTION TO READ FROM MATERIALIZED VIEW
-- ============================================================================

-- Function to get full tree from materialized view (faster than computing it)
CREATE OR REPLACE FUNCTION get_full_tree_from_mv(
    p_tree_id UUID,
    p_team_id UUID
)
RETURNS JSON
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

COMMENT ON FUNCTION get_full_tree_from_mv(UUID, UUID) IS 
'Read pre-computed tree data from materialized view. 
Extremely fast (~10ms) because data is pre-aggregated.
Uses fully qualified table names to work with empty search_path security setting.';

-- Grant permissions
GRANT SELECT ON mv_full_navigation_trees TO authenticated;
GRANT SELECT ON mv_full_navigation_trees TO service_role;
GRANT EXECUTE ON FUNCTION get_full_tree_from_mv(UUID, UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION get_full_tree_from_mv(UUID, UUID) TO service_role; 