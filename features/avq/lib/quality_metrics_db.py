"""
Quality Metrics Database Functions (AVQ).

Store/query per-minute audio/video quality KPIs in the `quality_metrics` table.
Mirrors the system_metrics_db.py pattern. See docs/agent/AVQ_IMPLEMENTATION.md.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

logger = logging.getLogger('avq')

# Columns the table accepts (anything else in the metrics dict is dropped).
_NUMERIC_COLS = [
    'window_seconds',
    'blurriness_score', 'blockiness_score', 'jerkiness_score',
    'clean_video_seconds', 'video_availability', 'video_mos',
    'audio_level_db',
    'loudness_lkfs', 'loudness_range', 'true_peak_dbtp',
    'saturation_score', 'silence_seconds', 'audio_availability', 'audio_mos',
    # incidents (from the realtime detector)
    'blackscreen_seconds', 'freeze_seconds', 'macroblocks_seconds',
    # subtitles / transcription / translation (null when feature disabled)
    'subtitle_availability', 'transcript_available',
]

_TEXT_COLS = [
    'subtitle_language', 'transcript_language',
    'translation_languages', 'dubbed_languages',
    # recognised text itself (so the L2 page can show WHAT was found)
    'transcript_text', 'subtitle_text',
]


def store_quality_metrics(host_name: str, device_info: Dict[str, Any],
                          metrics: Dict[str, Any]) -> bool:
    """Insert one quality_metrics row.

    Args:
        host_name: e.g. 'host1'
        device_info: dict from get_device_info_from_capture_folder()
                     (device_id, device_name, capture_path)
        metrics: dict from avq_analyze.analyze_device()
    """
    try:
        supabase = get_supabase_client()
        if supabase is None:
            return False

        capture_folder = device_info.get('capture_path') or device_info.get('capture_folder')
        if not capture_folder or capture_folder in ('unknown', 'null', None):
            logger.warning("Rejected quality_metrics: invalid capture_folder (%s)", capture_folder)
            return False

        row: Dict[str, Any] = {
            'host_name': host_name,
            'device_id': device_info.get('device_id', 'unknown'),
            'device_name': device_info.get('device_name', 'Unknown Device'),
            'capture_folder': capture_folder,
            'timestamp': metrics.get('timestamp') or datetime.now(timezone.utc).isoformat(),
            'events': metrics.get('events') or {},
        }
        if metrics.get('positions'):                 # RLE'd Localize screen position
            row['positions'] = metrics['positions']
        for col in _NUMERIC_COLS + _TEXT_COLS:
            if metrics.get(col) is not None:
                row[col] = metrics[col]

        result = supabase.table('quality_metrics').insert(row).execute()
        if result.data:
            logger.info("✅ AVQ stored: %s/%s vMOS=%s aMOS=%s",
                        host_name, capture_folder,
                        metrics.get('video_mos'), metrics.get('audio_mos'))
            return True
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to store quality_metrics: %s", e)
        return False


def get_quality_metrics(device_id: str, since_iso: str,
                        host_name: Optional[str] = None,
                        until_iso: Optional[str] = None) -> List[Dict[str, Any]]:
    """Time-ordered quality_metrics rows for a device (for the L2 page / API).

    IMPORTANT: device_id is NOT unique across hosts (e.g. 'device3' exists on both
    host1 and host3), so host_name MUST be supplied or rows from different
    physical devices get mixed. We also order DESC + limit and reverse, so when a
    device exceeds the PostgREST 1000-row cap we keep the MOST RECENT rows (not the
    oldest) and still hand the timeline an ascending series.
    """
    try:
        supabase = get_supabase_client()
        if supabase is None:
            return []
        q = (supabase.table('quality_metrics').select('*')
             .eq('device_id', device_id)
             .gte('timestamp', since_iso))
        if host_name:
            q = q.eq('host_name', host_name)
        if until_iso:
            q = q.lte('timestamp', until_iso)
        q = q.order('timestamp', desc=True).limit(1440)
        result = q.execute()
        rows = result.data or []
        rows.reverse()  # ascending for the timeline
        return rows
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to query quality_metrics: %s", e)
        return []
