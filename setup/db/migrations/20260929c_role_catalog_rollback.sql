-- 20260929c_role_catalog_rollback.sql
-- Inverse of 20260929c_role_catalog.sql.
--
-- ⚠ Users holding the manager or developer role are moved to tester first, because the
-- restored CHECK only allows admin / tester / viewer. Their role defaults and every alias are
-- lost. Deploy the matching older code before, or together with, this rollback.

BEGIN;

UPDATE public.profiles SET role = 'tester' WHERE role IN ('manager', 'developer');
DELETE FROM public.role_permissions WHERE role IN ('manager', 'developer');

ALTER TABLE public.role_permissions DROP CONSTRAINT IF EXISTS role_permissions_role_check;
ALTER TABLE public.role_permissions DROP CONSTRAINT IF EXISTS role_permissions_role_fkey;
ALTER TABLE public.role_permissions
    ADD CONSTRAINT role_permissions_role_check CHECK (role IN ('tester', 'viewer'));

ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_role_fkey;
ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_role_check;
ALTER TABLE public.profiles
    ADD CONSTRAINT profiles_role_check CHECK (role IN ('admin', 'tester', 'viewer'));

DROP TABLE IF EXISTS public.role_aliases;
DROP TABLE IF EXISTS public.roles;

COMMIT;
