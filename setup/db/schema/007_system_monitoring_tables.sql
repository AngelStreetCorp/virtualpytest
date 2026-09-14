-- VirtualPyTest System Monitoring Tables Schema
-- This file contains tables for system metrics, device metrics, and incident tracking

-- Drop existing tables if they exist (for clean recreation)
DROP TABLE IF EXISTS system_incident CASCADE;
DROP TABLE IF EXISTS system_device_metrics CASCADE;
DROP TABLE IF EXISTS system_metrics CASCADE;
DROP SEQUENCE IF EXISTS system_incident_incident_id_seq CASCADE;

-- System metrics table for host-level monitoring
CREATE TABLE system_metrics (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    host_name text NOT NULL,
    server_name text,
    timestamp timestamp with time zone NOT NULL DEFAULT now(),
    cpu_percent numeric NOT NULL DEFAULT 0,
    memory_percent numeric NOT NULL DEFAULT 0,
    memory_used_gb numeric NOT NULL DEFAULT 0,
    memory_total_gb numeric NOT NULL DEFAULT 0,
    disk_percent numeric NOT NULL DEFAULT 0,
    disk_used_gb numeric NOT NULL DEFAULT 0,
    disk_total_gb numeric NOT NULL DEFAULT 0,
    uptime_seconds bigint DEFAULT 0,
    platform text,
    architecture text,
    ffmpeg_status jsonb DEFAULT '{}'::jsonb,
    monitor_status jsonb DEFAULT '{}'::jsonb,
    ffmpeg_service_uptime_seconds bigint DEFAULT 0,
    monitor_service_uptime_seconds bigint DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    cpu_temperature_celsius numeric,
    load_average_1m numeric(5,2),
    load_average_5m numeric(5,2),
    load_average_15m numeric(5,2),
    download_mbps numeric,
    upload_mbps numeric,
    speedtest_last_run timestamp with time zone,
    speedtest_age_seconds integer,
    disk_write_mb_per_sec numeric(10,2) DEFAULT 0
);

-- System device metrics table for per-device monitoring
CREATE TABLE system_device_metrics (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    host_name text NOT NULL,
    device_id text NOT NULL,
    device_name text NOT NULL,
    device_port text NOT NULL,
    device_model text NOT NULL,
    cpu_percent numeric NOT NULL DEFAULT 0,
    memory_percent numeric NOT NULL DEFAULT 0,
    memory_used_gb numeric NOT NULL DEFAULT 0,
    memory_total_gb numeric NOT NULL DEFAULT 0,
    disk_percent numeric NOT NULL DEFAULT 0,
    disk_used_gb numeric NOT NULL DEFAULT 0,
    disk_total_gb numeric NOT NULL DEFAULT 0,
    uptime_seconds bigint DEFAULT 0,
    platform text,
    architecture text,
    ffmpeg_status text NOT NULL DEFAULT 'unknown'::text,
    ffmpeg_uptime_seconds bigint DEFAULT 0,
    ffmpeg_last_activity timestamp with time zone,
    monitor_status text NOT NULL DEFAULT 'unknown'::text,
    monitor_uptime_seconds bigint DEFAULT 0,
    monitor_last_activity timestamp with time zone,
    timestamp timestamp with time zone NOT NULL DEFAULT now(),
    created_at timestamp with time zone DEFAULT now(),
    capture_folder text NOT NULL CHECK (capture_folder IS NOT NULL AND capture_folder <> ''::text AND capture_folder <> 'unknown'::text),
    video_device text,
    cpu_temperature_celsius numeric,
    load_average_1m numeric(5,2),
    load_average_5m numeric(5,2),
    load_average_15m numeric(5,2),
    disk_usage_capture text
);

