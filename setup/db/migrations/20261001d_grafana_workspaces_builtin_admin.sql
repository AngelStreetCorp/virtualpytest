-- 20261001d_grafana_workspaces_builtin_admin.sql
-- BUG-0212: Grafana's built-in server admin (login 'admin', email admin@localhost, no
-- VirtualPyTest profile) saw only "None" in every dashboard's Workspace drop-down.
-- grafana_user_workspaces() matched the viewer by email only, while grafana_device_scope()
-- already recognises that account by its login. It now takes the login too and lists every
-- workspace for login 'admin' — the same rule.
--
-- p_login defaults to '' so dashboards not yet re-imported (one argument) keep working.
-- Requires 20260929f_grafana_device_scope.sql. Canonical twin: setup/db/schema/056_grafana_device_scope.sql.
-- Inverse: 20261001d_grafana_workspaces_builtin_admin_rollback.sql.

BEGIN;

-- A one-argument and a defaulted two-argument version cannot coexist (ambiguous call).
DROP FUNCTION IF EXISTS public.grafana_user_workspaces(TEXT);

CREATE OR REPLACE FUNCTION public.grafana_user_workspaces(p_email TEXT, p_login TEXT DEFAULT '')
RETURNS TABLE(id TEXT, name TEXT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH me AS (
    SELECT p.id, p.role FROM public.profiles p WHERE lower(p.email) = lower(p_email) LIMIT 1
  )
  SELECT w.id::text, w.name
  FROM public.workspaces w
  WHERE p_login = 'admin'
     OR EXISTS (SELECT 1 FROM me WHERE me.role = 'admin')
     OR w.is_public
     OR EXISTS (SELECT 1 FROM public.workspace_members wm, me
                WHERE wm.workspace_id = w.id
                  AND (wm.user_id = me.id
                       OR wm.team_id IN (SELECT m.team_id FROM public.team_members m WHERE m.user_id = me.id)))
  ORDER BY w.name;
$$;

REVOKE EXECUTE ON FUNCTION public.grafana_user_workspaces(TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.grafana_user_workspaces(TEXT, TEXT) TO service_role;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') THEN
    GRANT EXECUTE ON FUNCTION public.grafana_user_workspaces(TEXT, TEXT) TO grafana_reader;
  END IF;
END $$;

COMMIT;
