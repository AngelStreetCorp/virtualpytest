-- =====================================================
-- Sync profiles.role -> auth JWT app_metadata
--
-- Problem: profiles.role is the source of truth for a
-- user's role, but it was never propagated into the
-- auth token. So require_user_auth read user_metadata
-- .role (always empty) -> every real user looked like
-- 'viewer' server-side, and @require_role('admin')
-- could never pass without a per-request DB lookup.
--
-- Fix: keep auth.users.raw_app_meta_data.role in sync
-- with public.profiles.role via a trigger, and backfill
-- existing users. The role then rides in the JWT as the
-- `app_metadata` claim (server-controlled — NOT
-- user_metadata, which users can self-edit). Resolved
-- once at token mint (login/refresh), free on every
-- request thereafter.
-- =====================================================

-- Writes auth.users — must run as a privileged owner.
-- SECURITY DEFINER + the migration is applied as supabase_admin.
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

-- Fires on profile creation and whenever role changes.
-- AFTER so the profiles row is committed; the auth.users
-- row already exists (handle_new_user inserts the profile
-- after the auth.users insert).
DROP TRIGGER IF EXISTS on_profile_role_sync ON public.profiles;
CREATE TRIGGER on_profile_role_sync
  AFTER INSERT OR UPDATE OF role ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.sync_profile_role_to_auth();

-- One-time backfill for users who already have a profile.
-- Existing sessions only pick this up on next login / token
-- refresh (GoTrue mints the app_metadata claim at that point).
UPDATE auth.users u
SET raw_app_meta_data =
      COALESCE(u.raw_app_meta_data, '{}'::jsonb)
      || jsonb_build_object('role', p.role)
FROM public.profiles p
WHERE p.id = u.id
  AND COALESCE(u.raw_app_meta_data->>'role', '') IS DISTINCT FROM p.role;
