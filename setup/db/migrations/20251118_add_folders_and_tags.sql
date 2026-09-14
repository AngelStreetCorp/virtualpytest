-- 20251118_add_folders_and_tags.sql
-- Migration: Add folders and tags support for testcases and scripts
-- Based on: 016_folders_and_tags.sql schema file
-- Enables organizing both scripts (.py files) and testcases (DB) with folders and tags

-- ================================================
-- 1. Folders Table (Flat Structure)
-- ================================================
CREATE TABLE IF NOT EXISTS folders (
  folder_id SERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL UNIQUE,  -- Unique folder names
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create root folder (default for everything)
INSERT INTO folders (folder_id, name) VALUES (0, '(Root)') ON CONFLICT DO NOTHING;

-- Reset sequence to start at 1 for user-created folders
SELECT setval('folders_folder_id_seq', 1, false);

-- Index
CREATE INDEX IF NOT EXISTS idx_folders_name ON folders(name);

-- Comments
COMMENT ON TABLE folders IS 'Flat folder structure for organizing scripts and testcases';
COMMENT ON COLUMN folders.name IS 'Unique folder name - user selects existing or types new on save';
COMMENT ON COLUMN folders.folder_id IS 'folder_id=0 is root folder (default)';

-- ================================================
-- 2. Tags Table (Auto-Created with Random Color)
-- ================================================
CREATE TABLE IF NOT EXISTS tags (
  tag_id SERIAL PRIMARY KEY,
  name VARCHAR(50) NOT NULL UNIQUE,   -- Unique tag names (lowercase)
  color VARCHAR(7) NOT NULL,           -- Hex color from fixed Material Design palette
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index
CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);

-- Comments
COMMENT ON TABLE tags IS 'Tags for filtering - auto-created when user types new tag';
COMMENT ON COLUMN tags.name IS 'Tag name (lowercase) - unique across all tags';
COMMENT ON COLUMN tags.color IS 'Hex color randomly assigned from fixed palette (#f44336, #2196f3, etc)';

-- ================================================
-- 3. Executable Tags Mapping (Unified)
-- ================================================
CREATE TABLE IF NOT EXISTS executable_tags (
  executable_type VARCHAR(10) NOT NULL CHECK (executable_type IN ('script', 'testcase')),
  executable_id VARCHAR(255) NOT NULL,    -- script.name or testcase_id
  tag_id INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  PRIMARY KEY (executable_type, executable_id, tag_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_exec_tags_lookup ON executable_tags(executable_type, executable_id);
CREATE INDEX IF NOT EXISTS idx_exec_tags_tag ON executable_tags(tag_id);

-- Comments
COMMENT ON TABLE executable_tags IS 'Unified tag mapping for both scripts and testcases';
COMMENT ON COLUMN executable_tags.executable_type IS 'Type: "script" or "testcase"';
COMMENT ON COLUMN executable_tags.executable_id IS 'For scripts: script.name (e.g. "goto.py"), For testcases: testcase_id (UUID)';

-- ================================================
-- 4. Scripts Metadata Table (For Unified Listing)
-- ================================================
CREATE TABLE IF NOT EXISTS scripts (
  script_id SERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL UNIQUE,  -- Script filename (e.g. "goto.py")
  display_name VARCHAR(255),           -- Human-readable name (e.g. "Go To Channel")
  description TEXT,                    -- Script description
  folder_id INTEGER REFERENCES folders(folder_id) DEFAULT 0,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_scripts_name ON scripts(name);
CREATE INDEX IF NOT EXISTS idx_scripts_folder ON scripts(folder_id);

-- Comments
COMMENT ON TABLE scripts IS 'Metadata for scripts (files in virtualpytest/scripts/) - enables unified listing with testcases';
COMMENT ON COLUMN scripts.name IS 'Script filename - must match actual .py file (used for execution)';
COMMENT ON COLUMN scripts.display_name IS 'Human-readable name shown in UI';
COMMENT ON COLUMN scripts.folder_id IS 'Folder for organization - defaults to root (0)';

-- ================================================
-- 5. Add folder_id to testcase_definitions
-- ================================================
ALTER TABLE testcase_definitions 
ADD COLUMN IF NOT EXISTS folder_id INTEGER REFERENCES folders(folder_id) DEFAULT 0;

-- Index
CREATE INDEX IF NOT EXISTS idx_testcase_folder ON testcase_definitions(folder_id);

-- Comment
COMMENT ON COLUMN testcase_definitions.folder_id IS 'Folder for organization - user selects or types on save, defaults to root (0)';

-- ================================================
-- 6. Migrate Existing Data
-- ================================================

-- Set all existing testcases to root folder
UPDATE testcase_definitions SET folder_id = 0 WHERE folder_id IS NULL;

-- ================================================
-- Row Level Security (RLS)
-- ================================================

-- Enable RLS on new tables
ALTER TABLE folders ENABLE ROW LEVEL SECURITY;
ALTER TABLE tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE executable_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE scripts ENABLE ROW LEVEL SECURITY;

-- Public access policies (consistent with existing tables)
DROP POLICY IF EXISTS "folders_access_policy" ON folders;
CREATE POLICY "folders_access_policy" ON folders FOR ALL TO public USING (true);

DROP POLICY IF EXISTS "tags_access_policy" ON tags;
CREATE POLICY "tags_access_policy" ON tags FOR ALL TO public USING (true);

DROP POLICY IF EXISTS "executable_tags_access_policy" ON executable_tags;
CREATE POLICY "executable_tags_access_policy" ON executable_tags FOR ALL TO public USING (true);

DROP POLICY IF EXISTS "scripts_access_policy" ON scripts;
CREATE POLICY "scripts_access_policy" ON scripts FOR ALL TO public USING (true);

-- Service role policies
DROP POLICY IF EXISTS "service_role_all_folders" ON folders;
CREATE POLICY "service_role_all_folders" ON folders FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_tags" ON tags;
CREATE POLICY "service_role_all_tags" ON tags FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_executable_tags" ON executable_tags;
CREATE POLICY "service_role_all_executable_tags" ON executable_tags FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_scripts" ON scripts;
CREATE POLICY "service_role_all_scripts" ON scripts FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ================================================
-- Done! Clean implementation with no fallbacks
-- ================================================

