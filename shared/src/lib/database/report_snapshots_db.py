"""
Report Snapshots Database Operations (TASK-49)

Frozen, shareable copies of one test report (Grafana-style). Every read except
get_snapshot_by_key_hash / get_snapshot_by_delete_key_hash filters by team_id:
the public viewer holds the secret URL key and has no team.

Hashes (key_hash, delete_key_hash, password_hash) are written here but never
read back. list_snapshots strips them, and get_snapshot returns the row to a
server-side caller that has already authenticated the key, so the call site
can use them as it needs.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.database.in_filter import chunked_in
from shared.src.lib.database.transient_retry import brief, call_with_retry


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


# Columns list_snapshots returns. Never include the secret hashes: callers must
# not see them, the share dialog only needs to show expiry / has_password /
# size / view_count, and the delete action is the row's id.
_LIST_SELECT = (
    "id, team_id, script_result_id, server_name, created_by, created_at, "
    "expires_at, revoked_at, purged_at, include_video, size_bytes, "
    "view_count, last_viewed_at, password_hash"
)


def create_snapshot(
    snapshot_id: str,
    team_id: str,
    script_result_id: str,
    server_name: str,
    created_by: Optional[str],
    key_hash: str,
    delete_key_hash: str,
    password_hash: Optional[str],
    storage_prefix: str,
    include_video: bool,
    size_bytes: int,
    expires_at: datetime,
) -> Optional[dict]:
    """Insert a new snapshot row. `expires_at` is stored as its isoformat()."""
    try:
        row = {
            "id": snapshot_id,
            "team_id": team_id,
            "script_result_id": script_result_id,
            "server_name": server_name,
            "created_by": created_by,
            "key_hash": key_hash,
            "delete_key_hash": delete_key_hash,
            "password_hash": password_hash,
            "storage_prefix": storage_prefix,
            "include_video": include_video,
            "size_bytes": size_bytes,
            "expires_at": expires_at.isoformat(),
        }
        result = get_supabase().table("report_snapshots").insert(row).execute()
        if result.data:
            print(f"[@db:report_snapshots:create_snapshot] Created {snapshot_id}")
            return result.data[0]
        print(f"[@db:report_snapshots:create_snapshot] Insert returned no rows")
        return None
    except Exception as e:
        print(f"[@db:report_snapshots:create_snapshot] Error: {str(e)}")
        return None


def get_snapshot(team_id: str, snapshot_id: str) -> Optional[dict]:
    """Fetch a single snapshot, team-scoped."""
    try:
        result = (
            get_supabase()
            .table("report_snapshots")
            .select("*")
            .eq("team_id", team_id)
            .eq("id", snapshot_id)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"[@db:report_snapshots:get_snapshot] Error: {str(e)}")
        return None


def list_snapshots(
    team_id: str,
    script_result_id: str,
    active_only: bool = True,
) -> List[dict]:
    """List snapshots of one report for the share dialog.

    active_only=True (default) hides revoked rows and rows past their expiry.
    The result NEVER carries key_hash or delete_key_hash: we select the safe
    columns explicitly and compute has_password in Python from the
    password_hash column, then drop the hash.
    """
    try:
        query = (
            get_supabase()
            .table("report_snapshots")
            .select(_LIST_SELECT)
            .eq("team_id", team_id)
            .eq("script_result_id", script_result_id)
            .order("created_at", desc=True)
        )
        if active_only:
            now_iso = datetime.now(timezone.utc).isoformat()
            query = query.is_("revoked_at", "null").gt("expires_at", now_iso)

        result = query.execute()
        rows = result.data or []
        cleaned: List[dict] = []
        for row in rows:
            row["has_password"] = bool(row.pop("password_hash", None))
            cleaned.append(row)
        return cleaned
    except Exception as e:
        print(f"[@db:report_snapshots:list_snapshots] Error: {str(e)}")
        return []


LIST_STATUSES = ("active", "expired", "revoked", "all")


def list_team_snapshots(team_id: str, status: str = "active", limit: int = 200) -> List[dict]:
    """List every snapshot of a team for the "Shared links" view (newest first).

    status: active (not revoked, not expired), expired (not revoked, past expiry),
    revoked, or all. Always filtered by team_id. Same safe columns as list_snapshots:
    no key_hash / delete_key_hash, password_hash only becomes has_password.
    """
    try:
        query = (
            get_supabase()
            .table("report_snapshots")
            .select(_LIST_SELECT)
            .eq("team_id", team_id)
            .order("created_at", desc=True)
            .limit(limit)
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        if status == "active":
            query = query.is_("revoked_at", "null").gt("expires_at", now_iso)
        elif status == "expired":
            query = query.is_("revoked_at", "null").lte("expires_at", now_iso)
        elif status == "revoked":
            query = query.not_.is_("revoked_at", "null")
        result = query.execute()
        cleaned: List[dict] = []
        for row in result.data or []:
            row["has_password"] = bool(row.pop("password_hash", None))
            cleaned.append(row)
        return cleaned
    except Exception as e:
        print(f"[@db:report_snapshots:list_team_snapshots] Error: {str(e)}")
        return []


def get_script_summaries(team_id: str, script_result_ids: List[str]) -> Dict[str, dict]:
    """One batched script_results lookup (id IN (...) AND team_id) for the Shared links view.

    Returns {id: {script_name, device_name, host_name, started_at, report_url}}."""
    ids = sorted({str(i) for i in script_result_ids if i})
    if not ids:
        return {}
    try:
        supabase = get_supabase()
        rows = chunked_in(
            lambda chunk: supabase.table("script_results")
            .select("id, script_name, device_name, host_name, started_at, html_report_r2_url")
            .eq("team_id", team_id)
            .in_("id", chunk),
            ids)
        return {
            str(r["id"]): {
                "script_name": r.get("script_name"),
                "device_name": r.get("device_name"),
                "host_name": r.get("host_name"),
                "started_at": r.get("started_at"),
                "report_url": r.get("html_report_r2_url"),
            }
            for r in rows
        }
    except Exception as e:
        print(f"[@db:report_snapshots:get_script_summaries] Error: {str(e)}")
        return {}


def get_profile_names(user_ids: List[str]) -> Dict[str, str]:
    """One batched profiles lookup, {id: full_name or email}. The ids come from snapshot rows
    already filtered by team_id, so no extra team filter is applied here."""
    ids = sorted({str(i) for i in user_ids if i})
    if not ids:
        return {}
    try:
        result = get_supabase().table("profiles").select("id, full_name, email").in_("id", ids).execute()
        return {
            str(r["id"]): (r.get("full_name") or "").strip() or r.get("email") or ""
            for r in (result.data or [])
        }
    except Exception as e:
        print(f"[@db:report_snapshots:get_profile_names] Error: {str(e)}")
        return {}


def get_snapshot_by_key_hash(key_hash: str) -> Optional[dict]:
    """Lookup by the URL share-key hash.

    The ONLY lookups with no team_id filter: the caller is the public viewer,
    holds the secret key in the URL, and has no team. Auth is the key itself.
    """
    try:
        result = (
            get_supabase()
            .table("report_snapshots")
            .select("*")
            .eq("key_hash", key_hash)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"[@db:report_snapshots:get_snapshot_by_key_hash] Error: {str(e)}")
        return None


def get_snapshot_by_delete_key_hash(delete_key_hash: str) -> Optional[dict]:
    """Lookup by the delete-key hash (the Grafana-style revoke link).

    The ONLY lookups with no team_id filter: the caller is the holder of the
    delete secret, no account needed. Auth is the key itself.
    """
    try:
        result = (
            get_supabase()
            .table("report_snapshots")
            .select("*")
            .eq("delete_key_hash", delete_key_hash)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"[@db:report_snapshots:get_snapshot_by_delete_key_hash] Error: {str(e)}")
        return None


def revoke_snapshot(team_id: str, snapshot_id: str) -> bool:
    """Set revoked_at on a snapshot. Team-scoped: a wrong team never revokes."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        result = (
            get_supabase()
            .table("report_snapshots")
            .update({"revoked_at": now})
            .eq("team_id", team_id)
            .eq("id", snapshot_id)
            .is_("revoked_at", "null")
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        print(f"[@db:report_snapshots:revoke_snapshot] Error: {str(e)}")
        return False


