-- 20260907c_virtual_scripts_folder.sql
-- Group virtual scripts into folders (shared taxonomy from 016_folders_and_tags.sql),
-- same as testcase_definitions and disk scripts already do. See TASK-11.

ALTER TABLE virtual_scripts
    ADD COLUMN IF NOT EXISTS folder_id INTEGER REFERENCES folders(folder_id) DEFAULT 0;

ALTER TABLE virtual_scripts_history
    ADD COLUMN IF NOT EXISTS folder_id INTEGER;

UPDATE virtual_scripts SET folder_id = 0 WHERE folder_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_virtual_scripts_folder ON virtual_scripts(folder_id);

COMMENT ON COLUMN virtual_scripts.folder_id IS 'Folder for organization - shared with scripts/testcases, defaults to root (0)';
