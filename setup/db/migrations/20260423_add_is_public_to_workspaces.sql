-- Add is_public flag to workspaces and extend get_user_workspaces RPC to include public workspaces.
-- Public workspaces are visible to every user (and anonymous callers via the plain
-- GET /server/workspaces path) regardless of workspace_members rows.
ALTER TABLE public.workspaces ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT FALSE;

CREATE OR REPLACE FUNCTION get_user_workspaces(p_user_id UUID)
RETURNS TABLE(workspace_id UUID) AS $$
BEGIN
  RETURN QUERY
    SELECT wm.workspace_id FROM workspace_members wm
    WHERE wm.user_id = p_user_id
    UNION
    SELECT wm.workspace_id FROM workspace_members wm
    INNER JOIN team_members tm ON tm.team_id = wm.team_id
    WHERE tm.user_id = p_user_id
    UNION
    SELECT w.id FROM workspaces w
    WHERE w.is_public = TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
