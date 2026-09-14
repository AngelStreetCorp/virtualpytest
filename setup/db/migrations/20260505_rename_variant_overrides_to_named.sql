-- Migration: switch variant_overrides JSONB to the named-variant shape and add the registry.
-- Date: 2026-05-05
-- Companion to schema/034_node_edge_variant_overrides.sql (rewritten in place for fresh installs).
-- See docs/agent/ENHANCE_VARIANT.md §5.
--
-- Wipe-and-recreate strategy: the old {match: {locale, platform}} shape is dropped entirely.
-- Live data audited 2026-05-05 had 12 nodes / 0 edges with non-empty overrides — none preserved.
-- Authors recreate variants via the new /variants endpoint after this migration runs.

BEGIN;

-- 1. Wipe every existing variant_overrides JSONB. No data preserved.
UPDATE public.navigation_nodes  SET variant_overrides = '[]'::jsonb
  WHERE variant_overrides <> '[]'::jsonb;
UPDATE public.navigation_edges  SET variant_overrides = '[]'::jsonb
  WHERE variant_overrides <> '[]'::jsonb;

-- 2. Create the registry table (idempotent — same DDL as schema/034 above).
CREATE TABLE IF NOT EXISTS public.userinterface_variants (
    team_id          uuid        NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    userinterface_id uuid        NOT NULL REFERENCES public.userinterfaces(id) ON DELETE CASCADE,
    name             text        NOT NULL CHECK (name <> '__base__' AND name ~ '^[a-zA-Z0-9._-]{1,64}$'),
    description      text        DEFAULT '',
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, userinterface_id, name)
);

CREATE INDEX IF NOT EXISTS idx_userinterface_variants_ui
    ON public.userinterface_variants(userinterface_id);

ALTER TABLE public.userinterface_variants ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "userinterface_variants_open_access" ON public.userinterface_variants;
CREATE POLICY "userinterface_variants_open_access" ON public.userinterface_variants
FOR ALL
TO public
USING (true);

-- 3. Refresh MV so REST API readers see the wiped JSONB.
REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_full_navigation_trees;

COMMIT;

-- After applying, reload the PostgREST schema cache so the new table is visible to the REST API:
--   ssh database "echo \$SUDO_PASSWORD | sudo -S docker restart supabase_rest_supabase"
