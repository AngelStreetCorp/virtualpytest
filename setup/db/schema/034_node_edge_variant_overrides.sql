-- Migration 034: Per-variant full overrides on userinterface_variants
-- Date: 2026-04-29 (rewritten 2026-05-05 + 2026-05-12 — full-override model, no patches)
-- Description: Variant data lives on userinterface_variants.{node_overrides, edge_overrides}
--              keyed by node_id / edge_id. Each entry FULLY REPLACES the base row's content
--              for that variant (`verifications` for nodes, `action_sets` for edges).
--              There is no patch / param-merge layer.
--              Base navigation_nodes/edges rows stay clean (no variant_overrides column).
--              Each row carries a `hidden_in_base` boolean that hides it from base runs
--              (variant-only rows).
--              Also rebuilds mv_full_navigation_trees to expose the new shape and updates
--              the bidirectional parent<->subtree sync triggers (006) to mirror
--              `hidden_in_base` between root and subtree node duplicates.
--              See docs/agent/navigation/VARIANT.md for the full design.

-- ==============================================================================
-- 1. ADD hidden_in_base ON BOTH node/edge TABLES (idempotent)
-- ==============================================================================

ALTER TABLE public.navigation_nodes
    ADD COLUMN IF NOT EXISTS hidden_in_base boolean NOT NULL DEFAULT false;

ALTER TABLE public.navigation_edges
    ADD COLUMN IF NOT EXISTS hidden_in_base boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.navigation_nodes.hidden_in_base IS
'True when this row is invisible to base runs (variant-only). Variants that
 should not see the row carry a {disabled: true} entry under their own
 node_overrides[node_id]. See docs/agent/navigation/VARIANT.md.';

COMMENT ON COLUMN public.navigation_edges.hidden_in_base IS
'True when this edge is invisible to base runs (variant-only). Variants that
 should not see the edge carry a {disabled: true} entry under their own
 edge_overrides[edge_id]. See docs/agent/navigation/VARIANT.md.';

-- Drop the materialized view first — it selects variant_overrides, so it must go before the
-- column drop below or Postgres refuses with "other objects depend on it". Recreated in
-- section 2 with the new shape.
DROP MATERIALIZED VIEW IF EXISTS public.mv_full_navigation_trees;

-- Drop the old per-row JSONB column (renamed model — data lives on the variant row).
ALTER TABLE public.navigation_nodes  DROP COLUMN IF EXISTS variant_overrides;
ALTER TABLE public.navigation_edges  DROP COLUMN IF EXISTS variant_overrides;

-- ==============================================================================
-- 2. REBUILD MATERIALIZED VIEW TO EXPOSE hidden_in_base (drop variant_overrides)
-- ==============================================================================

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

-- Recreate unique index needed for REFRESH CONCURRENTLY.
CREATE UNIQUE INDEX idx_mv_full_trees_tree_team
ON public.mv_full_navigation_trees(tree_id, team_id);

-- Recreate the secondary indexes on the MV (originally in 002).
CREATE INDEX idx_mv_full_navigation_trees_tree_id ON public.mv_full_navigation_trees(tree_id);
CREATE INDEX idx_mv_full_navigation_trees_team_id ON public.mv_full_navigation_trees(team_id);
CREATE INDEX idx_mv_full_navigation_trees_tree_team ON public.mv_full_navigation_trees(tree_id, team_id);

COMMENT ON MATERIALIZED VIEW public.mv_full_navigation_trees IS
'Pre-computed full tree data (metadata + nodes + edges incl. hidden_in_base) for instant reads. Auto-refreshed via triggers on writes. Performance: ~10ms reads.';

-- Initial populate.
REFRESH MATERIALIZED VIEW public.mv_full_navigation_trees;

-- ==============================================================================
-- 3. EXTEND THE BIDIRECTIONAL SYNC FUNCTIONS (006) TO MIRROR hidden_in_base
-- ==============================================================================
-- Same shape as 006, only the SET clauses and WHEN conditions are extended.

