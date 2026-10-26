"""Sighting counters and durable thumbnails on screen_fingerprints rows.

TASK-159: rows are created by ``screen_fingerprints_db.register_screen`` only; this module counts a Localize
sighting on a row that exists (``bump_known_screen_sighting``) and stores its thumbnail.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib import screen_memory

TABLE = 'screen_fingerprints'
# A durable sample: the host's rolling frame URL is gone in minutes, so the server stores a small
# JPEG in sample_image_path itself (data URI) the first time it sees the screen.
THUMB_PREFIX = 'data:image/'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _thumb_uri(frame) -> Optional[str]:
    """A 320 px JPEG data URI of a frame (numpy image), or None."""
    try:
        import base64
        import cv2
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (320, max(1, int(h * 320 / w))), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return THUMB_PREFIX + 'jpeg;base64,' + base64.b64encode(buf.tobytes()).decode() if ok else None
    except Exception:
        return None


def bump_known_screen_sighting(*, team_id: str, screen_id: str, frame=None) -> None:
    """Count one Localize sighting of an UNCLASSIFIED screen (verdict 'unknown') on its row.

    Only unclassified rows are touched: the alert audit gate (screen_memory.should_audit, stamped by
    incident_manager) reads seen_count of TRUSTED rows, so those keep counting alert sightings only.
    The caller debounces to one call per sighting episode. Never raises."""
    if not team_id or not screen_id:
        return
    try:
        db = get_supabase_client()
        res = (db.table(TABLE).select('seen_count, sample_image_path').eq('id', screen_id).eq('team_id', team_id)
               .eq('verdict', 'unknown').is_('merged_into', 'null').limit(1).execute())
        rows = res.data or []
        if not rows:
            return
        upd = {'seen_count': int(rows[0].get('seen_count') or 0) + 1, 'last_seen': _now(), 'updated_at': _now()}
        # the host holds the live frame right now: keep a durable sample for the auto-classifier (BUG-0674)
        if frame is not None and not str(rows[0].get('sample_image_path') or '').startswith(THUMB_PREFIX):
            uri = _thumb_uri(frame)
            if uri:
                upd['sample_image_path'] = uri
        db.table(TABLE).update(upd).eq('id', screen_id).eq('team_id', team_id).execute()
    except Exception as e:
        print(f'[@db:screen_fingerprints_bump:bump_known_screen_sighting] {e}')


def set_sample_thumb(*, team_id: str, screen_id: str, data_uri: str) -> bool:
    """Store a durable thumbnail (data URI) as the row's sample. Never raises."""
    try:
        get_supabase_client().table(TABLE).update({'sample_image_path': data_uri, 'updated_at': _now()}) \
            .eq('id', screen_id).eq('team_id', team_id).execute()
        return True
    except Exception as e:
        print(f'[@db:screen_fingerprints_bump:set_sample_thumb] {e}')
        return False
