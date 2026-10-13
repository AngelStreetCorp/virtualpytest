-- 20260929f_grafana_device_scope.sql
-- TASK-31 phase D — Grafana dashboards show each viewer only the devices they may see.
--
-- Grafana and VirtualPyTest share the email as the user key. Every dashboard carries a hidden
-- variable `allowed_devices` = grafana_device_scope('${__user.email}', '${__user.login}',
-- '${workspace}') and wraps each device-table read with it (infra/monitoring/grafana/dashboards/
-- _apply_device_scope.py). The visible `workspace` drop-down lists grafana_user_workspaces().
--
-- The functions are SECURITY DEFINER: profiles, teams, roles, workspaces are service-role only,
-- so Grafana's read-only login sees none of their rows. They return device keys only.
--
-- A filter on what dashboards show, NOT authorization: Grafana queries over one shared login.
--
-- Requires 20260929d_access_ceilings.sql (team_cap, allowed_devices).
-- Canonical twin: setup/db/schema/056_grafana_device_scope.sql. Idempotent.
-- Inverse: 20260929f_grafana_device_scope_rollback.sql.

BEGIN;

-- The workspaces a user can pick: direct membership, through a team, or public. All for an admin.
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

-- The devices `p_email` may see, as dashboard keys. Always at least one row:
--   '*'  no limit (VirtualPyTest admin; Grafana's built-in admin login; nobody limited it)
--   keys host_name:device_id AND host_name:device_name (mapped through device_flags, the device
--        registry), so a panel matches on whichever column its table has
--   '-'  nothing (an email with no VirtualPyTest profile, or an empty intersection)
-- The rule is phase C's: team ∩ role ∩ user, then ∩ the workspace's device_filter when p_workspace
-- names a workspace the user can pick.
CREATE OR REPLACE FUNCTION public.grafana_device_scope(p_email TEXT, p_login TEXT, p_workspace TEXT DEFAULT '')
RETURNS TABLE(device_key TEXT)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_user   public.profiles%ROWTYPE;
  v_ids    TEXT[];          -- host_name:device_id, NULL = no limit
  v_level  JSONB;
BEGIN
  -- Grafana's built-in server admin is never restricted (it has no VirtualPyTest profile).
  IF p_login = 'admin' THEN
    RETURN QUERY SELECT '*'::text;
    RETURN;
  END IF;

  SELECT * INTO v_user FROM public.profiles WHERE lower(email) = lower(p_email) LIMIT 1;
  IF NOT FOUND THEN
    RETURN QUERY SELECT '-'::text;
    RETURN;
  END IF;
  IF v_user.role = 'admin' THEN
    RETURN QUERY SELECT '*'::text;
    RETURN;
  END IF;

  FOREACH v_level IN ARRAY ARRAY[
      public.team_cap(v_user.id, 'devices'),
      (SELECT r.allowed_devices FROM public.roles r WHERE r.role = v_user.role),
      v_user.allowed_devices,
      (SELECT w.device_filter FROM public.workspaces w
        WHERE COALESCE(p_workspace, '') <> ''
          AND w.id::text = p_workspace
          AND w.id::text IN (SELECT gw.id FROM public.grafana_user_workspaces(p_email) gw))
  ] LOOP
    CONTINUE WHEN v_level IS NULL;
    IF v_ids IS NULL THEN
      v_ids := ARRAY(SELECT jsonb_array_elements_text(v_level));
    ELSE
      v_ids := ARRAY(SELECT unnest(v_ids) INTERSECT SELECT jsonb_array_elements_text(v_level));
    END IF;
  END LOOP;

  IF v_ids IS NULL THEN
    RETURN QUERY SELECT '*'::text;
    RETURN;
  END IF;
  IF cardinality(v_ids) = 0 THEN
    RETURN QUERY SELECT '-'::text;
    RETURN;
  END IF;

  RETURN QUERY
    SELECT DISTINCT k FROM (
      SELECT unnest(v_ids) AS k
      UNION
      SELECT f.host_name || ':' || f.device_name
      FROM public.device_flags f
      WHERE f.host_name || ':' || f.device_id = ANY (v_ids)
    ) keys;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.grafana_user_workspaces(TEXT)          FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.grafana_device_scope(TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.grafana_user_workspaces(TEXT)          TO service_role;
GRANT  EXECUTE ON FUNCTION public.grafana_device_scope(TEXT, TEXT, TEXT) TO service_role;

-- Grafana's read-only login on Docker installs. Other installs grant their datasource user by hand
-- (see the release note); a superuser datasource login needs nothing.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') THEN
    GRANT EXECUTE ON FUNCTION public.grafana_user_workspaces(TEXT)          TO grafana_reader;
    GRANT EXECUTE ON FUNCTION public.grafana_device_scope(TEXT, TEXT, TEXT) TO grafana_reader;
  END IF;
END $$;

COMMIT;
