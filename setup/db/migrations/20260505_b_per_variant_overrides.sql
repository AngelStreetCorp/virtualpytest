-- 2026-05-05 (b) — Move per-variant data off node/edge rows onto userinterface_variants.
-- Companion to 20260505_rename_variant_overrides_to_named.sql; that migration
-- already wiped variant_overrides JSONB to '[]'. This migration:
--   1. Adds node_overrides / edge_overrides JSONB columns to userinterface_variants.
--   2. Adds hidden_in_base boolean column to navigation_nodes / navigation_edges.
--   3. Drops the now-unused variant_overrides columns.
--   4. Drops the legacy `name <> '__base__'` CHECK on userinterface_variants
--      (the sentinel is replaced by hidden_in_base).
--   5. Rewrites sync_parent_node_to_subtrees / sync_subtree_to_parent_node
--      so they mirror hidden_in_base instead of variant_overrides.
--   6. Rebuilds mv_full_navigation_trees with the new column set.
--   7. Refreshes the MV.
-- After this migration, reload the PostgREST schema cache:
--   ssh database "echo \$SUDO_PASSWORD | sudo -S docker restart supabase_rest_supabase"
--
-- See docs/agent/ENHANCE_VARIANT.md.

BEGIN;

-- ==============================================================================
-- 1. userinterface_variants: gain node_overrides / edge_overrides
-- ==============================================================================

ALTER TABLE public.userinterface_variants
    ADD COLUMN IF NOT EXISTS node_overrides jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.userinterface_variants
    ADD COLUMN IF NOT EXISTS edge_overrides jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.userinterface_variants.node_overrides IS
'Map keyed by navigation_nodes.node_id. Each entry: {disabled?: bool, patches?: [{verification_index, params}]}.
 disabled=true and patches are mutually exclusive (server-validated).';

COMMENT ON COLUMN public.userinterface_variants.edge_overrides IS
'Map keyed by navigation_edges.edge_id. Each entry: {disabled?: bool, patches?: [{action_set_index, action_index, params}]}.
 disabled=true and patches are mutually exclusive (server-validated).';

-- ==============================================================================
-- 2. navigation_nodes / navigation_edges: gain hidden_in_base
-- ==============================================================================

ALTER TABLE public.navigation_nodes
    ADD COLUMN IF NOT EXISTS hidden_in_base boolean NOT NULL DEFAULT false;

ALTER TABLE public.navigation_edges
    ADD COLUMN IF NOT EXISTS hidden_in_base boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.navigation_nodes.hidden_in_base IS
'True when this row is invisible to base runs (variant-only). Variants that
 should not see the row carry a {disabled: true} entry under their own
 node_overrides[node_id]. See docs/agent/ENHANCE_VARIANT.md.';

COMMENT ON COLUMN public.navigation_edges.hidden_in_base IS
'True when this edge is invisible to base runs (variant-only). Variants that
 should not see the edge carry a {disabled: true} entry under their own
 edge_overrides[edge_id]. See docs/agent/ENHANCE_VARIANT.md.';

-- ==============================================================================
-- 3. Drop dependents (MV + sync triggers) before dropping the columns.
--    The MV and the WHEN-clauses on the sync triggers reference
--    `variant_overrides`, so PostgreSQL refuses to drop the column otherwise.
-- ==============================================================================

DROP MATERIALIZED VIEW IF EXISTS public.mv_full_navigation_trees;
DROP TRIGGER IF EXISTS sync_parent_node_to_subtrees_trigger ON public.navigation_nodes;
DROP TRIGGER IF EXISTS sync_subtree_to_parent_trigger      ON public.navigation_nodes;

ALTER TABLE public.navigation_nodes  DROP COLUMN IF EXISTS variant_overrides;
ALTER TABLE public.navigation_edges  DROP COLUMN IF EXISTS variant_overrides;

-- ==============================================================================
-- 4. Drop the legacy `name <> '__base__'` CHECK (the sentinel is gone).
-- ==============================================================================
-- The constraint name varies; find every CHECK on userinterface_variants whose
-- definition still mentions __base__ and drop it. The regex CHECK
-- (~ '^[a-zA-Z0-9._-]{1,64}$') is preserved.

DO $$
DECLARE
    cons_name text;
BEGIN
    FOR cons_name IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'public.userinterface_variants'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) ILIKE '%__base__%'
    LOOP
        EXECUTE format(
            'ALTER TABLE public.userinterface_variants DROP CONSTRAINT %I',
            cons_name
        );
    END LOOP;
END
$$;

-- Make sure the regex CHECK is in place (idempotent).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.userinterface_variants'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%[a-zA-Z0-9._-]{1,64}%'
    ) THEN
        ALTER TABLE public.userinterface_variants
            ADD CONSTRAINT userinterface_variants_name_check
            CHECK (name ~ '^[a-zA-Z0-9._-]{1,64}$');
    END IF;
END
$$;

-- ==============================================================================
-- 5. Rewrite sync triggers — mirror hidden_in_base, not variant_overrides
-- ==============================================================================

CREATE OR REPLACE FUNCTION public.sync_parent_node_to_subtrees()
RETURNS TRIGGER AS $$
DECLARE
    v_userinterface_id uuid;
