"""Which deployment_executions rows this host can still see running (E50).

A `deployment_executions` row in 'running' is a CLAIM, not a fact. The run that owns it
died - or the host restarted - and the row stayed 'running'. Two consequences, both paid
for on the host:

  * the busy snapshot (`/host/deployment/jobs`) reported the dead row, and the deploy gate
    deferred every restart of this host for as long as the row existed,
  * the server's stale-row reaper skipped the dead row, because it asked "is this DEVICE
    busy?" and one unrelated live run on the same device answered yes. A runaway run
    therefore shielded every dead row of the host.

The host does know which runs are alive: the script executor's process registry and the
campaign registry live in this process. This module turns them into the two answers the
host needs:

  * `execution_is_alive(row_id)` - "is THIS row's run still there?" (per row),
  * `liveness_snapshot()` - which rows are alive, and whether the host could read the
    registries at all. When it could not, the answer is "unknown" and the caller keeps
    every row: closing a live row is worse than keeping a dead one.
"""

from typing import Any, Dict, List, Set, Tuple

# How long a 'running' row is trusted without a live process behind it. The row is created
# before the script starts, so a run that is still registering its process must not be
# called dead (E50).
RUNNING_EXECUTION_LIVENESS_GRACE_SECONDS = 300


def liveness_snapshot() -> Dict[str, Any]:
    """The execution ids this host can prove are still running.

    Returns {'alive': {execution ids}, 'complete': bool}. `complete` is False when a
    registry could not be read: the caller must then treat every row as alive.
    """
    alive: Set[str] = set()
    complete = True

    # The script executor's process registry: one entry per run, each tied to the
    # deployment_executions row that claims it.
    try:
        from shared.src.lib.executors.script_executor import (
            _running_processes_by_device,
            _running_processes_lock,
        )
        with _running_processes_lock:
            for entries in list(_running_processes_by_device.values()):
                for info in entries or []:
                    process = info.get('process')
                    if process is not None and process.poll() is not None:
                        continue        # the process is gone: the row it claimed is stale
                    execution_id = info.get('execution_id')
                    if execution_id:
                        alive.add(str(execution_id))
    except Exception as exc:
        complete = False
        print(f"⚠️ [execution_liveness] script registry unreadable: {exc}")

    # Campaigns: between two steps no script process exists, so only the campaign
    # registry shows that the run is still going.
    try:
        from shared.src.lib.executors.campaign_executor import get_in_flight_campaigns
        for info in get_in_flight_campaigns() or []:
            execution_id = info.get('deployment_execution_id')
            if execution_id:
                alive.add(str(execution_id))
    except Exception as exc:
        complete = False
        print(f"⚠️ [execution_liveness] campaign registry unreadable: {exc}")

    return {'alive': alive, 'complete': complete}


def execution_is_alive(execution_id: str) -> bool:
    """Is THIS execution still running?

    True when the host can see it alive, and also when the host cannot tell (the safe
    side: a row that is wrongly kept alive only waits for the next sweep).
    """
    if not execution_id:
        return True
    snapshot = liveness_snapshot()
    if not snapshot['complete']:
        return True
    return str(execution_id) in snapshot['alive']


def _row_age_seconds(row: Dict[str, Any]) -> Any:
    """How long ago the row started, None when it does not say."""
    from datetime import datetime, timezone

    started_at = row.get('started_at')
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(str(started_at).replace('Z', '+00:00'))
    except Exception:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started).total_seconds()


def split_running_by_liveness(rows: List[Dict[str, Any]],
                               grace_seconds: int = RUNNING_EXECUTION_LIVENESS_GRACE_SECONDS
                               ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split the 'running' rows into the ones this host can still see running and the
    dead claims (E50).

    The row is a claim, not a fact: a run that died (or a host restart) leaves it in
    'running' forever. Reporting those rows as running made the deploy gate defer every
    restart of this host, and made the server's reaper skip the row because the DEVICE was
    busy with an unrelated run.

    A row the host cannot judge yet - the run started but did not register its process -
    stays in the live list until the grace period is over.
    """
    snapshot = liveness_snapshot()
    if not snapshot['complete']:
        # The host could not read its own registries: report every row (the safe side).
        return list(rows), []

    alive = snapshot['alive']
    live: List[Dict[str, Any]] = []
    stale: List[Dict[str, Any]] = []
    for row in rows:
        execution_id = str(row.get('id') or '')
        if execution_id in alive:
            live.append(row)
            continue
        age_s = _row_age_seconds(row)
        if age_s is not None and age_s < grace_seconds:
            live.append(row)      # the run may have started but not registered yet
        else:
            stale.append(row)
    return live, stale
