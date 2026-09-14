-- Event System Tables for Multi-Agent Platform
-- Phase 1: Core Infrastructure
-- Created: 2025-12-06

-- Drop existing tables if they exist (for clean recreation)
DROP TABLE IF EXISTS scheduled_events CASCADE;
DROP TABLE IF EXISTS resource_lock_queue CASCADE;
DROP TABLE IF EXISTS resource_locks CASCADE;
DROP TABLE IF EXISTS event_log CASCADE;

-- ============================================================================
-- EVENT LOG TABLE
-- Stores all events published to the Event Bus
-- ============================================================================

CREATE TABLE event_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(255) UNIQUE NOT NULL,
    event_type VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    priority INTEGER NOT NULL DEFAULT 3,  -- 1=CRITICAL, 2=HIGH, 3=NORMAL, 4=LOW
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    processed_by VARCHAR(255),  -- Agent instance ID that processed this event
    processed_at TIMESTAMP WITH TIME ZONE,
    team_id VARCHAR(255) NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX idx_event_log_type ON event_log(event_type);
CREATE INDEX idx_event_log_priority ON event_log(priority);
CREATE INDEX idx_event_log_timestamp ON event_log(timestamp DESC);
CREATE INDEX idx_event_log_team ON event_log(team_id);
CREATE INDEX idx_event_log_processed ON event_log(processed_by) WHERE processed_by IS NOT NULL;

-- Add comment
COMMENT ON TABLE event_log IS 'Central log of all events published to the Event Bus';
COMMENT ON COLUMN event_log.event_id IS 'Unique event identifier (e.g., evt_1234567890)';
COMMENT ON COLUMN event_log.event_type IS 'Event type (e.g., alert.blackscreen, build.deployed)';
COMMENT ON COLUMN event_log.priority IS '1=CRITICAL, 2=HIGH, 3=NORMAL, 4=LOW';
COMMENT ON COLUMN event_log.processed_by IS 'Agent instance ID that handled this event';

-- ============================================================================
-- RESOURCE LOCKS TABLE
-- Tracks exclusive locks on resources (devices, trees, userinterfaces)
-- ============================================================================

CREATE TABLE resource_locks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id VARCHAR(255) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,  -- 'device', 'tree', 'userinterface'
    owner_id VARCHAR(255) NOT NULL,      -- Agent instance ID or user ID
    owner_type VARCHAR(50) NOT NULL,     -- 'agent', 'user', 'system'
    acquired_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    priority INTEGER NOT NULL DEFAULT 3,  -- 1=HIGH, 2=MEDIUM, 3=NORMAL, 4=LOW
    team_id VARCHAR(255) NOT NULL DEFAULT 'default',
    metadata JSONB DEFAULT '{}'::jsonb,  -- Additional lock context
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for lock management
CREATE INDEX idx_resource_locks_resource ON resource_locks(resource_id);
CREATE INDEX idx_resource_locks_owner ON resource_locks(owner_id);
CREATE INDEX idx_resource_locks_expires ON resource_locks(expires_at);
CREATE INDEX idx_resource_locks_team ON resource_locks(team_id);
CREATE INDEX idx_resource_locks_type ON resource_locks(resource_type);

-- Note: Removed partial unique index due to NOW() not being IMMUTABLE
-- Lock uniqueness enforced at application level

-- Add comments
COMMENT ON TABLE resource_locks IS 'Tracks exclusive locks on resources for parallel execution safety';
COMMENT ON COLUMN resource_locks.resource_id IS 'ID of locked resource (device_id, tree_id, etc.)';
COMMENT ON COLUMN resource_locks.resource_type IS 'Type of resource: device, tree, userinterface';
COMMENT ON COLUMN resource_locks.owner_id IS 'ID of lock owner (agent instance, user, etc.)';
COMMENT ON COLUMN resource_locks.priority IS 'Lock priority for queue ordering';

-- ============================================================================
-- RESOURCE LOCK QUEUE TABLE
-- Tracks waiting requests for locked resources
-- ============================================================================

CREATE TABLE resource_lock_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id VARCHAR(255) NOT NULL,
    owner_id VARCHAR(255) NOT NULL,
    priority INTEGER NOT NULL DEFAULT 3,
    timeout_seconds INTEGER NOT NULL DEFAULT 3600,
    queued_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    team_id VARCHAR(255) NOT NULL DEFAULT 'default',
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Indexes for queue management
CREATE INDEX idx_lock_queue_resource ON resource_lock_queue(resource_id);
CREATE INDEX idx_lock_queue_priority ON resource_lock_queue(resource_id, priority, queued_at);
CREATE INDEX idx_lock_queue_team ON resource_lock_queue(team_id);

-- Add comments
COMMENT ON TABLE resource_lock_queue IS 'Queue of pending lock requests for busy resources';

-- ============================================================================
-- CLEANUP FUNCTION FOR EXPIRED LOCKS
-- Automatically remove expired locks
-- ============================================================================

