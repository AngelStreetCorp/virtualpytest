-- VirtualPyTest — dev/prod versioning of userinterfaces.
--
-- A userinterface now has a lifecycle mode: 'dev' (editable, the default — every
-- pre-existing row) or 'prod' (a published snapshot, read-only in the editor).
-- Publishing dev -> prod deep-copies the graph on first publish, then syncs
-- IN PLACE on republish so the prod trees keep their ids and all tree_id-keyed
-- history (edge_metrics / node_metrics / execution_results / KPI trends)
-- survives across publishes.
--
-- Linkage: prod rows point at their dev source via dev_userinterface_id
-- (CASCADE — deleting the dev interface removes its prod snapshot). Dev rows
-- have NULL linkage. At most one prod per dev (partial unique index). The
-- prod row keeps the SAME name as its dev source; name disambiguation is by
-- mode everywhere (get_userinterface_by_name is mode-aware).
--
-- navigation_trees.published_from_tree_id maps each prod tree back to the dev
-- tree it was published from. Deliberately NO FK: a dangling value simply means
-- "this subtree no longer exists in dev" on the next republish diff, which is
-- exactly the removal signal the publisher needs — an FK would only add
-- cross-mode cascade work on every dev-tree delete.
--
-- Depends on: 002_ui_navigation_tables.sql (userinterfaces, navigation_trees).
-- Canonical for fresh installs; the dated migration for existing DBs is
-- setup/db/migrations/20260723_userinterface_dev_prod.sql.

-- ==============================================================================
-- 1. userinterfaces: mode + prod->dev linkage + publish bookkeeping
-- ==============================================================================

ALTER TABLE public.userinterfaces
    ADD COLUMN IF NOT EXISTS mode text NOT NULL DEFAULT 'dev',
    ADD COLUMN IF NOT EXISTS dev_userinterface_id uuid
        REFERENCES public.userinterfaces(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS published_at timestamptz,
    ADD COLUMN IF NOT EXISTS published_version integer;

DO $$ BEGIN
    ALTER TABLE public.userinterfaces
        ADD CONSTRAINT check_userinterfaces_mode CHECK (mode IN ('dev', 'prod'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- dev rows have no linkage; prod rows must point at their dev source
DO $$ BEGIN
    ALTER TABLE public.userinterfaces
        ADD CONSTRAINT check_userinterfaces_mode_linkage CHECK (
            (mode = 'dev'  AND dev_userinterface_id IS NULL) OR
            (mode = 'prod' AND dev_userinterface_id IS NOT NULL));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- at most ONE prod snapshot per dev interface
CREATE UNIQUE INDEX IF NOT EXISTS uq_userinterfaces_one_prod_per_dev
    ON public.userinterfaces(dev_userinterface_id) WHERE mode = 'prod';

COMMENT ON COLUMN public.userinterfaces.mode IS
'dev = editable working copy (default, all pre-existing rows); prod = published read-only snapshot';
COMMENT ON COLUMN public.userinterfaces.dev_userinterface_id IS
'On prod rows: the dev interface this snapshot was published from. NULL on dev rows.';
COMMENT ON COLUMN public.userinterfaces.published_version IS
'On prod rows: increments on every publish (1 = first publish).';

-- ==============================================================================
-- 2. navigation_trees: dev tree -> prod tree mapping, stamped at publish time
-- ==============================================================================

ALTER TABLE public.navigation_trees
    ADD COLUMN IF NOT EXISTS published_from_tree_id uuid;

CREATE INDEX IF NOT EXISTS idx_navigation_trees_published_from
    ON public.navigation_trees(published_from_tree_id)
    WHERE published_from_tree_id IS NOT NULL;

COMMENT ON COLUMN public.navigation_trees.published_from_tree_id IS
'On prod trees: id of the dev tree this was published from. No FK on purpose —
 a dangling value means the dev subtree was deleted, which the republish diff
 treats as "remove this prod subtree".';

-- ==============================================================================
-- 3. userinterface_publishes: publish log ("prod has its own history")
-- ==============================================================================

CREATE TABLE IF NOT EXISTS public.userinterface_publishes (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id               uuid NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    dev_userinterface_id  uuid NOT NULL REFERENCES public.userinterfaces(id) ON DELETE CASCADE,
    prod_userinterface_id uuid NOT NULL REFERENCES public.userinterfaces(id) ON DELETE CASCADE,
    version               integer NOT NULL,
    published_by          uuid,
    trees_count           integer,
    nodes_count           integer,
    edges_count           integer,
    variants_count        integer,
    references_count      integer,
    trees_created         integer DEFAULT 0,
    trees_deleted         integer DEFAULT 0,
    created_at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (prod_userinterface_id, version)
);

CREATE INDEX IF NOT EXISTS idx_userinterface_publishes_dev
    ON public.userinterface_publishes(dev_userinterface_id, version DESC);

ALTER TABLE public.userinterface_publishes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "userinterface_publishes_open_access" ON public.userinterface_publishes;
CREATE POLICY "userinterface_publishes_open_access" ON public.userinterface_publishes
FOR ALL
TO public
USING (true);
-- (Match the lax 'open_access' policy on userinterface_variants; tighten later.)

COMMENT ON TABLE public.userinterface_publishes IS
'One row per dev->prod publish of a userinterface: version counter, who/when,
 and content counts at publish time. This is prod''s own history.';

-- ==============================================================================
-- 4. verifications_references: dev + prod rows share a userinterface_name
-- ==============================================================================
-- The legacy name-based local-uniqueness index (004) would reject the publish
-- reference copy: prod rows carry the SAME name and userinterface_name as their
-- dev source, differing only in userinterface_id. Narrow the name index to
-- legacy rows whose userinterface_id was never backfilled, and make the id-based
-- index (introduced by migration 20260624_ui_variant_id_keying for existing DBs)
-- canonical here for fresh installs.

DROP INDEX IF EXISTS verifications_references_local_unique;
CREATE UNIQUE INDEX IF NOT EXISTS verifications_references_local_unique
    ON public.verifications_references (team_id, name, userinterface_name, reference_type)
    WHERE shared = false AND userinterface_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS verifications_references_local_unique_id
    ON public.verifications_references (team_id, name, userinterface_id, reference_type)
    WHERE shared = false AND userinterface_id IS NOT NULL;
