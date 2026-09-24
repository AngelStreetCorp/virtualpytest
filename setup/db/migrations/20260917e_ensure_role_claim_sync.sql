-- 20260917e_ensure_role_claim_sync.sql
-- TASK-22. Canonical: setup/db/schema/018_supabase_auth_schema.sql (this is that file's
-- role-sync half, applied to a database that predates it or lost it).
--
-- **Run this BEFORE deploying the viewer read-only floor to any instance.**
--
-- The floor reads the role from the JWT's app_metadata claim, which only exists because
-- on_profile_role_sync copies profiles.role into auth.users.raw_app_meta_data. Where that
-- trigger is missing, auth_middleware falls back to 'viewer' — fail-closed, which is the
-- right default, but it means an **admin with no claim is treated as a viewer and loses
-- every write**. Found on node3 2026-09-17: the trigger was absent and two of its three
-- admins had a NULL claim, so deploying the floor there locked them out until this ran.
--
-- Idempotent: CREATE OR REPLACE + DROP/CREATE TRIGGER, and the backfill only writes rows
-- whose claim does not already match.
BEGIN;

CREATE OR REPLACE FUNCTION public.sync_profile_role_to_auth()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE auth.users
  SET raw_app_meta_data =
        COALESCE(raw_app_meta_data, '{}'::jsonb)
        || jsonb_build_object('role', NEW.role)
  WHERE id = NEW.id;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_profile_role_sync ON public.profiles;
CREATE TRIGGER on_profile_role_sync
  AFTER INSERT OR UPDATE OF role ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.sync_profile_role_to_auth();

-- Backfill every account whose claim is missing or stale. Without this the trigger only
-- helps accounts created or re-roled after it existed, and today's admins stay locked out.
UPDATE auth.users u
SET raw_app_meta_data =
      COALESCE(u.raw_app_meta_data, '{}'::jsonb) || jsonb_build_object('role', p.role)
FROM public.profiles p
WHERE p.id = u.id
  AND p.role IS NOT NULL
  AND COALESCE(u.raw_app_meta_data->>'role', '') IS DISTINCT FROM p.role;

COMMIT;
