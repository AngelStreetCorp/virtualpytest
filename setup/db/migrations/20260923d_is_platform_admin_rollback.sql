-- 20260923d_is_platform_admin_rollback.sql
-- Inverse of 20260923d. Drops the is_platform_admin column. No data is lost
-- other than the flag itself (defaults back to "no super admins exist").

BEGIN;

ALTER TABLE public.profiles
  DROP COLUMN IF EXISTS is_platform_admin;

COMMIT;