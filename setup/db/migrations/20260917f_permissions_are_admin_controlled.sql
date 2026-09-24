-- 20260917f_permissions_are_admin_controlled.sql
-- TASK-22. Canonical: setup/db/schema/018_supabase_auth_schema.sql (role-sync half).
-- **Run this BEFORE deploying the matching code**, same as 20260917e.
--
-- `auth_middleware` read a user's fine-grained permissions from the JWT's
-- **user_metadata**, which the user writes themselves — `signUp({options:{data}})` at
-- registration, or `PUT /auth/v1/user` at any time afterwards. require_permission()
-- unions that list into what the caller is allowed, so any account could grant itself
-- arbitrary permission strings. Demonstrated 2026-09-17: a signup carrying
-- {"role":"admin","permissions":["execution.run:run_test"]} stored both verbatim in
-- raw_user_meta_data.
--
-- Permissions are an administrative decision, so they must travel in **app_metadata**,
-- which only this SECURITY DEFINER trigger writes — exactly as `role` already does.
-- After this, the only way to change a user's permissions is through the admin-gated
-- /server/users route on the service role.
--
-- Idempotent.
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
        || jsonb_build_object(
             'role',               NEW.role,
             'permissions',        COALESCE(NEW.permissions, '[]'::jsonb),
             'denied_permissions', COALESCE(NEW.denied_permissions, '[]'::jsonb)
           )
  WHERE id = NEW.id;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_profile_role_sync ON public.profiles;
CREATE TRIGGER on_profile_role_sync
  AFTER INSERT OR UPDATE OF role, permissions, denied_permissions ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.sync_profile_role_to_auth();

-- Backfill: every account's app_metadata now carries the administrative truth.
UPDATE auth.users u
SET raw_app_meta_data =
      COALESCE(u.raw_app_meta_data, '{}'::jsonb)
      || jsonb_build_object(
           'role',               p.role,
           'permissions',        COALESCE(p.permissions, '[]'::jsonb),
           'denied_permissions', COALESCE(p.denied_permissions, '[]'::jsonb)
         )
FROM public.profiles p
WHERE p.id = u.id;

-- Strip the self-asserted copies. The code no longer reads them, but leaving a
-- `"role": "admin"` sitting in a user's own metadata is a landmine for whoever next
-- reintroduces a fallback. full_name / email / avatar_url are left untouched.
UPDATE auth.users
SET raw_user_meta_data = (raw_user_meta_data - 'role' - 'permissions' - 'denied_permissions')
WHERE raw_user_meta_data ?| array['role','permissions','denied_permissions'];

COMMIT;
