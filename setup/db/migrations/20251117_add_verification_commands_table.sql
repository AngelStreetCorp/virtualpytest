-- ============================================================================
-- Migration: Add verification_commands table for validation
-- ============================================================================
-- Date: 2025-11-17
-- 
-- Purpose:
--   Store valid verification commands per device model to enable validation
--   at creation time (not execution time).
--
-- Problem Solved:
--   LLM used invalid command 'check_element_exists' for web devices, which
--   caused runtime error. Now validation happens at node creation time.
--
-- Impact:
--   - Enables early validation of verification commands
--   - Prevents invalid commands from being saved to nodes
--   - Provides reference for valid commands per device_model
-- ============================================================================

-- Create table to store valid verification commands per device model
CREATE TABLE IF NOT EXISTS verification_commands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_model VARCHAR(50) NOT NULL,
    command_name VARCHAR(100) NOT NULL,
    verification_type VARCHAR(50) NOT NULL, -- 'image', 'text', 'video', 'web', 'adb'
    params_schema JSONB, -- JSON schema defining expected parameters
    description TEXT,
    category VARCHAR(50), -- 'IMAGE', 'TEXT', 'VIDEO', 'WEB', 'ADB'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure unique command per device model
    UNIQUE (device_model, command_name)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_verification_commands_device_model 
ON verification_commands(device_model);

CREATE INDEX IF NOT EXISTS idx_verification_commands_category 
ON verification_commands(device_model, category);

-- Add comment
COMMENT ON TABLE verification_commands IS 'Valid verification commands per device model for validation';
COMMENT ON COLUMN verification_commands.device_model IS 'Device model: android_mobile, android_tv, web, host_vnc, fire_tv, stb';
COMMENT ON COLUMN verification_commands.command_name IS 'Verification command name (e.g., waitForElementToAppear)';
COMMENT ON COLUMN verification_commands.params_schema IS 'JSON schema for parameter validation';

-- Populate with common verification commands for web devices (host_vnc)
INSERT INTO verification_commands (device_model, command_name, verification_type, category, description, params_schema) VALUES
('host_vnc', 'waitForElementToAppear', 'web', 'WEB', 'Wait for web element to appear (by text, selector, or aria-label)', 
'{"search_term": {"type": "string", "required": true}, "timeout": {"type": "number", "default": 10.0}, "check_interval": {"type": "number", "default": 1.0}}'),

('host_vnc', 'waitForElementToDisappear', 'web', 'WEB', 'Wait for web element to disappear', 
'{"search_term": {"type": "string", "required": true}, "timeout": {"type": "number", "default": 10.0}, "check_interval": {"type": "number", "default": 1.0}}'),

('host_vnc', 'getMenuInfo', 'web', 'WEB', 'Extract key-value pairs from menu/info screen using web element dump', 
'{"area": {"type": "area", "required": false}}'),

('host_vnc', 'waitForTextToAppear', 'text', 'TEXT', 'Wait for specific text to appear on screen using OCR', 
'{"text": {"type": "string", "required": true}, "timeout": {"type": "number", "default": 0}, "area": {"type": "area", "required": false}}'),

('host_vnc', 'waitForTextToDisappear', 'text', 'TEXT', 'Wait for specific text to disappear from screen using OCR', 
'{"text": {"type": "string", "required": true}, "timeout": {"type": "number", "default": 0}, "area": {"type": "area", "required": false}}'),

('host_vnc', 'waitForImageToAppear', 'image', 'IMAGE', 'Wait for reference image to appear on screen using template matching', 
'{"image_path": {"type": "string", "required": true}, "threshold": {"type": "number", "default": 0.8}, "timeout": {"type": "number", "default": 0}, "area": {"type": "area", "required": false}}'),

('host_vnc', 'waitForImageToDisappear', 'image', 'IMAGE', 'Wait for reference image to disappear from screen using template matching', 
'{"image_path": {"type": "string", "required": true}, "threshold": {"type": "number", "default": 0.8}, "timeout": {"type": "number", "default": 0}, "area": {"type": "area", "required": false}}')

ON CONFLICT (device_model, command_name) DO NOTHING;

-- Populate with common verification commands for android_mobile
INSERT INTO verification_commands (device_model, command_name, verification_type, category, description, params_schema) VALUES
('android_mobile', 'waitForElementToAppear', 'adb', 'ADB', 'Wait for Android element to appear using UI Automator', 
'{"search_term": {"type": "string", "required": true}, "timeout": {"type": "number", "default": 10.0}, "check_interval": {"type": "number", "default": 1.0}}'),

('android_mobile', 'waitForElementToDisappear', 'adb', 'ADB', 'Wait for Android element to disappear', 
'{"search_term": {"type": "string", "required": true}, "timeout": {"type": "number", "default": 10.0}, "check_interval": {"type": "number", "default": 1.0}}'),

('android_mobile', 'getMenuInfo', 'adb', 'ADB', 'Extract Android element information using UI Automator dump', 
'{"area": {"type": "area", "required": false}}')

ON CONFLICT (device_model, command_name) DO NOTHING;

-- Populate with common verification commands for android_tv
INSERT INTO verification_commands (device_model, command_name, verification_type, category, description, params_schema) VALUES
('android_tv', 'waitForElementToAppear', 'adb', 'ADB', 'Wait for Android TV element to appear using UI Automator', 
'{"search_term": {"type": "string", "required": true}, "timeout": {"type": "number", "default": 10.0}, "check_interval": {"type": "number", "default": 1.0}}'),

('android_tv', 'waitForElementToDisappear', 'adb', 'ADB', 'Wait for Android TV element to disappear', 
'{"search_term": {"type": "string", "required": true}, "timeout": {"type": "number", "default": 10.0}, "check_interval": {"type": "number", "default": 1.0}}'),

('android_tv', 'getMenuInfo', 'adb', 'ADB', 'Extract Android TV element information using UI Automator dump', 
'{"area": {"type": "area", "required": false}}')

ON CONFLICT (device_model, command_name) DO NOTHING;

-- Add trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_verification_commands_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_verification_commands_updated_at
    BEFORE UPDATE ON verification_commands
    FOR EACH ROW
    EXECUTE FUNCTION update_verification_commands_updated_at();

-- Grant permissions
GRANT SELECT ON verification_commands TO authenticated;
GRANT SELECT ON verification_commands TO service_role;
GRANT INSERT, UPDATE, DELETE ON verification_commands TO service_role;

-- ============================================================================
-- Verification Query (run after migration to test)
-- ============================================================================
-- SELECT * FROM verification_commands WHERE device_model = 'host_vnc';
-- 
-- Expected: Should return 7 commands for host_vnc (web)
--   - 3 WEB commands
--   - 2 TEXT commands  
--   - 2 IMAGE commands
-- ============================================================================