-- NOTE: navigation_nodes does NOT have a userinterface_id column. Resolve it
-- from navigation_trees via NEW.tree_id; using NEW.userinterface_id here would
-- compile (PL/pgSQL is lazy-parsed) but error at runtime on any UPDATE that
-- touches a node referenced by a subtree.
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

-- ==============================================================================
-- 4. EXTEND TRIGGER WHEN-CLAUSES TO FIRE ON hidden_in_base CHANGES
-- ==============================================================================

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
-- 5. USERINTERFACE_VARIANTS REGISTRY + per-variant override JSONB columns
-- ==============================================================================
-- Single source of truth for what variant names exist per userinterface, AND
-- where every per-variant override lives (keyed by node_id / edge_id).
--
-- node_overrides shape:
--   { "<node_id>": { "disabled"?: bool,
--                    "verifications"?: [<Verification>, ...] } }
-- edge_overrides shape:
--   { "<edge_id>": { "disabled"?: bool,
--                    "action_sets"?:  [<ActionSet>,    ...] } }
-- A row's `disabled: true` and presence of the full-override field are mutually
-- exclusive at the validator level. When the override field is absent and
-- disabled is not true, the entry is a no-op (fall-through to base).

CREATE TABLE IF NOT EXISTS public.userinterface_variants (
    team_id          uuid        NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    userinterface_id uuid        NOT NULL REFERENCES public.userinterfaces(id) ON DELETE CASCADE,
    name             text        NOT NULL CHECK (name ~ '^[a-z0-9._-]{1,64}$'),
    description      text        DEFAULT '',
    node_overrides   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    edge_overrides   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, userinterface_id, name)
);

-- Idempotently add the override columns when this file is rerun against an
-- already-created table from an older revision of 034.
ALTER TABLE public.userinterface_variants
    ADD COLUMN IF NOT EXISTS node_overrides jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.userinterface_variants
    ADD COLUMN IF NOT EXISTS edge_overrides jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_userinterface_variants_ui
    ON public.userinterface_variants(userinterface_id);

ALTER TABLE public.userinterface_variants ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "userinterface_variants_open_access" ON public.userinterface_variants;
CREATE POLICY "userinterface_variants_open_access" ON public.userinterface_variants
FOR ALL
TO public
USING (true);
-- (Match the lax 'open_access' policy on the userinterfaces table itself; tighten later.)

COMMENT ON TABLE public.userinterface_variants IS
'Registered variant names per userinterface. Carries every per-variant override
 in node_overrides / edge_overrides JSONB (keyed by node_id / edge_id). Base
 navigation_nodes / navigation_edges rows stay pure — variant-only rows are
 marked via the boolean hidden_in_base column on those tables.';

COMMENT ON COLUMN public.userinterface_variants.node_overrides IS
'Map keyed by navigation_nodes.node_id. Each entry: {disabled?: bool, verifications?: <Verification>[]}.
 disabled=true and verifications are mutually exclusive (server-validated).
 When verifications is present it FULLY REPLACES the base row''s verifications
 for this variant. There is no patch / param-merge layer.';

COMMENT ON COLUMN public.userinterface_variants.edge_overrides IS
'Map keyed by navigation_edges.edge_id. Each entry: {disabled?: bool, action_sets?: <ActionSet>[]}.
 disabled=true and action_sets are mutually exclusive (server-validated).
 When action_sets is present it FULLY REPLACES the base row''s action_sets for
 this variant. There is no patch / param-merge layer.';

-- ==============================================================================
-- ROLLBACK INSTRUCTIONS
-- ==============================================================================
-- DROP TABLE IF EXISTS public.userinterface_variants;
-- ALTER TABLE public.navigation_nodes DROP COLUMN IF EXISTS hidden_in_base;
-- ALTER TABLE public.navigation_edges DROP COLUMN IF EXISTS hidden_in_base;
-- (then re-run migration 002's MV definition + migration 006's triggers to restore prior shape)

SELECT 'Migration 034: hidden_in_base + per-variant overrides on userinterface_variants applied successfully' AS status;
