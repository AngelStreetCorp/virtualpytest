-- 039_virtual_scripts.sql
-- Virtual Scripts: Python test scripts stored in the DB (source-in-database)
-- instead of as files on disk. Edited in the browser (Virtual Scripts page),
-- syntax-checked on save, and executed on a host that materializes the source
-- to a temp .py file the instant before launch — so a new/edited script never
-- needs an rsync deploy. See docs/agent/execution/VIRTUAL_SCRIPTS.md.
--
-- Clean implementation, mirrors testcase_definitions (+ _history) patterns.

-- Drop existing tables/functions for clean recreation
DROP TABLE IF EXISTS virtual_scripts_history CASCADE;
DROP TABLE IF EXISTS virtual_scripts CASCADE;
DROP FUNCTION IF EXISTS update_virtual_scripts_updated_at();
DROP FUNCTION IF EXISTS save_virtual_script_version_history();

-- ================================================
-- 1. virtual_scripts (latest source)
-- ================================================
CREATE TABLE virtual_scripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,            -- Used as script_name in script_results
    description TEXT,
    source TEXT NOT NULL,                  -- Full Python source (@script-decorated)
    doc TEXT,                              -- Markdown doc (the "Doc" tab, like goto.md)
    target_rules JSONB,                    -- Parsed _target_rules (optional, advisory)
    folder_id INTEGER REFERENCES folders(folder_id) DEFAULT 0,  -- Shared folder taxonomy (see 016_folders_and_tags.sql)
    created_by VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Lifecycle: a script name has up to 3 live rows (one per environment).
    -- 'dev' is canonical and always exists (editing writes it); 'test'/'prod'
    -- are promotion snapshots created on Promote. Mirrors testcase_definitions.
    environment VARCHAR(10) NOT NULL DEFAULT 'dev'
        CHECK (environment IN ('dev', 'test', 'prod')),
    -- On the prod row only: increments on each promote-to-prod (1 = first). The
    -- previous prod source is snapshotted to _history as the N-1 rollback point.
    prod_version INTEGER,

    -- One script name per team PER ENVIRONMENT (≤3 rows: dev/test/prod)
    CONSTRAINT unique_virtual_script_per_team_env UNIQUE (team_id, name, environment)
);

CREATE INDEX idx_virtual_scripts_team ON virtual_scripts(team_id);
CREATE INDEX idx_virtual_scripts_name ON virtual_scripts(name);
CREATE INDEX idx_virtual_scripts_environment ON virtual_scripts(environment);
CREATE INDEX idx_virtual_scripts_folder ON virtual_scripts(folder_id);

CREATE OR REPLACE FUNCTION update_virtual_scripts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER virtual_scripts_updated_at
    BEFORE UPDATE ON virtual_scripts
    FOR EACH ROW
    EXECUTE FUNCTION update_virtual_scripts_updated_at();

COMMENT ON TABLE virtual_scripts IS 'DB-stored Python test scripts (no-disk-deploy). Source materialized to a temp file on the host at execution time.';
COMMENT ON COLUMN virtual_scripts.name IS 'Used as script_name in script_results for unified tracking';
COMMENT ON COLUMN virtual_scripts.source IS 'Full Python source — must be @script-decorated and declare _script_args';
COMMENT ON COLUMN virtual_scripts.target_rules IS 'Advisory _target_rules parsed from the source (target_type/host_os/device_model)';
COMMENT ON COLUMN virtual_scripts.folder_id IS 'Folder for organization - shared with scripts/testcases, defaults to root (0)';
COMMENT ON COLUMN virtual_scripts.environment IS 'Lifecycle env: dev (canonical, editable, always exists), test, or prod. A name fans out to <=3 rows.';
COMMENT ON COLUMN virtual_scripts.prod_version IS 'Prod row only: promote-to-prod counter (1=first). Previous prod source lives in _history as the N-1 rollback point.';

-- ================================================
-- 2. virtual_scripts_history (version history)
-- ================================================
CREATE TABLE virtual_scripts_history (
    history_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    virtual_script_id UUID NOT NULL REFERENCES virtual_scripts(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    source TEXT NOT NULL,
    doc TEXT,
    target_rules JSONB,
    folder_id INTEGER,
    created_by VARCHAR(255),
    snapshot_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    change_description TEXT,

    CONSTRAINT unique_virtual_script_version UNIQUE (virtual_script_id, version_number)
);

CREATE INDEX idx_virtual_script_history_script_id ON virtual_scripts_history(virtual_script_id);
CREATE INDEX idx_virtual_script_history_team_id ON virtual_scripts_history(team_id);
CREATE INDEX idx_virtual_script_history_version ON virtual_scripts_history(virtual_script_id, version_number DESC);

-- Save the OLD row to history before an update that changes source/description/name
CREATE OR REPLACE FUNCTION save_virtual_script_version_history()
RETURNS TRIGGER AS $$
DECLARE
    next_version INTEGER;
BEGIN
    SELECT COALESCE(MAX(version_number), 0) + 1 INTO next_version
    FROM virtual_scripts_history
    WHERE virtual_script_id = OLD.id;

    INSERT INTO virtual_scripts_history (
        virtual_script_id, team_id, version_number, name, description,
        source, doc, target_rules, folder_id, created_by, snapshot_timestamp, change_description
    ) VALUES (
        OLD.id, OLD.team_id, next_version, OLD.name, OLD.description,
        OLD.source, OLD.doc, OLD.target_rules, OLD.folder_id, OLD.created_by, OLD.updated_at,
        'Auto-saved before update'
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER save_virtual_script_history_before_update
    BEFORE UPDATE ON virtual_scripts
    FOR EACH ROW
    WHEN (OLD.source IS DISTINCT FROM NEW.source OR
          OLD.description IS DISTINCT FROM NEW.description OR
          OLD.doc IS DISTINCT FROM NEW.doc OR
          OLD.name IS DISTINCT FROM NEW.name)
    EXECUTE FUNCTION save_virtual_script_version_history();

COMMENT ON TABLE virtual_scripts_history IS 'Version history for virtual_scripts — allows reverting to previous source';

-- ================================================
-- Row Level Security (match testcase_definitions pattern)
-- ================================================
ALTER TABLE virtual_scripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE virtual_scripts_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_virtual_scripts" ON virtual_scripts
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "virtual_scripts_access_policy" ON virtual_scripts
    FOR ALL TO public
    USING (true);

CREATE POLICY "service_role_all_virtual_scripts_history" ON virtual_scripts_history
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "virtual_scripts_history_access_policy" ON virtual_scripts_history
    FOR ALL TO public
    USING (true);
