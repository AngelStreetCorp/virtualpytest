-- G2/G3 (2026-10-17): preserve the complete v6 image fingerprint for a live
-- unknown screen.
--
-- The live matcher already computes dhash/regions/crop/focus; on an abstention
-- it can also compute the full v6 blob (which adds the OCR title/text). Storing
-- it here lets the auto-classify proposal carry the same fingerprint a captured
-- node has, so an accepted unknown screen is as strong as a normal node.
--
-- Existing rows keep NULL: identify_screen reads a dhash-only fingerprint
-- through its v4 fallback, so nothing breaks. The column is additive and the
-- matcher never reads it; screen_memory.match_screen still uses dhash +
-- region_center (region_center is now filled from regions.center when known).

BEGIN;

ALTER TABLE public.screen_fingerprints
    ADD COLUMN IF NOT EXISTS fingerprint jsonb;

COMMENT ON COLUMN public.screen_fingerprints.fingerprint IS
    'Full v6 image fingerprint (v, dhash, regions, crop, focus, title, text) of the sampling frame. '
    'NULL on legacy rows; screen_memory.match_screen reads dhash/region_center only.';

COMMIT;
