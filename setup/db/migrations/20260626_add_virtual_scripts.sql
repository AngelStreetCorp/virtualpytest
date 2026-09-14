-- 20260626_add_virtual_scripts.sql
-- Migration: Add virtual_scripts (+ history) for DB-stored Python test scripts.
-- Based on: setup/db/schema/039_virtual_scripts.sql
-- Idempotent (safe to re-run on a live DB). See docs/agent/execution/VIRTUAL_SCRIPTS.md.

-- ================================================
-- 1. virtual_scripts
-- ================================================
CREATE TABLE IF NOT EXISTS virtual_scripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    source TEXT NOT NULL,
    target_rules JSONB,
    created_by VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT unique_virtual_script_per_team UNIQUE (team_id, name)
);

CREATE INDEX IF NOT EXISTS idx_virtual_scripts_team ON virtual_scripts(team_id);
CREATE INDEX IF NOT EXISTS idx_virtual_scripts_name ON virtual_scripts(name);

CREATE OR REPLACE FUNCTION update_virtual_scripts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS virtual_scripts_updated_at ON virtual_scripts;
CREATE TRIGGER virtual_scripts_updated_at
    BEFORE UPDATE ON virtual_scripts
    FOR EACH ROW
    EXECUTE FUNCTION update_virtual_scripts_updated_at();

-- ================================================
-- 2. virtual_scripts_history
-- ================================================
CREATE TABLE IF NOT EXISTS virtual_scripts_history (
    history_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    virtual_script_id UUID NOT NULL REFERENCES virtual_scripts(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    source TEXT NOT NULL,
    target_rules JSONB,
    created_by VARCHAR(255),
    snapshot_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    change_description TEXT,
    CONSTRAINT unique_virtual_script_version UNIQUE (virtual_script_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_virtual_script_history_script_id ON virtual_scripts_history(virtual_script_id);
CREATE INDEX IF NOT EXISTS idx_virtual_script_history_team_id ON virtual_scripts_history(team_id);
CREATE INDEX IF NOT EXISTS idx_virtual_script_history_version ON virtual_scripts_history(virtual_script_id, version_number DESC);

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
        source, target_rules, created_by, snapshot_timestamp, change_description
    ) VALUES (
        OLD.id, OLD.team_id, next_version, OLD.name, OLD.description,
        OLD.source, OLD.target_rules, OLD.created_by, OLD.updated_at,
        'Auto-saved before update'
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS save_virtual_script_history_before_update ON virtual_scripts;
CREATE TRIGGER save_virtual_script_history_before_update
    BEFORE UPDATE ON virtual_scripts
    FOR EACH ROW
    WHEN (OLD.source IS DISTINCT FROM NEW.source OR
          OLD.description IS DISTINCT FROM NEW.description OR
          OLD.name IS DISTINCT FROM NEW.name)
    EXECUTE FUNCTION save_virtual_script_version_history();

-- ================================================
-- 3. Row Level Security
-- ================================================
ALTER TABLE virtual_scripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE virtual_scripts_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_virtual_scripts" ON virtual_scripts;
CREATE POLICY "service_role_all_virtual_scripts" ON virtual_scripts
    FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "virtual_scripts_access_policy" ON virtual_scripts;
CREATE POLICY "virtual_scripts_access_policy" ON virtual_scripts
    FOR ALL TO public
    USING ((auth.uid() IS NULL) OR (auth.role() = 'service_role'::text) OR true);

DROP POLICY IF EXISTS "service_role_all_virtual_scripts_history" ON virtual_scripts_history;
CREATE POLICY "service_role_all_virtual_scripts_history" ON virtual_scripts_history
    FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "virtual_scripts_history_access_policy" ON virtual_scripts_history;
CREATE POLICY "virtual_scripts_history_access_policy" ON virtual_scripts_history
    FOR ALL TO public
    USING ((auth.uid() IS NULL) OR (auth.role() = 'service_role'::text) OR true);
