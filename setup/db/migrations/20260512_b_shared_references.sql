-- 20260512 — Add `shared` flag to verifications_references.
--
-- A reference saved under userinterface X with shared=true is visible AND
-- editable by any userinterface Y in the same team whose userinterfaces.models[]
-- intersects X's models[]. Visibility resolution is done server-side in
-- backend_server/src/services/verification_service.py (compatible_ui_names set).
--
-- One canonical row per reference — there is no duplication. Editing a shared
-- ref updates the single row for every userinterface that sees it.
--
-- Uniqueness:
--   * Local rows: unique within (team_id, name, userinterface_name, reference_type)
--   * Shared rows: unique within (team_id, name, reference_type) — globally per team
-- A partial-index pair enforces both without conflicting with each other.

BEGIN;

ALTER TABLE public.verifications_references
  ADD COLUMN IF NOT EXISTS shared BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN public.verifications_references.shared IS
'When true, this reference is visible+editable by every userinterface in the team
 whose models[] intersects with the origin userinterface_name''s models[]. The
 userinterface_name column still records the origin UI. There is no row
 duplication — edits write back to this single row.';

-- Replace the old unique constraint with two partial unique indexes so the
-- uniqueness rule differs for local vs shared rows.
ALTER TABLE public.verifications_references
  DROP CONSTRAINT IF EXISTS verifications_references_team_id_name_userinterface_reference_key;

DROP INDEX IF EXISTS verifications_references_local_unique;
DROP INDEX IF EXISTS verifications_references_shared_unique;

CREATE UNIQUE INDEX verifications_references_local_unique
  ON public.verifications_references (team_id, name, userinterface_name, reference_type)
  WHERE shared = FALSE;

CREATE UNIQUE INDEX verifications_references_shared_unique
  ON public.verifications_references (team_id, name, reference_type)
  WHERE shared = TRUE;

CREATE INDEX IF NOT EXISTS idx_verifications_references_shared
  ON public.verifications_references (team_id, shared)
  WHERE shared = TRUE;

COMMIT;

SELECT '20260512_b_shared_references.sql applied' AS status;