-- Create sequence for system_incident table (must be created before the table)
CREATE SEQUENCE IF NOT EXISTS system_incident_incident_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- System incident table for incident management
CREATE TABLE system_incident (
    incident_id integer DEFAULT nextval('system_incident_incident_id_seq'::regclass) PRIMARY KEY,
    incident_uuid uuid DEFAULT gen_random_uuid() UNIQUE,
    host_name character varying NOT NULL,
    device_id character varying NOT NULL,
    device_name character varying NOT NULL,
    capture_folder character varying NOT NULL,
    video_device character varying,
    incident_type character varying NOT NULL,
    severity character varying NOT NULL,
    component character varying NOT NULL,
    status character varying NOT NULL DEFAULT 'open'::character varying,
    detected_at timestamp with time zone NOT NULL,
    acknowledged_at timestamp with time zone,
    resolved_at timestamp with time zone,
    closed_at timestamp with time zone,
    detection_to_ack_minutes integer,
    ack_to_resolution_minutes integer,
    total_duration_minutes integer,
    description text,
    root_cause text,
    resolution_notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

-- Add indexes for performance
CREATE INDEX idx_system_metrics_host_name ON system_metrics(host_name);
CREATE INDEX idx_system_metrics_server_name ON system_metrics(server_name);
CREATE INDEX idx_system_metrics_timestamp ON system_metrics(timestamp);
CREATE INDEX idx_system_metrics_created_at ON system_metrics(created_at);
CREATE INDEX idx_system_metrics_speedtest_last_run ON system_metrics(speedtest_last_run);

CREATE INDEX idx_system_device_metrics_host_name ON system_device_metrics(host_name);
CREATE INDEX idx_system_device_metrics_device_id ON system_device_metrics(device_id);
CREATE INDEX idx_system_device_metrics_device_name ON system_device_metrics(device_name);
CREATE INDEX idx_system_device_metrics_timestamp ON system_device_metrics(timestamp);
CREATE INDEX idx_system_device_metrics_ffmpeg_status ON system_device_metrics(ffmpeg_status);
CREATE INDEX idx_system_device_metrics_monitor_status ON system_device_metrics(monitor_status);
CREATE INDEX idx_system_device_metrics_capture_folder ON system_device_metrics(capture_folder);

CREATE INDEX idx_system_incident_host_name ON system_incident(host_name);
CREATE INDEX idx_system_incident_device_id ON system_incident(device_id);
CREATE INDEX idx_system_incident_incident_type ON system_incident(incident_type);
CREATE INDEX idx_system_incident_status ON system_incident(status);
CREATE INDEX idx_system_incident_detected_at ON system_incident(detected_at);
CREATE INDEX idx_system_incident_severity ON system_incident(severity);

-- Add comments
COMMENT ON TABLE system_metrics IS 'Retention: Keep 7 days of 1-minute data, 30 days of hourly aggregates';
COMMENT ON COLUMN system_metrics.timestamp IS 'UTC timestamp for system metrics collection';
COMMENT ON COLUMN system_metrics.created_at IS 'UTC timestamp for record creation';
COMMENT ON COLUMN system_metrics.server_name IS 'Server identifier for grouping metrics across multiple servers (from SERVER_NAME env var)';
COMMENT ON COLUMN system_metrics.ffmpeg_service_uptime_seconds IS 'Duration FFmpeg service has been continuously active in seconds';
COMMENT ON COLUMN system_metrics.monitor_service_uptime_seconds IS 'Duration Monitor service has been continuously active in seconds';
COMMENT ON COLUMN system_metrics.cpu_temperature_celsius IS 'CPU temperature in Celsius from vcgencmd or thermal zones';
COMMENT ON COLUMN system_metrics.load_average_1m IS 'System load average over 1 minute (number of processes in runnable state)';
COMMENT ON COLUMN system_metrics.load_average_5m IS 'System load average over 5 minutes (number of processes in runnable state)';
COMMENT ON COLUMN system_metrics.load_average_15m IS 'System load average over 15 minutes (number of processes in runnable state)';
COMMENT ON COLUMN system_metrics.download_mbps IS 'Download speed in Mbps from speedtest (cached 10 min)';
COMMENT ON COLUMN system_metrics.upload_mbps IS 'Upload speed in Mbps from speedtest (cached 10 min)';
COMMENT ON COLUMN system_metrics.speedtest_last_run IS 'UTC timestamp when speedtest was last executed';
COMMENT ON COLUMN system_metrics.speedtest_age_seconds IS 'Age of cached speedtest data in seconds';
COMMENT ON COLUMN system_metrics.disk_write_mb_per_sec IS 'Disk write speed in MB/s - tracks SD card write activity for health monitoring';

COMMENT ON TABLE system_device_metrics IS 'Stores per-device system performance and process status data';
COMMENT ON COLUMN system_device_metrics.device_name IS 'Real device name from device registration (e.g., Samsung TV Living Room)';
COMMENT ON COLUMN system_device_metrics.device_port IS 'Capture port identifier (e.g., capture1, capture2)';
COMMENT ON COLUMN system_device_metrics.ffmpeg_uptime_seconds IS 'Duration FFmpeg was continuously active before current status';
COMMENT ON COLUMN system_device_metrics.ffmpeg_last_activity IS 'UTC timestamp when FFmpeg last created files';
COMMENT ON COLUMN system_device_metrics.monitor_uptime_seconds IS 'Duration Monitor was continuously active before current status';
COMMENT ON COLUMN system_device_metrics.monitor_last_activity IS 'UTC timestamp when Monitor last created JSON files';
COMMENT ON COLUMN system_device_metrics.timestamp IS 'UTC timestamp for device metrics collection';
COMMENT ON COLUMN system_device_metrics.created_at IS 'UTC timestamp for record creation';
COMMENT ON COLUMN system_device_metrics.capture_folder IS 'Capture folder name (capture1, capture2, etc.) - must not be NULL as it indicates incomplete device configuration';
COMMENT ON COLUMN system_device_metrics.cpu_temperature_celsius IS 'CPU temperature in Celsius from vcgencmd or thermal zones';
COMMENT ON COLUMN system_device_metrics.load_average_1m IS 'System load average over 1 minute (number of processes in runnable state)';
COMMENT ON COLUMN system_device_metrics.load_average_5m IS 'System load average over 5 minutes (number of processes in runnable state)';
COMMENT ON COLUMN system_device_metrics.load_average_15m IS 'System load average over 15 minutes (number of processes in runnable state)';
COMMENT ON COLUMN system_device_metrics.disk_usage_capture IS 'Disk usage for capture folder (e.g., "2.5G", "850M") from du -sh command';

COMMENT ON TABLE system_incident IS 'System incident management and tracking';

-- Enable Row Level Security on all monitoring tables
ALTER TABLE system_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_device_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_incident ENABLE ROW LEVEL SECURITY;

-- Create RLS policies (open access for monitoring data)
CREATE POLICY system_metrics_access_policy ON system_metrics
    FOR ALL USING (true);

CREATE POLICY system_device_metrics_access_policy ON system_device_metrics
    FOR ALL USING (true);

CREATE POLICY system_incident_access_policy ON system_incident
    FOR ALL USING (true);

-- Create triggers for updated_at timestamp
CREATE OR REPLACE FUNCTION update_system_incident_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER system_incident_updated_at_trigger
    BEFORE UPDATE ON system_incident
    FOR EACH ROW
    EXECUTE FUNCTION update_system_incident_updated_at();

-- Create summary views with security_invoker for monitoring dashboards
CREATE OR REPLACE VIEW device_availability_summary
WITH (security_invoker = true)
AS
WITH device_availability AS (
    SELECT 
        system_device_metrics.device_name,
        system_device_metrics.capture_folder,
        count(*) AS total_minutes,
        count(
            CASE
                WHEN ((system_device_metrics.ffmpeg_status = 'active'::text) AND (system_device_metrics.monitor_status = 'active'::text)) THEN 1
                ELSE NULL::integer
            END) AS healthy_minutes
    FROM system_device_metrics
    WHERE (system_device_metrics."timestamp" >= (now() - '01:00:00'::interval))
    GROUP BY system_device_metrics.device_name, system_device_metrics.capture_folder
)
SELECT 
    device_name,
    capture_folder,
    round((((healthy_minutes)::numeric * 100.0) / (total_minutes)::numeric), 2) AS availability_percent,
    CASE
        WHEN ((((healthy_minutes)::numeric * 100.0) / (total_minutes)::numeric) < (90)::numeric) THEN 1
        ELSE 0
    END AS is_low_availability
FROM device_availability
WHERE (total_minutes > 10);

CREATE OR REPLACE VIEW active_incidents_summary
WITH (security_invoker = true)
AS
SELECT 
    count(
        CASE
            WHEN ((status)::text = ANY ((ARRAY['open'::character varying, 'in_progress'::character varying])::text[])) THEN 1
            ELSE NULL::integer
        END) AS active_incidents,
    count(
        CASE
            WHEN (((status)::text = ANY ((ARRAY['open'::character varying, 'in_progress'::character varying])::text[])) AND ((severity)::text = 'critical'::text)) THEN 1
            ELSE NULL::integer
        END) AS critical_incidents,
    count(
        CASE
            WHEN (detected_at >= (now() - '00:05:00'::interval)) THEN 1
            ELSE NULL::integer
        END) AS new_incidents_5min,
    max(detected_at) AS last_incident_time
FROM system_incident;

COMMENT ON VIEW device_availability_summary IS 'Real-time device availability metrics over the last hour';
COMMENT ON VIEW active_incidents_summary IS 'Summary of active and recent incidents for dashboard display';
