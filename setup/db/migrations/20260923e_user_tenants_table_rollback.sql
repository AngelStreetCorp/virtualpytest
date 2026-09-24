-- 20260923e_user_tenants_table_rollback.sql
-- Inverse of 20260923e. Drops the user_tenants table and its service_role
-- policy. CASCADE drops dependent FKs (none right now, but safe).

BEGIN;

DROP TABLE IF EXISTS public.user_tenants CASCADE;

COMMIT;