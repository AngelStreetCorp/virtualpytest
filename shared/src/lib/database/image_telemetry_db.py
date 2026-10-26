"""Image telemetry rows (TASK-157): per-device and per-host 60 s buckets in ``image_telemetry_buckets``.

Schema: setup/db/schema/081_image_telemetry.sql. Written by the img monitor's batch thread
(backend_host/scripts/monitor/img_telemetry.py) through the shared Supabase client (which carries the short
connect/read timeouts); read by Grafana. ``device_id = '_host'`` rows carry the process CPU/RSS and load per core.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from shared.src.lib.utils.supabase_utils import get_supabase_client

logger = logging.getLogger('capture_monitor')

TABLE = 'image_telemetry_buckets'
CONFLICT = 'host_name,device_id,bucket_start'
COLUMNS = (
    'host_name', 'device_id', 'capture_folder', 'bucket_start', 'bucket_seconds',
    'frames_arrived', 'frames_analyzed', 'frames_dropped', 'image_bytes', 'arrived_fps',
    'estimated_image_throughput_bps', 'frame_age_p95_ms', 'frame_age_max_ms', 'queue_depth_max',
    'cpu_pct_monitor', 'rss_monitor_bytes', 'cpu_pct_ffmpeg', 'rss_ffmpeg_bytes', 'load_per_core',
    'samples_dropped', 'schema_version',
)


def upsert_rows(rows: List[Dict[str, Any]]) -> None:
    """Idempotent batch write: the same (host, device, bucket) twice overwrites. Raises on failure so the caller backs off.
    Every row carries every column (None where unsupported) so PostgREST gets one uniform batch."""
    if not rows:
        return
    client = get_supabase_client()
    if client is None:
        raise RuntimeError('no database client')
    payload = [{c: r.get(c) for c in COLUMNS} for r in rows]
    client.table(TABLE).upsert(payload, on_conflict=CONFLICT).execute()


def prune(retention_days: int) -> None:
    client = get_supabase_client()
    if client is None:
        raise RuntimeError('no database client')
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    client.table(TABLE).delete().lt('bucket_start', cutoff).execute()