def revoke_snapshot_by_id(snapshot_id: str) -> bool:
    """Set revoked_at on a snapshot with no team filter (delete-key path).

    The ONLY revoke without a team_id: the caller is the holder of the delete
    secret shown once at creation. Auth is the key itself (already checked by
    the route via get_snapshot_by_delete_key_hash).
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        result = (
            get_supabase()
            .table("report_snapshots")
            .update({"revoked_at": now})
            .eq("id", snapshot_id)
            .is_("revoked_at", "null")
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        print(f"[@db:report_snapshots:revoke_snapshot_by_id] Error: {str(e)}")
        return False


def record_view(snapshot_id: str) -> None:
    """Bump view_count and last_viewed_at. Best effort, never raises.

    Read-then-write is fine here: an occasional double-count from a parallel
    view is acceptable for a vanity counter, and there is no RPC to do it in
    one shot. Any failure is logged and swallowed so a view never 500s on a
    counter problem.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        row = (
            get_supabase()
            .table("report_snapshots")
            .select("view_count")
            .eq("id", snapshot_id)
            .execute()
        )
        current = 0
        if row.data:
            current = int((row.data[0] or {}).get("view_count") or 0)
        get_supabase().table("report_snapshots").update(
            {"view_count": current + 1, "last_viewed_at": now}
        ).eq("id", snapshot_id).execute()
    except Exception as e:
        print(f"[@db:report_snapshots:record_view] Error: {e}")


