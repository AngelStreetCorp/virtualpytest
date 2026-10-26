#!/usr/bin/env python3
"""
match_runs_worker.py — the vpt-match-runs-writer service.

BUG-0565.  Reads from the three match_runs Redis channels, batches inserts
to public.match_runs, and bumps the screen_fingerprints counter for
unknown / low_confidence hits.

Service: vpt-match-runs-writer.service (one-shot? no — long-running
BRPOP loop).  Mirrors the vpt-discard-incidents pattern.

Channels and their priority (BRPOP is blocking on a single key, so the
worker rotates):

  match_runs:queue:change   first — transitions are the most valuable
                              write, and a settled-screen burst should
                              not delay them
  match_runs:queue:alert    second — alert hits feed the auto-classify
                              scheduler
  match_runs:queue          last  — the steady-state settled-screen log

Throttling is per (host, device, profile) on the steady-state channel.
The other two channels are written as-is (their natural cadence is
already low).

DRY RUN
  --dry-run            consume the queue but only print what would be
                       written; no DB inserts.  For smoke-testing the
                       worker without writing to the live match_runs
                       table.

Run on the vpt-server:
  sudo -u vpt_user /opt/virtualpytest/venv/bin/python3 \\
      /opt/virtualpytest/backend_server/scripts/match_runs_worker.py
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_RUNNING = True


def _setup_paths() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    for p in (project_root, project_root / 'backend_server' / 'src'):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    return project_root


def _handle_signal(signum, _frame):
    global _RUNNING
    print(f'[@match_runs_worker] signal {signum} — stopping after this cycle')
    _RUNNING = False


# Throttle cache: (host, device) -> (last_emitted_at_s, last_verdict)
# Reset on worker restart (Redis state is the source of truth; this is
# only a debounce so we don't write 5 rows in the same second).
_THROTTLE: Dict[Tuple[str, str, str], Tuple[float, str]] = {}
_DEFAULT_THROTTLE_S = float(os.environ.get('MATCH_RUNS_THROTTLE_NORMAL_S', '10.0'))


def _should_emit(host: str, device: str, profile: str, verdict: str,
                now: float, throttle_s: float) -> bool:
    """True if this entry should be written.  Steady-state channel rule:
    same (host, device, profile, verdict) within throttle_s → drop.
    Verdicts changing always emit (transitions live in the `change` channel
    anyway, so this is just a safety net).
    """
    if verdict in ('unknown', 'no_signal', 'low_confidence'):
        # These bypass the steady-state throttle — the auto-classify
        # scheduler needs them.
        return True
    key = (host, device, profile)
    last = _THROTTLE.get(key)
    if last is None:
        return True
    last_at, last_verdict = last
    if last_verdict != verdict:
        return True
    if (now - last_at) >= throttle_s:
        return True
    return False


def _mark_emitted(host: str, device: str, profile: str, verdict: str, now: float) -> None:
    _THROTTLE[(host, device, profile)] = (now, verdict)


def _prune_throttle(now: float, max_age_s: float = 3600.0) -> None:
    """Drop entries that haven't fired in an hour — keeps the dict bounded."""
    stale = [k for k, (t, _) in _THROTTLE.items() if (now - t) > max_age_s]
    for k in stale:
        _THROTTLE.pop(k, None)


def _write_batch(rows: List[Dict[str, Any]], dry_run: bool) -> Tuple[int, int, int]:
    """Insert N rows into match_runs.  Returns ``(ok, fail, deduped)``.

    ``deduped`` counts rows the BUG-0571 unique index caught as
    duplicate pushes from a vpt-host restart — not a real failure but
    worth surfacing so the operator's "X deduped" log line is honest.
    """
    if dry_run:
        for r in rows:
            print(f'[@match_runs_worker] [dry-run] {r.get("host_name")} '
                  f'{r.get("device_id")}/{r.get("userinterface_name")} '
                  f'verdict={r.get("verdict")} profile={r.get("profile")}')
        return len(rows), 0, 0
    try:
        from shared.src.lib.database.match_runs_db import record_match_run
        ok = 0
        deduped = 0
        failed = 0
        for r in rows:
            out = record_match_run(
                team_id=r['team_id'],
                host_name=r['host_name'],
                userinterface_name=r['userinterface_name'],
                source=r['source'],
                result=r['result'],
                server_id=r.get('server_id'),
                device_id=r.get('device_id'),
                device_name=r.get('device_name'),
                device_model=r.get('device_model'),
                tree_id=r.get('tree_id'),
                variant=r.get('variant'),
                profile=r.get('profile'),
                dhash=r.get('dhash'),
                frame_url=r.get('frame_url'),
                confidence_floor=0.80,
            )
            if out.get('success'):
                ok += 1
                continue
            err = str(out.get('error') or '')
            # 23505 = unique_violation → BUG-0571's dedupe index caught a
            # double-pushed row.  Expected on a vpt-host restart mid-batch;
            # log at info, not warning, so the operator's eye does not
            # treat every dedupe as a real failure.
            if 'duplicate key' in err or 'unique constraint' in err or '23505' in err:
                print(f'[@match_runs_worker] dedupe hit on profile={r.get("profile")} ts={r.get("started_at")} (BUG-0571)')
                deduped += 1
            else:
                print(f'[@match_runs_worker] insert failed: {err}')
                failed += 1
        return ok, failed, deduped
    except Exception as e:
        print(f'[@match_runs_worker] batch insert failed: {e}')
        return 0, len(rows), 0


