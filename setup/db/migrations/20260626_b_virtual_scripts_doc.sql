-- 20260626_b_virtual_scripts_doc.sql
-- Add a markdown `doc` field to virtual scripts (the "Doc" tab, like goto.md).
-- Idempotent. Follows 20260626_add_virtual_scripts.sql.

ALTER TABLE virtual_scripts ADD COLUMN IF NOT EXISTS doc TEXT;
ALTER TABLE virtual_scripts_history ADD COLUMN IF NOT EXISTS doc TEXT;

-- Snapshot `doc` too, and fire when it changes.
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
        source, doc, target_rules, created_by, snapshot_timestamp, change_description
    ) VALUES (
        OLD.id, OLD.team_id, next_version, OLD.name, OLD.description,
        OLD.source, OLD.doc, OLD.target_rules, OLD.created_by, OLD.updated_at,
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
          OLD.doc IS DISTINCT FROM NEW.doc OR
          OLD.name IS DISTINCT FROM NEW.name)
    EXECUTE FUNCTION save_virtual_script_version_history();
