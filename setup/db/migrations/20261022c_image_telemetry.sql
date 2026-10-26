-- TASK-157: per-device image telemetry buckets (frames, bytes, frame age) + one `_host` row per bucket (process CPU/RSS, load per core).
-- Written by vpt-monitor-img (service role) when IMG_TELEMETRY=true; read by Grafana. Host-scoped infra telemetry like
-- system_metrics: no team_id, RLS service_role only. Retention: the writer deletes rows older than IMG_TELEMETRY_RETENTION_DAYS
-- (7) once a day; it is deliberately NOT wired into retention.cleanup_all() (static member list differs per database).
-- Additive and idempotent. Rollback: 20261022c_image_telemetry_rollback.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.image_telemetry_buckets (
    id                              BIGSERIAL PRIMARY KEY,
    host_name                       TEXT NOT NULL,
    device_id                       TEXT NOT NULL,            -- '_host' = the host's process row
    capture_folder                  TEXT,
    bucket_start                    TIMESTAMPTZ NOT NULL,
    bucket_seconds                  INTEGER NOT NULL,
    frames_arrived                  INTEGER,
    frames_analyzed                 INTEGER,
    frames_dropped                  INTEGER,
    image_bytes                     BIGINT,
    arrived_fps                     NUMERIC(7,2),
    estimated_image_throughput_bps  BIGINT,                   -- JPEG on disk, not stream bitrate, not network
    frame_age_p95_ms                NUMERIC(9,1),
    frame_age_max_ms                NUMERIC(9,1),
    queue_depth_max                 INTEGER,
    cpu_pct_monitor                 NUMERIC(7,1),             -- % of one core
    rss_monitor_bytes               BIGINT,
    cpu_pct_ffmpeg                  NUMERIC(7,1),
    rss_ffmpeg_bytes                BIGINT,
    load_per_core                   NUMERIC(7,2),
    samples_dropped                 INTEGER,
    schema_version                  SMALLINT NOT NULL DEFAULT 1,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT image_telemetry_buckets_key UNIQUE (host_name, device_id, bucket_start)
);

CREATE INDEX IF NOT EXISTS idx_image_telemetry_device_ts ON public.image_telemetry_buckets (device_id, bucket_start DESC);
CREATE INDEX IF NOT EXISTS idx_image_telemetry_host_ts   ON public.image_telemetry_buckets (host_name, bucket_start DESC);

COMMENT ON TABLE public.image_telemetry_buckets IS
    'TASK-157 image telemetry: 60 s buckets per device plus a _host row. NULL = not measured (never 0). Written by vpt-monitor-img.';

ALTER TABLE public.image_telemetry_buckets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_image_telemetry_buckets" ON public.image_telemetry_buckets;
CREATE POLICY "service_role_all_image_telemetry_buckets" ON public.image_telemetry_buckets
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.image_telemetry_buckets FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.image_telemetry_buckets_id_seq FROM anon, authenticated;
GRANT ALL ON public.image_telemetry_buckets TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.image_telemetry_buckets_id_seq TO service_role;

COMMIT;
