-- 20260915b_profiles_backfill_blank_full_name.sql
-- OPTIONAL one-time pass, split out of 20260915_profiles_provider_type_and_default_full_name.sql
-- so that migration only changes future behaviour and never rewrites rows on its own.
--
-- Gives every profile that has no name today the same default new ones now get: the local
-- part of the email (marie.dupont@example.com -> marie.dupont). Profiles that already have
-- a name are untouched — this only fills blanks, so it is safe to re-run.
--
-- Preview what it would change before running it:
--   SELECT id, email FROM public.profiles
--    WHERE COALESCE(btrim(full_name), '') = '' AND COALESCE(btrim(email), '') <> '';

BEGIN;

UPDATE public.profiles
SET full_name = split_part(email, '@', 1)
WHERE COALESCE(btrim(full_name), '') = ''
  AND COALESCE(btrim(email), '') <> '';

COMMIT;