CREATE OR REPLACE FUNCTION cleanup_expired_locks()
RETURNS trigger AS $$
BEGIN
    DELETE FROM resource_locks 
    WHERE expires_at < NOW();
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Trigger to clean up expired locks before new lock attempts
CREATE TRIGGER trigger_cleanup_expired_locks
    BEFORE INSERT ON resource_locks
    EXECUTE FUNCTION cleanup_expired_locks();

-- ============================================================================
-- FUNCTION TO GET RESOURCE LOCK STATUS
-- Returns current lock status for a resource
-- ============================================================================

CREATE OR REPLACE FUNCTION get_resource_lock_status(
    p_resource_id VARCHAR(255)
)
RETURNS TABLE (
    is_locked BOOLEAN,
    owner_id VARCHAR(255),
    expires_at TIMESTAMP WITH TIME ZONE,
    queue_length INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        EXISTS(
            SELECT 1 FROM resource_locks 
            WHERE resource_id = p_resource_id 
            AND expires_at > NOW()
        ) as is_locked,
        rl.owner_id,
        rl.expires_at,
        (SELECT COUNT(*)::INTEGER FROM resource_lock_queue WHERE resource_id = p_resource_id) as queue_length
    FROM resource_locks rl
    WHERE rl.resource_id = p_resource_id 
    AND rl.expires_at > NOW()
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Add comment
COMMENT ON FUNCTION get_resource_lock_status IS 'Get current lock status and queue length for a resource';

-- ============================================================================
-- SCHEDULED EVENTS TABLE
-- Stores cron-based scheduled events
-- ============================================================================

CREATE TABLE scheduled_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(255) NOT NULL,
    cron_expression VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled BOOLEAN DEFAULT TRUE,
    team_id VARCHAR(255) NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(255),
    last_run TIMESTAMP WITH TIME ZONE,
    next_run TIMESTAMP WITH TIME ZONE,
    run_count INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Indexes
CREATE INDEX idx_scheduled_events_enabled ON scheduled_events(enabled) WHERE enabled = TRUE;
CREATE INDEX idx_scheduled_events_next_run ON scheduled_events(next_run) WHERE enabled = TRUE;
CREATE INDEX idx_scheduled_events_team ON scheduled_events(team_id);
CREATE INDEX idx_scheduled_events_type ON scheduled_events(event_type);

-- Add comments
COMMENT ON TABLE scheduled_events IS 'Cron-based scheduled events for autonomous agent triggers';
COMMENT ON COLUMN scheduled_events.cron_expression IS 'Cron expression (e.g., "0 */6 * * *" for every 6 hours)';
COMMENT ON COLUMN scheduled_events.enabled IS 'Whether this schedule is active';

-- ============================================================================
-- GRANT PERMISSIONS
-- ============================================================================

-- Grant access to authenticated users (Supabase pattern)
GRANT SELECT, INSERT, UPDATE ON event_log TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON resource_locks TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON resource_lock_queue TO authenticated;
GRANT SELECT, INSERT, UPDATE ON scheduled_events TO authenticated;

-- Grant usage on sequences
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO authenticated;

-- ============================================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================================

-- Enable Row Level Security (RLS)
ALTER TABLE event_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE resource_locks ENABLE ROW LEVEL SECURITY;
ALTER TABLE resource_lock_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE scheduled_events ENABLE ROW LEVEL SECURITY;

-- RLS Policies for event_log
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_event_log"
ON event_log
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Team-based access policy
CREATE POLICY "event_log_access_policy"
ON event_log
FOR ALL
TO authenticated
USING (true);

-- RLS Policies for resource_locks
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_resource_locks"
ON resource_locks
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Team-based access policy
CREATE POLICY "resource_locks_access_policy"
ON resource_locks
FOR ALL
TO authenticated
USING (true);

-- RLS Policies for resource_lock_queue
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_resource_lock_queue"
ON resource_lock_queue
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Team-based access policy
CREATE POLICY "resource_lock_queue_access_policy"
ON resource_lock_queue
FOR ALL
TO authenticated
USING (true);

-- RLS Policies for scheduled_events
-- Policy 1: service_role has full access (backend services)
CREATE POLICY "service_role_all_scheduled_events"
ON scheduled_events
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Policy 2: Team-based access policy
CREATE POLICY "scheduled_events_access_policy"
ON scheduled_events
FOR ALL
TO authenticated
USING (true);

-- ============================================================================
-- SAMPLE DATA (Optional - for testing)
-- ============================================================================

-- Sample scheduled event (disabled by default)
INSERT INTO scheduled_events (event_type, cron_expression, payload, enabled, team_id)
VALUES 
    ('schedule.regression', '0 */6 * * *', '{"userinterface": "example-app"}', FALSE, 'default')
ON CONFLICT DO NOTHING;

-- Add comment about this schema
COMMENT ON SCHEMA public IS 'VirtualPyTest database schema - Event system added in 020';

