-- 20261004b_workspaces_slug_per_server_rollback.sql — inverse of 20261004b_workspaces_slug_per_server.sql.
-- Fails if two servers already use the same slug: rename one first.

BEGIN;

ALTER TABLE public.workspaces DROP CONSTRAINT IF EXISTS workspaces_server_name_slug_key;
ALTER TABLE public.workspaces ADD CONSTRAINT workspaces_slug_key UNIQUE (slug);

COMMIT;
