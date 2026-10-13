"""
Infra Status Database Functions

Writes the infra-status data behind the "System Service Status" Grafana
dashboard (setup/db/schema/057_infra_status.sql):
  service_status_current — one live row per component, overwritten every check
  service_status         — change log: a row only when a component's status changes
  vm_metrics             — resources of the infra VMs, one row per VM every 5 minutes
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client


def _client():
    supabase = get_supabase_client()
    if supabase is None:
        raise RuntimeError('Supabase client unavailable')
    return supabase


def get_current_service_status(server_name: str) -> List[Dict[str, Any]]:
    """Live rows this collector wrote last time — the baseline for change detection."""
    result = (_client().table('service_status_current')
              .select('vm, component, status, checked_at, since')
              .eq('server_name', server_name)
              .execute())
    return result.data or []


def upsert_current_service_status(rows: List[Dict[str, Any]]) -> bool:
    if not rows:
        return True
    result = (_client().table('service_status_current')
              .upsert(rows, on_conflict='server_name,vm,component')
              .execute())
    return bool(result.data)


def insert_service_status_changes(rows: List[Dict[str, Any]]) -> bool:
    if not rows:
        return True
    result = _client().table('service_status').insert(rows).execute()
    return bool(result.data)


def store_vm_metrics(rows: List[Dict[str, Any]]) -> bool:
    if not rows:
        return True
    result = _client().table('vm_metrics').insert(rows).execute()
    return bool(result.data)


# vm_metrics is a global fact about the platform — every customer install
# reads the same rows. The table has no team_id column, so no team filter
# here. Windowed to a recent window so the page query stays cheap (~12 rows
# per VM at the 5-minute cadence).
VM_METRICS_WINDOW_HOURS = 1


def get_latest_vm_metrics(
    window_hours: int = VM_METRICS_WINDOW_HOURS,
    vms: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return the latest row per VM from the `vm_metrics` table.

    The table keeps one row per VM every 5 minutes (90-day retention). The
    Supabase PostgREST client does not support DISTINCT ON directly, so we
    window to the last {window_hours} hour(s), order by timestamp DESC, and
    dedupe in Python (the first row per vm wins — it is the most recent).

    Args:
        window_hours: how far back to look. Defaults to 1 (the 5-minute
            cadence gives ~12 rows per VM, ~60 for a typical 5-VM install).
        vms: optional whitelist of vm names to keep; None returns every VM.

    Returns:
        Dict keyed by vm name (database / storage / frontend / proxy / …).
        Each value carries cpu_percent, memory_percent, disk_percent,
        load_average_1m, memory_used_gb, disk_used_gb, etc., plus the
        row's `timestamp`. Empty dict if the table has no recent rows
        or the Supabase client is unavailable.
    """
    try:
        supabase = _client()
    except RuntimeError:
        return {}

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    try:
        result = (
            supabase.table('vm_metrics')
            .select('vm, hostname, cpu_percent, memory_percent, memory_used_gb, '
                    'memory_total_gb, disk_percent, disk_used_gb, disk_total_gb, '
                    'load_average_1m, cpu_count, uptime_seconds, timestamp')
            .gte('timestamp', cutoff)
            .order('timestamp', desc=True)
            .execute()
        )
        rows = result.data or []
    except Exception as exc:
        # A failed read should not break the page — the summary rows render
        # '—' for any metric we cannot fetch.
        print(f'[@infra_status_db:get_latest_vm_metrics] ❌ read failed: {exc}')
        return {}

    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        vm = row.get('vm')
        if not vm or vm in latest:
            continue
        if vms is not None and vm not in vms:
            continue
        latest[vm] = row
    return latest
