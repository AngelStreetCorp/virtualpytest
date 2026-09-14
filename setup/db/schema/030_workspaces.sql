-- =====================================================
-- Workspaces Schema
-- Named scoped contexts restricting permissions,
-- devices, and project visibility (admin-managed)
-- =====================================================

-- workspaces table
CREATE TABLE IF NOT EXISTS public.workspaces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  description TEXT DEFAULT '',
  permissions JSONB DEFAULT '[]'::jsonb,          -- permission filter (intersection with user perms)
  denied_permissions JSONB DEFAULT '[]'::jsonb,   -- extra denials within workspace
  device_filter JSONB DEFAULT '[]'::jsonb,         -- device name patterns e.g. ["stb-*", "tv-lab"]
  script_filter JSONB DEFAULT '[]'::jsonb,         -- allowed script names; empty = all allowed
  project_tags JSONB DEFAULT '[]'::jsonb,          -- project scope tags
  hidden_pages JSONB DEFAULT '[]'::jsonb,          -- page paths hidden in this workspace
  is_public BOOLEAN NOT NULL DEFAULT FALSE,        -- when TRUE, workspace is visible to everyone (no membership required)
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- workspace_members junction table
CREATE TABLE IF NOT EXISTS public.workspace_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
  team_id UUID REFERENCES public.teams(id) ON DELETE CASCADE,
  role TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  -- Either user_id OR team_id must be set (not both, not neither)
  CONSTRAINT workspace_member_target CHECK (
    (user_id IS NOT NULL AND team_id IS NULL) OR
    (user_id IS NULL AND team_id IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace ON public.workspace_members(workspace_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_user ON public.workspace_members(user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_team ON public.workspace_members(team_id);

-- Enable Row Level Security
ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_members ENABLE ROW LEVEL SECURITY;

-- RLS Policies (match pattern from 001_core_tables.sql)
CREATE POLICY "workspaces_access_policy" ON public.workspaces
FOR ALL
TO public
USING (true);

CREATE POLICY "workspace_members_access_policy" ON public.workspace_members
FOR ALL
TO public
USING (true);

-- RPC: get workspaces for a user (direct + via team membership + public)
CREATE OR REPLACE FUNCTION get_user_workspaces(p_user_id UUID)
RETURNS TABLE(workspace_id UUID) AS $$
BEGIN
  RETURN QUERY
    -- Direct user membership
    SELECT wm.workspace_id FROM workspace_members wm
    WHERE wm.user_id = p_user_id
    UNION
    -- Team membership
    SELECT wm.workspace_id FROM workspace_members wm
    INNER JOIN team_members tm ON tm.team_id = wm.team_id
    WHERE tm.user_id = p_user_id
    UNION
    -- Public workspaces (visible to every authenticated user regardless of membership)
    SELECT w.id FROM workspaces w
    WHERE w.is_public = TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON TABLE public.workspaces IS 'Named scoped contexts restricting user permissions, devices, and project visibility';
COMMENT ON TABLE public.workspace_members IS 'Junction table linking users or teams to workspaces with roles';
COMMENT ON FUNCTION get_user_workspaces IS 'Returns workspace IDs accessible to a user (direct + via team membership)';
