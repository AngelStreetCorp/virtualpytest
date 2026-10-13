"""screen_fingerprints table access (TASK-84). Logic lives in ``shared/src/lib/screen_memory.py``.

Hosts call ``resolve_or_create`` when a freeze alert opens; the triage worker calls ``get`` and
``update_fields``. Rows are cached per scope on the host for ``_TTL`` seconds so a burst of alerts
costs one read. Every function returns None / False on failure and never raises: screen memory
must not break alert creation.
"""
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from shared.src.lib import screen_memory
from shared.src.lib.utils.app_utils import DEFAULT_TEAM_ID
from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = "screen_fingerprints"
_TTL = 60
_cache: Dict[Tuple[str, str], Tuple[float, List[Dict[str, Any]]]] = {}
_pending = screen_memory.PendingScreens()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(scope: str, incident_type: str) -> List[Dict[str, Any]]:
    key = (scope, incident_type)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    res = (get_supabase_client().table(TABLE).select("*").eq("team_id", DEFAULT_TEAM_ID)
           .eq("scope", scope).eq("incident_type", incident_type).execute())
    rows = res.data or []
    _cache[key] = (time.time(), rows)
    return rows


def resolve_or_create(scope: str, incident_type: str, fp: Dict[str, str],
                      sample_image_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Match ``fp`` against the device's screens: ``{'id', 'dist', 'is_new', 'verdict'}``.

    None on failure, and None while ``fp`` is only a candidate seen fewer than ``ALERT_SCREEN_MIN_SEEN`` times:
    a new screen row is created only once it has been seen that often (no rows for splash screens)."""
    try:
        db = get_supabase_client()
        found = screen_memory.match_screen(fp, _rows(scope, incident_type))
        if found:
            row, dist = found
            seen = int(row.get("seen_count") or 0) + 1
            row["seen_count"] = seen
            db.table(TABLE).update({"seen_count": seen, "last_seen": _now(), "updated_at": _now()}) \
                .eq("id", row["id"]).eq("team_id", DEFAULT_TEAM_ID).execute()
            return {"id": row["id"], "dist": dist, "is_new": False, "verdict": row.get("verdict"), "seen": seen}
        cand = _pending.see((scope, incident_type), fp, time.time(), sample_image_path)
        if not cand:
            return None
        res = db.table(TABLE).insert({"team_id": DEFAULT_TEAM_ID, "scope": scope, "incident_type": incident_type,
                                      "dhash": cand["dhash"], "region_center": cand["region_center"],
                                      "seen_count": cand["count"],
                                      "sample_image_path": cand["sample"]}).execute()
        if not res.data:
            return None
        _cache.pop((scope, incident_type), None)
        return {"id": res.data[0]["id"], "dist": 0, "is_new": True, "verdict": "unknown", "seen": cand["count"]}
    except Exception as e:
        print(f"[@db:screen_fingerprints:resolve_or_create] {e}")
        return None


def get(screen_id: str) -> Optional[Dict[str, Any]]:
    try:
        res = (get_supabase_client().table(TABLE).select("*").eq("id", screen_id)
               .eq("team_id", DEFAULT_TEAM_ID).limit(1).execute())
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"[@db:screen_fingerprints:get] {e}")
        return None


def update_fields(screen_id: str, fields: Dict[str, Any]) -> bool:
    if not fields:
        return True
    try:
        fields = dict(fields, updated_at=_now())
        res = (get_supabase_client().table(TABLE).update(fields).eq("id", screen_id)
               .eq("team_id", DEFAULT_TEAM_ID).execute())
        return bool(res.data)
    except Exception as e:
        print(f"[@db:screen_fingerprints:update_fields] {e}")
        return False


def set_human_verdict(screen_id: str, expected: bool, alert_id: str) -> bool:
    """A person's Discard (expected) or Keep (bad) on an alert of this screen. A human verdict is trusted at once
    and is never overwritten by the model (``screen_memory.apply_ai_verdict``)."""
    return update_fields(screen_id, {"verdict": "expected" if expected else "bad", "source": "human",
                                     "verdict_by": alert_id})
