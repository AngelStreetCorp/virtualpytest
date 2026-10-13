-- 20261004a_workspaces_server_name_rollback.sql — inverse of 20261004a_workspaces_server_name.sql.
-- Every workspace becomes visible on every server sharing the database again.

BEGIN;

ALTER TABLE public.workspaces DROP COLUMN IF EXISTS server_name;

COMMIT;
