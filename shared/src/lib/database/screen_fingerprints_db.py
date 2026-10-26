"""screen_fingerprints table access (TASK-84, TASK-159). Logic lives in ``shared/src/lib/screen_memory.py``.

``register_screen`` is the only creator of rows (Localize in the monitor, and the freeze alert when Localize gave no
screen); the triage worker calls ``get`` and ``update_fields``. Reads for Localize are cached per scope for ``_TTL``
seconds so a burst costs one read. Every function returns None / False on failure and never raises: screen memory
must not break alert creation.
"""
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from shared.src.lib import screen_memory
from shared.src.lib.utils.app_utils import DEFAULT_TEAM_ID
from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = "screen_fingerprints"
_TTL = 60
_cache: Dict[Tuple[str, str], Tuple[float, List[Dict[str, Any]]]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_PAGE = 1000
_ROW_CAP = 5000   # a device with more live screens than this is a runaway: warn, match against the first rows only


def _device_rows(team_id: str, scope: str) -> List[Dict[str, Any]]:
    """Live (not merged) rows of one device, read fresh: the registry must see a row another process just made.
    Read in pages (PostgREST caps one response); capped at ``_ROW_CAP`` rows with a warning."""
    rows: List[Dict[str, Any]] = []
    while len(rows) < _ROW_CAP:
        res = (get_supabase_client().table(TABLE).select("*").eq("team_id", team_id).eq("scope", scope)
               .is_("merged_into", "null").order("first_seen").range(len(rows), len(rows) + _PAGE - 1).execute())
        page = res.data or []
        rows.extend(page)
        if len(page) < _PAGE:
            break
    else:
        print(f"[@db:screen_fingerprints:_device_rows] {scope}: more than {_ROW_CAP} screen rows, matching the first {_ROW_CAP}")
    return [r for r in rows if r.get("dhash") and r.get("region_center")]


def fp_from_blob(fingerprint: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """``{'dhash', 'region_center'}`` out of a v6 fingerprint blob (``compute_fingerprint``), None when it has none."""
    if not isinstance(fingerprint, dict):
        return None
    regions = fingerprint.get("regions")
    center = regions.get("center") if isinstance(regions, dict) else None
    dhash = fingerprint.get("dhash")
    return {"dhash": dhash, "region_center": center} if dhash and center else None


def _drop_cache(team_id: str, scope: str) -> None:
    _cache.pop((f"{team_id}:{scope}", "*"), None)


def register_screen(team_id: str, scope: str, fp: Dict[str, str], *, fingerprint: Optional[Dict[str, Any]] = None,
                    userinterface: Optional[str] = None, sample_image_path: Optional[str] = None
                    ) -> Optional[Dict[str, Any]]:
    """The one place a screen row is created (TASK-159). One call = one sighting (the caller counts per transition).

    The frame's ``fp`` (``screen_memory.fingerprint_frame``) is matched against the device's rows within
    ``match_screen`` tolerance, whatever made them: a hit counts a sighting, a miss makes the next ``unknown_N`` row
    (number and insert in one DB function). Returns ``{'id', 'label', 'dist', 'is_new', 'verdict', 'seen'}``, None on failure."""
    try:
        hit = _match_and_count(team_id, scope, fp, fingerprint, sample_image_path)
        if hit:
            return hit
        res = get_supabase_client().rpc("register_screen_row", {
            "p_team_id": team_id, "p_scope": scope, "p_dhash": fp["dhash"], "p_region_center": fp["region_center"],
            "p_fingerprint": fingerprint, "p_userinterface": (userinterface or "").strip() or None,
            "p_sample": sample_image_path}).execute()
        row = (res.data or [None])[0]
        if not row:
            return None
        _drop_cache(team_id, scope)
        return {"id": row["id"], "label": row["label"], "dist": 0, "is_new": True, "verdict": "unknown", "seen": 1}
    except Exception as e:
        print(f"[@db:screen_fingerprints:register_screen] {e}")
        return None


def count_screen_sighting(team_id: str, scope: str, fp: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """A sighting of a screen the device already has (the Localize button, host routes, replay worker): counts it on
    the matching row and never creates one. None when the screen is not registered yet."""
    try:
        return _match_and_count(team_id, scope, fp)
    except Exception as e:
        print(f"[@db:screen_fingerprints:count_screen_sighting] {e}")
        return None


def count_sighting_by_id(team_id: str, screen_id: str, frame=None,
                         fingerprint: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """One more sighting of a screen Localize already named for the frame (the freeze alert reads its ``screen_id``
    instead of matching again). A merged row is followed to the row that was kept. ``frame`` (BGR image) gives a row that has
    no durable picture its thumbnail, so the AI can name it later. None when the row is gone.

    ``fingerprint`` is the caller's v6 blob for the frame (TASK-162). A row registered before fingerprints existed keeps
    ``fingerprint = NULL`` for ever unless somebody hands it one, and this is the path a frozen screen takes: the freeze
    sees the screen again and can fill it -- once, through the single writer.
    """
    try:
        db = get_supabase_client()
        for _ in range(3):
            res = db.table(TABLE).select("*").eq("id", screen_id).eq("team_id", team_id).limit(1).execute()
            if not res.data:
                return None
            row = res.data[0]
            if not row.get("merged_into"):
                break
            screen_id = row["merged_into"]
        seen = int(row.get("seen_count") or 0) + 1
        upd = {"seen_count": seen, "last_seen": _now(), "updated_at": _now()}
        if frame is not None and not str(row.get("sample_image_path") or "").startswith("data:image/"):
            from shared.src.lib.database.screen_fingerprints_bump import _thumb_uri
            uri = _thumb_uri(frame)
            if uri:
                upd["sample_image_path"] = uri
        db.table(TABLE).update(upd).eq("id", row["id"]).eq("team_id", team_id).execute()
        # TASK-162: fill a missing fingerprint through the single writer (never over an existing one).
        if fingerprint and not row.get("fingerprint"):
            link_screen_fingerprint(team_id, row["id"], fingerprint)
        return {"id": row["id"], "label": row.get("label"), "dist": 0, "is_new": False,
                "verdict": row.get("verdict"), "seen": seen}
    except Exception as e:
        print(f"[@db:screen_fingerprints:count_sighting_by_id] {e}")
        return None


def link_screen_fingerprint(team_id: str, row_id: str, fingerprint: Optional[Dict[str, Any]],
                            node_id: Optional[str] = None) -> bool:
    """Write a fingerprint onto a screen row, ONCE (TASK-159 G7).

    The single writer is the DB function ``link_screen_fingerprint`` (migration 20261023b): it fills
    only a row whose ``fingerprint`` IS NULL, never touches the label (a name goes through
    ``name_screen_row``) and never deletes.  Returns False when the row already had a fingerprint
    or the write was refused.

    ``node_id`` is set when the fingerprint came from a navigation tree node, so the row is known to
    BE that node.  It is left alone otherwise, so a plain backfill never claims a tree link.
    """
    if not fingerprint or not fingerprint.get('dhash'):
        return False
    try:
        res = get_supabase_client().rpc("link_screen_fingerprint", {
            "p_team_id": team_id, "p_id": row_id,
            "p_fingerprint": fingerprint, "p_node_id": node_id}).execute()
        data = res.data
        n = data[0] if isinstance(data, list) and data else data
        return bool(n)
    except Exception as e:  # noqa: BLE001
        print(f"[@db:screen_fingerprints:link_screen_fingerprint] {e}")
        return False


def _match_and_count(team_id: str, scope: str, fp: Dict[str, str],
                     fingerprint: Optional[Dict[str, Any]] = None,
                     sample_image_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    found = screen_memory.match_screen(fp, _device_rows(team_id, scope))
    if not found:
        return None
    row, dist = found
    seen = int(row.get("seen_count") or 0) + 1
    upd = {"seen_count": seen, "last_seen": _now(), "updated_at": _now()}
    # A row made by the old writers kept a host file path that rotated away, so the AI could never name it (no_sample
    # every hour). The caller's durable thumbnail replaces a picture that is not one; an existing thumbnail is kept.
    if str(sample_image_path or "").startswith("data:image/") \
            and not str(row.get("sample_image_path") or "").startswith("data:image/"):
        upd["sample_image_path"] = sample_image_path
    get_supabase_client().table(TABLE).update(upd).eq("id", row["id"]).eq("team_id", team_id).execute()
    # TASK-162: the caller often ALREADY holds the v6 fingerprint of the frame it just matched --
    # the monitor computes it on every sighting.  Until now it was handed to register_screen_row()
    # (the INSERT path) and thrown away here, so a row registered before the fingerprint existed
    # kept fingerprint = NULL for ever, however often the screen was seen again.  Fill it now, once,
    # through the single writer.
    if fingerprint and not row.get("fingerprint"):
        link_screen_fingerprint(team_id, row["id"], fingerprint)
    return {"id": row["id"], "label": row.get("label"), "dist": dist, "is_new": False,
            "verdict": row.get("verdict"), "seen": seen}


def prune_rare(team_id: str = DEFAULT_TEAM_ID, incident_type: str = "freeze") -> int:
    """Delete the screens that turned out random: seen fewer than ``keep_min_seen()`` times, not seen for
    ``prune_after_days()``, never judged (verdict unknown, no person) and never named (the SQL keeps every row whose
    label is not ``unknown_N``). Returns the number deleted (0 on failure)."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=screen_memory.prune_after_days())).isoformat()
        res = get_supabase_client().rpc("prune_rare_screens", {
            "p_team_id": team_id, "p_incident_type": incident_type,
            "p_min_seen": screen_memory.keep_min_seen(), "p_cutoff": cutoff}).execute()
        _cache.clear()
        return int(res.data or 0)
    except Exception as e:
        print(f"[@db:screen_fingerprints:prune_rare] {e}")
        return 0


def get(screen_id: str) -> Optional[Dict[str, Any]]:
    """The row of ``screen_id``; a row soft-merged into another (TASK-159 G7) answers with the row that was kept."""
    try:
        for _ in range(3):
            res = (get_supabase_client().table(TABLE).select("*").eq("id", screen_id)
                   .eq("team_id", DEFAULT_TEAM_ID).limit(1).execute())
            if not res.data:
                return None
            if not res.data[0].get("merged_into"):
                return res.data[0]
            screen_id = res.data[0]["merged_into"]
        return None
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


def rows_for_scope(team_id: str, scope: str) -> List[Dict[str, Any]]:
    """Every screen row of one device (any incident type), for Localize's known-screen step (TASK-104).
    Cached like ``_rows``; [] on failure."""
    key = (f"{team_id}:{scope}", "*")
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    try:
        rows = _device_rows(team_id, scope)
    except Exception as e:
        print(f"[@db:screen_fingerprints:rows_for_scope] {e}")
        return []
    _cache[key] = (time.time(), rows)
    return rows


def known_screen_lookup(team_id: str, scope: str):
    """``img -> (row, dist) | None``: the frame matched against the device's screen memory."""
    def lookup(img_bgr):
        if not team_id or not scope:
            return None
        fp = screen_memory.fingerprint_frame(img_bgr)
        rows = rows_for_scope(team_id, scope) if fp else []
        return screen_memory.match_screen(fp, rows) if rows else None
    return lookup