def list_purgeable(server_name: str, limit: int = 100) -> List[dict]:
    """Rows of this server that should be swept: revoked or expired, not yet purged.

    A read, so it is safe to retry: the sweeper gets a dropped TLS session or a proxy 500
    while the Supabase path is re-establishing, and the next 15-minute run would otherwise
    leave the backlog sitting there for a quarter of an hour.
    """
    def _query() -> List[dict]:
        now_iso = datetime.now(timezone.utc).isoformat()
        result = (
            get_supabase()
            .table("report_snapshots")
            .select("*")
            .eq("server_name", server_name)
            .is_("purged_at", "null")
            .or_(f"revoked_at.not.is.null,expires_at.lt.{now_iso}")
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []

    try:
        return call_with_retry(_query, label="@db:report_snapshots:list_purgeable")
    except Exception as e:
        print(f"[@db:report_snapshots:list_purgeable] Error: {brief(e)}")
        return []


def mark_purged(snapshot_id: str) -> bool:
    """Set purged_at after the sweeper deletes the storage objects."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        result = (
            get_supabase()
            .table("report_snapshots")
            .update({"purged_at": now})
            .eq("id", snapshot_id)
            .is_("purged_at", "null")
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        print(f"[@db:report_snapshots:mark_purged] Error: {str(e)}")
        return False


def team_live_bytes(team_id: str) -> int:
    """Sum of size_bytes for every snapshot of a team whose objects still exist.

    Counts each row with purged_at IS NULL, revoked or expired included: the bytes stay in
    storage until the sweeper purges them, so a revoke must not free quota before then.
    Used for the per-team 5 GB quota.
    """
    try:
        result = (
            get_supabase()
            .table("report_snapshots")
            .select("size_bytes")
            .eq("team_id", team_id)
            .is_("purged_at", "null")
            .execute()
        )
        total = 0
        for row in result.data or []:
            try:
                total += int(row.get("size_bytes") or 0)
            except (TypeError, ValueError):
                continue
        return total
    except Exception as e:
        print(f"[@db:report_snapshots:team_live_bytes] Error: {str(e)}")
        return 0