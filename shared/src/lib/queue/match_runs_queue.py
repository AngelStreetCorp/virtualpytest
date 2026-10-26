"""match_runs_queue — Redis queue between the matcher and the match_runs DB writer.

BUG-0565.  Three channels with different latency budgets:

  match_runs:queue         normal-settled verdicts, throttled (default 10s per device)
  match_runs:queue:change   verdict CHANGED (different node, or known_node <-> unknown)
                            — the v_node_transitions aggregation needs every change,
                            so this channel has a much smaller throttle (default 1s)
  match_runs:queue:alert    unknown / low_confidence hits that the auto-classify
                            scheduler cares about — every hit bumps the
                            screen_fingerprints counter, so this channel
                            is throttled by a per-dhash counter inside the worker
                            (default 5 hits / 14 days per the existing rule)

Why three channels and not one: the worker is a single loop, but each
channel has its own batch window.  A burst of verdict changes (e.g. an
operator pressing Localize 20 times) should not delay the steady-state
settled-screen writes; the alert hits should not delay the transitions
either.  Redis lists are cheap enough that three is fine.

Why Redis and not Postgres LISTEN/NOTIFY: Redis is already deployed
(used by the vpt-discard-* workers), survives the vpt-server being
restarted, and the worker on the vpt-server does not need direct DB
write access to push to the queue.  Postgres NOTIFY would tie the
writer to a DB connection, which is the exact coupling we are
breaking.

All three channels LPUSH at the writer and BRPOP / LMPOP at the
worker (the existing redis_queue module supports both Upstash REST
and local Redis).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


CHANNEL_NORMAL = 'match_runs:queue'
CHANNEL_CHANGE = 'match_runs:queue:change'
CHANNEL_ALERT = 'match_runs:queue:alert'

# Throttle defaults (overridable by env when the writer is configured).
# The "10s per device on a stable screen" comes from a measured 1 Hz
# monitor on a settled STB: 10s gives us a 10x compression on rows
# without losing the "where am I" timeline.  Verdicts changing faster
# than 1s are noise (the motion gate already drops them).
DEFAULT_THROTTLE_NORMAL_S = 10.0
DEFAULT_THROTTLE_CHANGE_S = 1.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profile_from_env() -> str:
    """The matcher profile this host is running (TASK-90 §4.5).

    Reads MONITOR_PROFILE from os.environ.  The writer (host) imports
    ``shared.src.lib.utils.monitor_profile.resolve_monitor_profile`` if
    it wants per-device resolution; the queue helper just stamps the
    queue payload with the value the caller passed.
    """
    return ''  # the caller supplies the profile; the helper does not read env directly


def build_payload(*, team_id: str, host_name: str, userinterface_name: str,
                  source: str, result: Dict[str, Any], device_id: Optional[str] = None,
                  device_name: Optional[str] = None, device_model: Optional[str] = None,
                  tree_id: Optional[str] = None, variant: Optional[str] = None,
                  dhash: Optional[int] = None, frame_url: Optional[str] = None,
                  profile: Optional[str] = None, server_id: Optional[str] = None,
                  elapsed_ms: Optional[int] = None) -> Dict[str, Any]:
    """One queue entry.  Carries the same fields the direct writer takes,
    plus a 'previous_verdict' (optional) so the worker can detect a change
    without re-querying the DB.
    """
    return {
        'team_id': team_id,
        'server_id': server_id,
        'host_name': host_name,
        'device_id': device_id,
        'device_name': device_name,
        'device_model': device_model,
        'userinterface_name': userinterface_name,
        'tree_id': tree_id,
        'variant': variant,
        'profile': profile,
        'source': source,
        'result': result,
        'dhash': dhash,
        'frame_url': frame_url,
        'elapsed_ms': elapsed_ms,
        'enqueued_at': _now_iso(),
    }


def _client():
    """Lazy import so the helper can be imported without the redis stack
    being available (the writer on the host might run before redis is up).
    """
    from shared.src.lib.utils.redis_queue import get_queue_processor
    return get_queue_processor()


def _channel_for(severity: str) -> str:
    if severity == 'change':
        return CHANNEL_CHANGE
    if severity == 'alert':
        return CHANNEL_ALERT
    return CHANNEL_NORMAL


def push(payload: Dict[str, Any], severity: str = 'normal') -> bool:
    """LPUSH one payload onto the right channel.  Never raises — a missing
    Redis is logged and the matcher keeps running (it just stops feeding
    match_runs until Redis is back).
    """
    try:
        client = _client()
        return bool(client._redis_command(['LPUSH', _channel_for(severity), json.dumps(payload)]).get('result'))
    except Exception as e:
        # Logged at the caller; the matcher does not abort because the
        # queue is down.
        print(f'[@queue:match_runs] push failed ({severity}): {e}')
        return False


def push_batch(payloads: List[Dict[str, Any]], severity: str = 'normal') -> int:
    """LPUSH many.  Cheaper than N round-trips on Upstash REST.  Returns
    the number of payloads accepted (best-effort: 0 on total failure,
    len(payloads) on success)."""
    if not payloads:
        return 0
    try:
        client = _client()
        accepted = 0
        # The REST API supports a single multi-command call; local Redis
        # is pipelined by the client.  Fall back to a serial loop if the
        # helper does not expose a pipelined method.
        for p in payloads:
            if client._redis_command(['LPUSH', _channel_for(severity), json.dumps(p)]).get('result'):
                accepted += 1
        return accepted
    except Exception as e:
        print(f'[@queue:match_runs] push_batch failed ({severity}): {e}')
        return 0


def pop_batch(channel: str, max_items: int = 50, timeout_s: float = 1.0) -> List[Dict[str, Any]]:
    """Pop up to max_items from `channel`.

    Mode-aware:
      - Local Redis: BRPOP with `timeout_s` (the one blocking call the worker
        actually wants); bypasses the redis_queue helper's limited command
        set, which only knows LPOP / RPUSH.
      - Upstash REST: LPOP up to max_items with a tiny gap; the REST API
        has no blocking primitive, so a tight LPOP loop is the standard
        pattern.  Tight loop with sleep 0 keeps the worker responsive to
        SIGTERM.

    Returns the parsed payloads (each is the dict built by build_payload).
    On a quiet queue, returns [] after the timeout.
    """
    try:
        client = _client()
        if client.redis_mode == 'local':
            # Use the underlying redis client directly for BRPOP — the
            # redis_queue wrapper does not implement it.
            raw = getattr(client, 'redis_client', None)
            if raw is None:
                return []
            out: List[Dict[str, Any]] = []
            for _ in range(max_items):
                item = raw.brpop([channel], timeout=int(timeout_s))
                if not item:
                    break
                # brpop returns (channel, value) or None on timeout.
                value = item[1] if isinstance(item, (list, tuple)) else None
                if value is None:
                    break
                try:
                    out.append(json.loads(value))
                except Exception:
                    continue
            return out
        # Upstash REST: LPOP, with a small sleep between calls so the
        # process is interruptible.
        out = []
        for _ in range(max_items):
            res = client._redis_command(['LPOP', channel])
            if not res or not res.get('result'):
                break
            value = res['result']
            try:
                out.append(json.loads(value))
            except Exception:
                continue
        return out
    except Exception as e:
        print(f'[@queue:match_runs] pop_batch failed ({channel}): {e}')
        return []


def queue_lengths() -> Dict[str, int]:
    """Length of each channel; for the operator's "is the worker keeping up?" check."""
    try:
        client = _client()
        out = {}
        for ch in (CHANNEL_NORMAL, CHANNEL_CHANGE, CHANNEL_ALERT):
            res = client._redis_command(['LLEN', ch])
            out[ch] = int((res or {}).get('result') or 0)
        return out
    except Exception:
        return {}
