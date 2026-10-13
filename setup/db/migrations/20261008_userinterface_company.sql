-- 20261008_userinterface_company.sql
-- Free-text `company` metadata on userinterfaces.
--
-- WHY THIS EXISTS
--   A userinterface (e.g. 'brand_a_app', 'brand_b_v3', 'brand_c_tv') can be
--   shipped by one of many companies, and brand-specific OCR keywords benefit
--   from a confidence boost when the matched text on a frame agrees with the
--   UI's company. A 'BRAND_A' token on a brand_a userinterface is a strong
--   splash/login candidate; the same token on a brand_b userinterface is
--   noise. Until now the only signal was the UI's name, and names do not
--   always include the company (e.g. 'stb3_home' is a generic STB home
--   screen shipped under one of the brands).
--
-- SHAPE
--   `company` is a short, NULLABLE free-text label. NULL = unknown company,
--   treated as today (no boost, no change in behaviour). It is NOT a
--   foreign key, NOT normalized, NOT a vendor registry: this is metadata an
--   editor types in once, the same way `min_version` / `max_version` are.
--
-- EXAMPLES
--   'brand_a', 'brand_b', 'brand_c', 'brand_d', 'brand_e', 'brand_f',
--   'brand_g', 'brand_h', 'brand_i', 'brand_j'.
--
-- WHAT THIS MIGRATION DOES NOT DO
--   Does not rename any existing field. Does not enforce uniqueness
--   (two UIs may share a company). Does not backfill values — NULL is the
--   safe default and any pre-existing company inference must run as a
--   separate job.

BEGIN;

ALTER TABLE public.userinterfaces
    ADD COLUMN IF NOT EXISTS company text;

-- Optional index — only the lookup path that powers a future "all
-- UIs for company X" page needs this. Cheap to keep even at zero rows
-- today, and the column is NULL for every pre-existing row so the
-- index is a one-page btree until editors start filling it in.
CREATE INDEX IF NOT EXISTS idx_userinterfaces_company
    ON public.userinterfaces (company)
    WHERE company IS NOT NULL;

COMMIT;
