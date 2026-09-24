-- VirtualPyTest Core Tables Schema
-- This file contains the main tables for the VirtualPyTest system

-- Drop existing tables if they exist (for clean recreation)
DROP TABLE IF EXISTS ai_analysis_cache CASCADE;
DROP TABLE IF EXISTS campaign_executions CASCADE;
DROP TABLE IF EXISTS environment_profiles CASCADE;
DROP TABLE IF EXISTS device CASCADE;
DROP TABLE IF EXISTS device_models CASCADE;
DROP TABLE IF EXISTS teams CASCADE;

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Teams table (referenced by most other tables)
CREATE TABLE teams (
    id uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
    name text NOT NULL,
    description text,
    tenant_id uuid NOT NULL,
    created_by uuid,
    is_default boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

-- Core device and controller tables
CREATE TABLE device_models (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    name character varying NOT NULL CHECK (length(TRIM(BOTH FROM name)) > 0),
    types jsonb DEFAULT '[]'::jsonb NOT NULL CHECK (jsonb_typeof(types) = 'array'::text),
    controllers jsonb DEFAULT '{"av": "", "power": "", "remote": "", "network": ""}'::jsonb NOT NULL CHECK (jsonb_typeof(controllers) = 'object'::text),
    version character varying,
    description text,
    is_default boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE device (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    name text NOT NULL,
    description text,
    model text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    controller_configs jsonb
);

-- Add comment for controller_configs column
COMMENT ON COLUMN device.controller_configs IS 'controller config';

-- controllers table removed - does not exist in current database

-- Environment and campaign tables
CREATE TABLE environment_profiles (
    id uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
    name character varying NOT NULL,
    description text,
    config jsonb DEFAULT '{}'::jsonb,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

-- Campaign executions table (UPDATED SCHEMA)
CREATE TABLE campaign_executions (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    campaign_name character varying NOT NULL,
    campaign_description text,
    campaign_execution_id character varying NOT NULL UNIQUE,  -- UPDATED: Added UNIQUE constraint
    userinterface_name character varying,
    host_name character varying NOT NULL,
    device_name character varying NOT NULL,
    status character varying DEFAULT 'pending'::character varying CHECK (status::text = ANY (ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying, 'cancelled'::character varying, 'aborted'::character varying]::text[])),  -- UPDATED: Added enum constraint
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    execution_time_ms integer,
    success boolean NOT NULL DEFAULT false,
    error_message text,
    script_configurations jsonb NOT NULL DEFAULT '[]'::jsonb,
    execution_config jsonb DEFAULT '{}'::jsonb,
    metadata jsonb DEFAULT '{}'::jsonb,
    script_result_ids uuid[] DEFAULT '{}'::uuid[],
    html_report_r2_path text,
    html_report_r2_url text,
    logs_r2_path text,
    logs_r2_url text,
    executed_by uuid,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now())
);

-- AI analysis cache table (NEW TABLE)
CREATE TABLE ai_analysis_cache (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    prompt text NOT NULL,
    analysis_result jsonb NOT NULL,
    compatibility_matrix jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone DEFAULT (now() + '01:00:00'::interval)
);


-- Add indexes for performance
CREATE INDEX idx_device_models_team_id ON device_models(team_id);
CREATE INDEX idx_device_team_id ON device(team_id);
-- controllers indexes removed - table does not exist
CREATE INDEX idx_environment_profiles_team_id ON environment_profiles(team_id);
CREATE INDEX idx_campaign_executions_team_id ON campaign_executions(team_id);
CREATE INDEX idx_campaign_executions_campaign_name ON campaign_executions(campaign_name);
CREATE INDEX idx_campaign_executions_host_name ON campaign_executions(host_name);
CREATE INDEX idx_campaign_executions_status ON campaign_executions(status);
CREATE INDEX idx_ai_analysis_cache_team_id ON ai_analysis_cache(team_id);
CREATE INDEX idx_ai_analysis_cache_expires_at ON ai_analysis_cache(expires_at);

-- Add comments
COMMENT ON TABLE device_models IS 'Device model definitions and capabilities';
COMMENT ON TABLE device IS 'Physical device instances';
-- controllers and campaigns table comments removed - tables do not exist
COMMENT ON TABLE environment_profiles IS 'Test environment configurations';
COMMENT ON TABLE campaign_executions IS 'Campaign execution tracking and results';
COMMENT ON TABLE ai_analysis_cache IS 'Caches AI analysis results for the two-step test case generation process';

-- Enable Row Level Security (RLS)
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_models ENABLE ROW LEVEL SECURITY;
ALTER TABLE device ENABLE ROW LEVEL SECURITY;
-- controllers and campaigns RLS removed - tables do not exist
ALTER TABLE environment_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_analysis_cache ENABLE ROW LEVEL SECURITY;

-- RLS Policies for teams table (updated to match actual working database)
CREATE POLICY "teams_access_policy" ON teams
FOR ALL 
TO public
USING (true);

-- RLS Policies for device_models table (updated to match actual working database)
CREATE POLICY "device_models_access_policy" ON device_models
FOR ALL 
TO public
USING (true);

-- RLS Policies for device table (updated to match actual working database)
CREATE POLICY "device_access_policy" ON device
FOR ALL 
TO public
USING (true);

-- controllers table RLS policies removed - table does not exist

-- RLS Policies for environment_profiles table (updated to match actual working database)
CREATE POLICY "environment_profiles_access_policy" ON environment_profiles
FOR ALL 
TO public
USING (true);

-- campaigns table RLS policies removed - table does not exist

-- RLS Policies for campaign_executions table (updated to match actual working database)
CREATE POLICY "campaign_executions_access_policy" ON campaign_executions
FOR ALL 
TO public
USING (true);

-- RLS Policies for ai_analysis_cache table
CREATE POLICY "ai_analysis_cache_access_policy" ON ai_analysis_cache
FOR ALL 
TO public
USING (true);

-- =============================================================================
-- DEFAULT DATA INSERTIONS
-- =============================================================================

-- Insert default team with fixed ID for consistent setup
INSERT INTO teams (id, name, description, tenant_id, created_by, is_default, created_at, updated_at)
VALUES (
    '7fdeb4bb-3639-4ec3-959f-b54769a219ce',
    'Default Team',
    'Default team for testing',
    '00000000-0000-0000-0000-000000000001',
    NULL,
    true,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
)
ON CONFLICT (id) DO NOTHING;

-- Insert basic device models for each team
-- This function will be called after teams are created to populate basic device models
CREATE OR REPLACE FUNCTION create_default_device_models(p_team_id uuid)
RETURNS void AS $$
BEGIN
    -- Only insert if no device models exist for this team
    IF NOT EXISTS (SELECT 1 FROM device_models WHERE team_id = p_team_id LIMIT 1) THEN
        
        -- Web device model
        INSERT INTO device_models (team_id, name, types, controllers, version, description, is_default)
        VALUES (
            p_team_id,
            'web',
            '["safari", "chrome", "firefox", "edge"]'::jsonb,
            '{"av": "", "web": "playwright", "power": "", "remote": "", "network": ""}'::jsonb,
            '',
            'Web browser testing via Playwright',
            true
        );

        -- Android TV device model
        INSERT INTO device_models (team_id, name, types, controllers, version, description, is_default)
        VALUES (
            p_team_id,
            'android_tv',
            '["Android TV", "Fire TV", "Nvidia Shield"]'::jsonb,
            '{"av": "hdmi_stream", "power": "", "remote": "android_tv", "network": ""}'::jsonb,
            '',
            'Android TV and streaming devices',
            true
        );

        -- STB (Set-Top Box) device model
        INSERT INTO device_models (team_id, name, types, controllers, version, description, is_default)
        VALUES (
            p_team_id,
            'stb',
            '["STB"]'::jsonb,
            '{}'::jsonb,
            '',
            'Generic Set-Top Box',
            true
        );

        -- Android Mobile device model
        INSERT INTO device_models (team_id, name, types, controllers, version, description, is_default)
        VALUES (
            p_team_id,
            'android_mobile',
            '["Android Phone", "Android TV"]'::jsonb,
            '{"av": "hdmi_stream", "power": "", "remote": "android_mobile", "network": ""}'::jsonb,
            '',
            'Android mobile devices',
            true
        );

        -- Apple TV device model
        INSERT INTO device_models (team_id, name, types, controllers, version, description, is_default)
        VALUES (
            p_team_id,
            'apple_tv',
            '["apple_tv"]'::jsonb,
            '{"av": "hdmi_stream", "power": "", "remote": "apple_tv", "network": ""}'::jsonb,
            '',
            'Apple TV devices',
            true
        );

    END IF;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically create default device models when a new team is created
CREATE OR REPLACE FUNCTION trigger_create_default_device_models()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM create_default_device_models(NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER after_team_insert
    AFTER INSERT ON teams
    FOR EACH ROW
    EXECUTE FUNCTION trigger_create_default_device_models();

COMMENT ON FUNCTION create_default_device_models(uuid) IS 'Creates default device models for a team';
COMMENT ON FUNCTION trigger_create_default_device_models() IS 'Trigger function to auto-create device models when a team is created';

-- Create device models for the default team (only if they don't exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM device_models WHERE team_id = '7fdeb4bb-3639-4ec3-959f-b54769a219ce' LIMIT 1) THEN
        INSERT INTO device_models (team_id, name, types, controllers, version, description, is_default)
        VALUES
            ('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'web', '["safari", "chrome", "firefox", "edge"]'::jsonb, '{"av": "", "web": "playwright", "power": "", "remote": "", "network": ""}'::jsonb, '', 'Web browser testing via Playwright', true),
            ('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'android_tv', '["Android TV", "Fire TV", "Nvidia Shield"]'::jsonb, '{"av": "hdmi_stream", "power": "", "remote": "android_tv", "network": ""}'::jsonb, '', 'Android TV and streaming devices', true),
            ('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'stb', '["STB"]'::jsonb, '{}'::jsonb, '', 'Generic Set-Top Box', true),
            ('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'android_mobile', '["Android Phone", "Android TV"]'::jsonb, '{"av": "hdmi_stream", "power": "", "remote": "android_mobile", "network": ""}'::jsonb, '', 'Android mobile devices', true),
            ('7fdeb4bb-3639-4ec3-959f-b54769a219ce', 'apple_tv', '["apple_tv"]'::jsonb, '{"av": "hdmi_stream", "power": "", "remote": "apple_tv", "network": ""}'::jsonb, '', 'Apple TV devices', true);
    END IF;
END $$;
