-- 20260923h_extend_role_sync_trigger_to_platform_admin.sql
-- TASK-23 — Extend the on_profile_role_sync trigger (from 20260917g) so it also
-- fires on changes to is_platform_admin. Without this, promoting a user to
-- super admin via UPDATE public.profiles SET is_platform_admin = true does NOT
-- sync the claim to their JWT — the bootstrap script had to call
-- public.sync_user_claims_to_auth() explicitly. After this migration, future
-- promotions auto-sync.
--
-- Idempotent. Drops + re-creates the trigger; the function body is unchanged
-- (sync_user_claims_to_auth already reads is_platform_admin after 20260923g).

DROP TRIGGER IF EXISTS on_profile_role_sync ON public.profiles;

CREATE TRIGGER on_profile_role_sync
  AFTER INSERT OR UPDATE OF role, permissions, denied_permissions, team_id,
                          is_platform_admin
  ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.sync_profile_role_to_auth();