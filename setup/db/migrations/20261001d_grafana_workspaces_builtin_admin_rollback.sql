-- 20261001d_grafana_workspaces_builtin_admin_rollback.sql
-- Inverse of 20261001d_grafana_workspaces_builtin_admin.sql: back to the email-only version.
-- Re-import dashboards that pass ${__user.login} to grafana_user_workspaces first, or they error.

BEGIN;

DROP FUNCTION IF EXISTS public.grafana_user_workspaces(TEXT, TEXT);

CREATE OR REPLACE FUNCTION public.grafana_user_workspaces(p_email TEXT)
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
  WHERE EXISTS (SELECT 1 FROM me WHERE me.role = 'admin')
     OR w.is_public
     OR EXISTS (SELECT 1 FROM public.workspace_members wm, me
                WHERE wm.workspace_id = w.id
                  AND (wm.user_id = me.id
                       OR wm.team_id IN (SELECT m.team_id FROM public.team_members m WHERE m.user_id = me.id)))
  ORDER BY w.name;
$$;

REVOKE EXECUTE ON FUNCTION public.grafana_user_workspaces(TEXT) FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.grafana_user_workspaces(TEXT) TO service_role;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') THEN
    GRANT EXECUTE ON FUNCTION public.grafana_user_workspaces(TEXT) TO grafana_reader;
  END IF;
END $$;

COMMIT;
