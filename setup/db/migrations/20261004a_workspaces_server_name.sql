-- 20261004a_workspaces_server_name.sql
-- A workspace belongs to the server that created it. Several servers can read one database
-- (vpt-pi1's RPI1-server uses the same Supabase as Awesomation), and without an owner every
-- server listed every workspace. `server_name` holds the owning server's SERVER_NAME; a server
-- lists and edits only its own (shared/src/lib/database/workspaces_db.py).
--
-- Existing rows have no owner yet: they all go to ONE server, named on the command line. The
-- script stops with a syntax error if the variable is missing, so nothing is half-applied:
--   psql ... -v ON_ERROR_STOP=1 -v owner_server=Awesomation < 20261004a_workspaces_server_name.sql
-- Rows meant for another server: delete and recreate them from that server.
--
-- Canonical twin: setup/db/schema/030_workspaces.sql.
-- Inverse: 20261004a_workspaces_server_name_rollback.sql.

BEGIN;

ALTER TABLE public.workspaces ADD COLUMN IF NOT EXISTS server_name TEXT;
UPDATE public.workspaces SET server_name = :'owner_server' WHERE server_name IS NULL;
ALTER TABLE public.workspaces ALTER COLUMN server_name SET NOT NULL;
COMMENT ON COLUMN public.workspaces.server_name IS
  'SERVER_NAME of the backend server that owns this workspace; only that server lists it';

COMMIT;
