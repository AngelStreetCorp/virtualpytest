-- Stable-ID keying for UserInterface & Variant references.
--
-- Problem: renaming a userinterface or variant breaks verification references
-- (they vanish) and orphans the MinIO/R2 objects, because the *mutable name* is
-- the operational key for both reference lookups and storage paths.
--
-- This migration makes a stable UUID the key:
--   * userinterface_variants gains a stable `id` (today its identity IS the name).
--   * verifications_references.userinterface_id (already present, optional) is
--     backfilled from the name and gets an id-based uniqueness index, so lookups
--     can move from userinterface_name -> userinterface_id.
--
-- The R2 object relocation (name-path -> id-path) is done by the companion
-- backfill script (cannot be expressed in SQL). Past analytics rows
-- (script_results / execution_results.variant / *_metrics) are intentionally
-- left name-based — history continuity is out of scope.
--
-- Idempotent: safe to re-run. Apply per docs/agent/infra/DATABASE.md, then reload PostgREST.

BEGIN;

-- ============================================================================
-- A. userinterface_variants: add a stable id (name becomes a display label)
-- ============================================================================
-- Nothing FK-references this table, so adding an alternate stable key is safe.
-- We keep the existing composite PK (team_id, userinterface_id, name) for now —
-- it still enforces name-uniqueness — and add `id` as a UNIQUE alternate key
-- that downstream code uses as the rename-stable handle.

ALTER TABLE public.userinterface_variants
    ADD COLUMN IF NOT EXISTS id uuid NOT NULL DEFAULT gen_random_uuid();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'userinterface_variants_id_key'
    ) THEN
        ALTER TABLE public.userinterface_variants
            ADD CONSTRAINT userinterface_variants_id_key UNIQUE (id);
    END IF;
END $$;

COMMENT ON COLUMN public.userinterface_variants.id IS
'Stable UUID identity for the variant. Rename-safe key used by cache/composition/
 resolution. `name` is a mutable display label.';

-- ============================================================================
-- B. verifications_references: key by userinterface_id instead of name
-- ============================================================================
-- userinterface_id already exists (nullable). Backfill it from the current name
-- so the operational lookup can switch to the id.

UPDATE public.verifications_references vr
SET    userinterface_id = ui.id
FROM   public.userinterfaces ui
WHERE  vr.userinterface_id IS NULL
  AND  vr.team_id          = ui.team_id
  AND  vr.userinterface_name = ui.name;

-- Id-based local-uniqueness index, alongside the existing name-based one. The
-- name index stays during transition for any legacy row whose id is still NULL.
CREATE UNIQUE INDEX IF NOT EXISTS verifications_references_local_unique_id
    ON public.verifications_references (team_id, name, userinterface_id, reference_type)
    WHERE shared = false AND userinterface_id IS NOT NULL;

COMMENT ON COLUMN public.verifications_references.userinterface_id IS
'PRIMARY operational key (rename-stable). Lookups filter by this; userinterface_name
 is now denormalized display/debug only. r2_path/r2_url move to id-based paths via
 the companion backfill script.';

COMMIT;