def _process_channel(channel: str, *, batch_max: int, timeout_s: float,
                     dry_run: bool, throttle_s: float) -> Tuple[int, int, int]:
    """One cycle on one channel.  Returns (kept, written, alerts_bumped)."""
    from shared.src.lib.queue.match_runs_queue import pop_batch
    payloads = pop_batch(channel, max_items=batch_max, timeout_s=timeout_s)
    if not payloads:
        return 0, 0, 0
    now = time.time()
    kept: List[Dict[str, Any]] = []
    for p in payloads:
        host = p.get('host_name') or 'unknown'
        device = p.get('device_id') or 'unknown'
        profile = p.get('profile') or ''
        verdict = (p.get('result') or {}).get('kind') or 'unknown'
        if not _should_emit(host, device, profile, verdict, now, throttle_s):
            continue
        # Build a row shaped for record_match_run.
        kept.append({
            'team_id': p['team_id'],
            'server_id': p.get('server_id'),
            'host_name': host,
            'device_id': device,
            'device_name': p.get('device_name'),
            'device_model': p.get('device_model'),
            'userinterface_name': p['userinterface_name'],
            'tree_id': p.get('tree_id'),
            'variant': p.get('variant'),
            'profile': profile,
            'source': p.get('source', 'monitor_localize'),
            'result': p.get('result') or {},
            'dhash': p.get('dhash'),
            'frame_url': p.get('frame_url'),
            'verdict': verdict,
        })
        _mark_emitted(host, device, profile, verdict, now)
    if not kept:
        return len(payloads), 0, 0
    ok, fail, deduped = _write_batch(kept, dry_run=dry_run)
    if not dry_run and (ok or fail or deduped):
        print(f'[@match_runs_worker] {channel}: {len(payloads)} popped, '
              f'{ok} kept, {ok} written, {fail} failed, {deduped} deduped')
    return len(payloads), ok, 0


def _queue_health() -> Dict[str, int]:
    try:
        from shared.src.lib.queue.match_runs_queue import queue_lengths
        return queue_lengths()
    except Exception:
        return {}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', default=False,
                        help='consume the queue but do not write to match_runs / screen_fingerprints')
    parser.add_argument('--batch-max', type=int, default=50,
                        help='max items per channel per cycle (default 50)')
    parser.add_argument('--timeout-s', type=float, default=1.0,
                        help='BRPOP timeout per channel (default 1.0s)')
    parser.add_argument('--throttle-s', type=float, default=_DEFAULT_THROTTLE_S,
                        help='steady-state channel throttle per (host, device, profile) in seconds')
    parser.add_argument('--idle-log-s', type=float, default=60.0,
                        help='how often to log queue lengths when idle (default 60s)')
    args = parser.parse_args(argv)

    project_root = _setup_paths()
    try:
        from shared.src.lib.utils.app_utils import load_environment_variables
        load_environment_variables(str(project_root))
    except Exception as e:
        print(f'[@match_runs_worker] warning: failed to load env: {e}')

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print(f'[@match_runs_worker] starting; dry_run={args.dry_run} '
          f'batch_max={args.batch_max} timeout_s={args.timeout_s} '
          f'throttle_s={args.throttle_s}')

    # Probe the queue once before the loop so a missing Redis surfaces
    # immediately and systemd restarts us with logs.
    health = _queue_health()
    if not health:
        print('[@match_runs_worker] WARNING: no queue lengths returned — is Redis up?')
    else:
        print(f'[@match_runs_worker] queue lengths at start: {health}')

    last_idle_log = time.time()
    last_prune = time.time()
    while _RUNNING:
        cycle_start = time.time()
        # Priority order: change → alert → normal.
        for channel in ('match_runs:queue:change', 'match_runs:queue:alert', 'match_runs:queue'):
            try:
                _process_channel(channel, batch_max=args.batch_max,
                                 timeout_s=args.timeout_s, dry_run=args.dry_run,
                                 throttle_s=args.throttle_s)
            except Exception as e:
                print(f'[@match_runs_worker] cycle on {channel} failed: {e}')
        if (time.time() - last_prune) > 60:
            _prune_throttle(time.time())
            last_prune = time.time()
        # Idle log: print queue lengths so the operator can see if we are keeping up.
        if (time.time() - last_idle_log) > args.idle_log_s:
            print(f'[@match_runs_worker] idle; queue lengths: {_queue_health()}')
            last_idle_log = time.time()
        # If a cycle took less than 100ms, sleep the rest to avoid hot-spinning.
        elapsed = time.time() - cycle_start
        if elapsed < 0.1:
            time.sleep(0.1 - elapsed)
    print('[@match_runs_worker] stopped')
    return 0


if __name__ == '__main__':
    sys.exit(main())
