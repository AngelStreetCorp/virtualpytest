-- 009_device_flags.sql
-- Device Flags System
-- Simple table to store user-defined flags/clusters for devices
-- Clean implementation with no backward compatibility

-- Drop existing table if it exists (for clean recreation)
DROP TABLE IF EXISTS device_flags CASCADE;

-- Create the device_flags table
CREATE TABLE device_flags (
    -- Primary identification
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    
    -- Device identification
    host_name TEXT NOT NULL,
    device_id TEXT NOT NULL,
    device_name TEXT NOT NULL,
    
    -- Flags array
    flags TEXT[] DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Unique constraint
    UNIQUE(host_name, device_id)
);

-- Create indexes for performance
CREATE INDEX idx_device_flags_host_device ON device_flags(host_name, device_id);
CREATE INDEX idx_device_flags_flags ON device_flags USING GIN(flags);
CREATE INDEX idx_device_flags_host_name ON device_flags(host_name);
CREATE INDEX idx_device_flags_updated_at ON device_flags(updated_at DESC);

-- Enable Row Level Security
ALTER TABLE device_flags ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Match existing table pattern
CREATE POLICY "device_flags_access_policy" ON device_flags
    FOR ALL USING (true);

-- Function to upsert device flags (auto-insert on registration)
CREATE OR REPLACE FUNCTION upsert_device_flags(
    p_host_name TEXT,
    p_device_id TEXT,
    p_device_name TEXT
) RETURNS VOID AS $$
BEGIN
    INSERT INTO device_flags (host_name, device_id, device_name, flags)
    VALUES (p_host_name, p_device_id, p_device_name, '{}')
    ON CONFLICT (host_name, device_id) 
    DO UPDATE SET 
        device_name = EXCLUDED.device_name,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Function to update device flags
CREATE OR REPLACE FUNCTION update_device_flags(
    p_host_name TEXT,
    p_device_id TEXT,
    p_flags TEXT[]
) RETURNS VOID AS $$
BEGIN
    UPDATE device_flags 
    SET 
        flags = p_flags,
        updated_at = NOW()
    WHERE host_name = p_host_name AND device_id = p_device_id;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Device not found: host_name=%, device_id=%', p_host_name, p_device_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to get devices by flag
CREATE OR REPLACE FUNCTION get_devices_by_flag(
    p_flag TEXT,
    p_host_name TEXT DEFAULT NULL
) RETURNS TABLE(
    host_name TEXT,
    device_id TEXT,
    device_name TEXT,
    flags TEXT[]
) AS $$
BEGIN
    RETURN QUERY
    SELECT df.host_name, df.device_id, df.device_name, df.flags
    FROM device_flags df
    WHERE p_flag = ANY(df.flags)
    AND (p_host_name IS NULL OR df.host_name = p_host_name)
    ORDER BY df.host_name, df.device_name;
END;
$$ LANGUAGE plpgsql;

-- Grant necessary permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON device_flags TO authenticated;
GRANT EXECUTE ON FUNCTION upsert_device_flags TO authenticated;
GRANT EXECUTE ON FUNCTION update_device_flags TO authenticated;
GRANT EXECUTE ON FUNCTION get_devices_by_flag TO authenticated;

-- Add comments for documentation
COMMENT ON TABLE device_flags IS 'Device Flags System - stores user-defined flags/clusters for devices';
COMMENT ON COLUMN device_flags.host_name IS 'Host name where the device is registered';
COMMENT ON COLUMN device_flags.device_id IS 'Unique device identifier within the host';
COMMENT ON COLUMN device_flags.device_name IS 'Human-readable device name';
COMMENT ON COLUMN device_flags.flags IS 'Array of user-defined flags/tags for the device';
COMMENT ON FUNCTION upsert_device_flags IS 'Inserts or updates device registration with empty flags';
COMMENT ON FUNCTION update_device_flags IS 'Updates flags for an existing device';
COMMENT ON FUNCTION get_devices_by_flag IS 'Retrieves devices that have a specific flag';
