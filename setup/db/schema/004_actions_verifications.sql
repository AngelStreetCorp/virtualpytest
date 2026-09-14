-- VirtualPyTest Actions and Verifications Tables Schema
-- This file contains tables for test actions and verification definitions

-- Drop existing tables if they exist (for clean recreation)
DROP TABLE IF EXISTS verifications_references CASCADE;

-- actions table removed - does not exist in current database

-- verifications table removed - does not exist in current database

-- Verification reference data
CREATE TABLE verifications_references (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    name text NOT NULL,
    userinterface_name text,  -- PRIMARY: Userinterface name (e.g., 'example_androidtv')
    device_model text,  -- DEPRECATED: Kept for backward compatibility during migration
    userinterface_id uuid REFERENCES userinterfaces(id) ON DELETE SET NULL,  -- Foreign key reference (optional, set to NULL if UI deleted)
    reference_type text NOT NULL CHECK (reference_type = ANY (ARRAY['reference_image'::text, 'reference_text'::text])),
    area jsonb,
    r2_path text NOT NULL,  -- Path format: reference-images/{userinterface_name}/{filename} or text-references/{userinterface_name}/{filename}
    r2_url text NOT NULL,   -- URL format: https://.../reference-images/{userinterface_name}/{filename}
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    shared boolean NOT NULL DEFAULT false,  -- When true, visible+editable by any UI sharing a device model with the origin UI
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

-- Local refs are unique within (team, name, userinterface, type).
-- Shared refs are unique globally per (team, name, type) — one canonical row.
CREATE UNIQUE INDEX verifications_references_local_unique
    ON verifications_references (team_id, name, userinterface_name, reference_type)
    WHERE shared = false;
CREATE UNIQUE INDEX verifications_references_shared_unique
    ON verifications_references (team_id, name, reference_type)
    WHERE shared = true;

-- Add comments to explain the columns
COMMENT ON COLUMN verifications_references.userinterface_name IS 
'PRIMARY: Userinterface name string (e.g., ''example_androidtv''). Used for grouping and filtering references.';

COMMENT ON COLUMN verifications_references.userinterface_id IS
'OPTIONAL: Foreign key to userinterfaces table. References are organized by userinterface_name (text) for simplicity.';

COMMENT ON COLUMN verifications_references.shared IS
'When true, the reference is visible+editable by every userinterface in the team whose models[] intersects with the origin userinterface_name''s models[]. One canonical row — edits propagate to all consumers.';

-- verifications table foreign key removed - table does not exist

-- actions and verifications indexes removed - tables do not exist

CREATE INDEX idx_verifications_references_team_id ON verifications_references(team_id);
CREATE INDEX idx_verifications_references_userinterface_name ON verifications_references(userinterface_name);  -- PRIMARY INDEX
CREATE INDEX idx_verifications_references_device_model ON verifications_references(device_model);  -- DEPRECATED: Will be removed after migration
CREATE INDEX idx_verifications_references_userinterface_id ON verifications_references(userinterface_id);  -- OPTIONAL FK
CREATE INDEX idx_verifications_references_reference_type ON verifications_references(reference_type);
CREATE INDEX idx_verifications_references_shared ON verifications_references(team_id, shared) WHERE shared = true;

-- Add comments
COMMENT ON TABLE verifications_references IS 'Reference data for verifications (screenshots, elements, etc.)';

-- Enable Row Level Security (RLS)
ALTER TABLE verifications_references ENABLE ROW LEVEL SECURITY;

-- RLS Policies for verifications_references table (updated to match actual working database)
CREATE POLICY "verifications_references_access_policy" ON verifications_references
FOR ALL 
TO public
USING (true); 