BEGIN
    SELECT userinterface_id INTO v_userinterface_id
    FROM public.navigation_trees WHERE id = NEW.tree_id;

    IF EXISTS(
        SELECT 1 FROM public.navigation_trees nt
        JOIN public.navigation_trees parent_tree ON nt.parent_tree_id = parent_tree.id
        WHERE nt.parent_node_id = NEW.node_id
        AND nt.team_id = NEW.team_id
        AND parent_tree.userinterface_id = v_userinterface_id
    ) THEN
        UPDATE public.navigation_nodes
        SET
            label = NEW.label,
            data = COALESCE(data, '{}'::jsonb) || jsonb_build_object(
                'screenshot', NEW.data->>'screenshot'
            ),
            verifications = NEW.verifications,
            hidden_in_base = NEW.hidden_in_base,
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
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path TO public, pg_temp;

CREATE OR REPLACE FUNCTION public.sync_subtree_to_parent_node()
RETURNS TRIGGER AS $$
DECLARE
    v_parent_tree_id UUID;
    v_parent_node_id TEXT;
    v_node_userinterface_id UUID;
    v_parent_userinterface_id UUID;
BEGIN
    SELECT userinterface_id INTO v_node_userinterface_id
    FROM public.navigation_trees WHERE id = NEW.tree_id;

    SELECT nt.parent_tree_id, nt.parent_node_id, pt.userinterface_id
    INTO v_parent_tree_id, v_parent_node_id, v_parent_userinterface_id
    FROM public.navigation_trees nt
    JOIN public.navigation_trees pt ON nt.parent_tree_id = pt.id
    WHERE nt.id = NEW.tree_id
    AND nt.team_id = NEW.team_id
    AND nt.parent_tree_id IS NOT NULL
    AND nt.parent_node_id IS NOT NULL;

    IF v_parent_tree_id IS NOT NULL AND v_parent_node_id IS NOT NULL
       AND v_parent_userinterface_id = v_node_userinterface_id THEN
        UPDATE public.navigation_nodes
        SET
            label = NEW.label,
            data = COALESCE(data, '{}'::jsonb) || jsonb_build_object(
                'screenshot', NEW.data->>'screenshot'
            ),
            verifications = NEW.verifications,
            hidden_in_base = NEW.hidden_in_base,
            updated_at = NOW()
        WHERE
            node_id = NEW.node_id
            AND tree_id = v_parent_tree_id
            AND team_id = NEW.team_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path TO public, pg_temp;

DROP TRIGGER IF EXISTS sync_parent_node_to_subtrees_trigger ON public.navigation_nodes;
CREATE TRIGGER sync_parent_node_to_subtrees_trigger
    AFTER UPDATE ON public.navigation_nodes
    FOR EACH ROW
    WHEN (
        OLD.label IS DISTINCT FROM NEW.label OR
        OLD.data IS DISTINCT FROM NEW.data OR
        OLD.verifications IS DISTINCT FROM NEW.verifications OR
        OLD.hidden_in_base IS DISTINCT FROM NEW.hidden_in_base
    )
    EXECUTE FUNCTION public.sync_parent_node_to_subtrees();

DROP TRIGGER IF EXISTS sync_subtree_to_parent_trigger ON public.navigation_nodes;
CREATE TRIGGER sync_subtree_to_parent_trigger
    AFTER UPDATE ON public.navigation_nodes
    FOR EACH ROW
    WHEN (
        OLD.label IS DISTINCT FROM NEW.label OR
        OLD.data IS DISTINCT FROM NEW.data OR
        OLD.verifications IS DISTINCT FROM NEW.verifications OR
        OLD.hidden_in_base IS DISTINCT FROM NEW.hidden_in_base
    )
    EXECUTE FUNCTION public.sync_subtree_to_parent_node();

-- ==============================================================================
-- 6. Rebuild mv_full_navigation_trees with the new column set
-- ==============================================================================

DROP MATERIALIZED VIEW IF EXISTS public.mv_full_navigation_trees;

CREATE MATERIALIZED VIEW public.mv_full_navigation_trees AS
SELECT
    t.id AS tree_id,
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
                    hidden_in_base,
                    created_at,
                    updated_at
                FROM public.navigation_nodes
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
                    hidden_in_base,
                    default_action_set_id,
                    final_wait_time,
                    created_at,
                    updated_at
                FROM public.navigation_edges
                WHERE tree_id = t.id
                AND team_id = t.team_id
             ) e),
            '[]'::json
        )
    ) AS full_tree_data,
    now() AS last_refreshed
FROM public.navigation_trees t;

CREATE UNIQUE INDEX idx_mv_full_trees_tree_team
ON public.mv_full_navigation_trees(tree_id, team_id);

CREATE INDEX idx_mv_full_navigation_trees_tree_id ON public.mv_full_navigation_trees(tree_id);
CREATE INDEX idx_mv_full_navigation_trees_team_id ON public.mv_full_navigation_trees(team_id);
CREATE INDEX idx_mv_full_navigation_trees_tree_team ON public.mv_full_navigation_trees(tree_id, team_id);

COMMENT ON MATERIALIZED VIEW public.mv_full_navigation_trees IS
'Pre-computed full tree data (metadata + nodes + edges incl. hidden_in_base) for instant reads. Auto-refreshed via triggers on writes. Performance: ~10ms reads.';

REFRESH MATERIALIZED VIEW public.mv_full_navigation_trees;

COMMIT;

-- After applying:
--   ssh database "echo \$SUDO_PASSWORD | sudo -S docker restart supabase_rest_supabase"
