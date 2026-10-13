-- 20261004b_workspaces_slug_per_server.sql
-- A workspace slug is unique per server, not per database: servers sharing one database
-- (Awesomation and vpt-pi1's RPI1-server) can each have a "Streams" workspace. Needs
-- 20261004a_workspaces_server_name.sql first.
--
-- Idempotent. Canonical twin: setup/db/schema/030_workspaces.sql.
-- Inverse: 20261004b_workspaces_slug_per_server_rollback.sql.

BEGIN;

ALTER TABLE public.workspaces DROP CONSTRAINT IF EXISTS workspaces_slug_key;
ALTER TABLE public.workspaces DROP CONSTRAINT IF EXISTS workspaces_server_name_slug_key;
ALTER TABLE public.workspaces
  ADD CONSTRAINT workspaces_server_name_slug_key UNIQUE (server_name, slug);

COMMIT;
