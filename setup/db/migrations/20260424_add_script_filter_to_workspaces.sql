-- Add script_filter to workspaces.
-- List of script names allowed in the workspace (empty array = all allowed,
-- matching the same convention as device_filter / hidden_pages).
ALTER TABLE public.workspaces
  ADD COLUMN IF NOT EXISTS script_filter JSONB DEFAULT '[]'::jsonb;
