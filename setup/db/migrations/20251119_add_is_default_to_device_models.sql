-- Migration: Add is_default column to device_models table
-- Purpose: Prevent deletion of system default models
-- Date: 2025-11-19

-- Add is_default column if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'device_models' 
        AND column_name = 'is_default'
    ) THEN
        ALTER TABLE device_models 
        ADD COLUMN is_default boolean DEFAULT false NOT NULL;
        
        RAISE NOTICE 'Added is_default column to device_models table';
    ELSE
        RAISE NOTICE 'Column is_default already exists in device_models table';
    END IF;
END $$;

-- Update existing default models to have is_default = true
-- These are the standard models that are auto-created for each team
UPDATE device_models 
SET is_default = true 
WHERE name IN ('web', 'android_tv', 'stb', 'android_mobile', 'apple_tv');

-- Add comment explaining the column
COMMENT ON COLUMN device_models.is_default IS 
'Flag indicating if this is a system default model that cannot be deleted by users';

-- Display summary of updated models
DO $$
DECLARE
    default_count integer;
BEGIN
    SELECT COUNT(*) INTO default_count FROM device_models WHERE is_default = true;
    RAISE NOTICE 'Migration complete. % default models marked as system-protected.', default_count;
END $$;

