"""Unit tests for the match_runs_queue helper and worker throttle logic.

The Redis client is mocked; the worker throttle logic is pure-Python
and tested directly.
"""
import os
import sys
import time
from unittest.mock import MagicMock

# Repo root is three levels up from this test file (worktree-relative).
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

# match_runs_queue uses a lazy import for the Redis client, so the
# `get_queue_processor` import is the natural seam to mock.
import shared.src.lib.utils.redis_queue as _redis_queue_mod  # noqa: E402

# Pre-create a fake processor so the helper picks it up.
class _FakeProc:
    redis_mode = 'local'
    def _redis_command(self, cmd):
        # LPUSH returns the new length; BRPOP returns [ch, value] or None.
        if cmd[0] == 'LPUSH':
            return {'result': 1}
        if cmd[0] == 'BRPOP':
            return {'result': None}
        if cmd[0] == 'LPOP':
            return {'result': None}
        if cmd[0] == 'LLEN':
            return {'result': 0}
        return {'result': None}

_fake = _FakeProc()
_redis_queue_mod.get_queue_processor = lambda: _fake

import shared.src.lib.queue.match_runs_queue as q  # noqa: E402
from backend_server.scripts import match_runs_worker as w  # noqa: E402


def test_build_payload_has_required_fields():
    p = q.build_payload(
        team_id='t1', host_name='h1', userinterface_name='stb-testop',
        source='monitor_localize', result={'kind': 'node'},
        device_id='d1', profile='tv_app', dhash=12345, frame_url='/tmp/x.png',
    )
    assert p['team_id'] == 't1'
    assert p['host_name'] == 'h1'
    assert p['profile'] == 'tv_app'
    assert p['dhash'] == 12345
    assert p['enqueued_at']  # timestamp set


def test_channel_for_severity():
    assert q._channel_for('change') == 'match_runs:queue:change'
    assert q._channel_for('alert') == 'match_runs:queue:alert'
    assert q._channel_for('normal') == 'match_runs:queue'
    assert q._channel_for('unknown') == 'match_runs:queue'  # default


def test_push_routes_to_channel():
    """push() calls _redis_command with the right channel for each severity."""
    captured = []
    class _Cap:
        redis_mode = 'local'
        def _redis_command(self, cmd):
            captured.append(cmd)
            return {'result': 1}
    q._client = lambda: _Cap()
    payload = q.build_payload(team_id='t', host_name='h', userinterface_name='u',
                              source='monitor_localize', result={})
    for severity, expected_channel in [
        ('normal', 'match_runs:queue'),
        ('change', 'match_runs:queue:change'),
        ('alert', 'match_runs:queue:alert'),
    ]:
        captured.clear()
        q.push(payload, severity=severity)
        assert captured[0][1] == expected_channel
        # Second arg is the JSON string of the payload.
        import json as _json
        assert _json.loads(captured[0][2])['team_id'] == 't'


def test_push_swallows_redis_exceptions():
    def boom():
        raise RuntimeError('redis down')
    q._client = boom
    out = q.push(q.build_payload(team_id='t', host_name='h', userinterface_name='u',
                                  source='monitor_localize', result={}))
    assert out is False


def test_pop_batch_returns_parsed_payloads_local():
    """Local Redis path uses the underlying redis client's brpop()."""
    payloads = [
        q.build_payload(team_id='t1', host_name='h1', userinterface_name='u1',
                        source='monitor_localize', result={'kind': 'node'}),
        q.build_payload(team_id='t2', host_name='h2', userinterface_name='u2',
                        source='monitor_localize', result={'kind': 'unknown'}),
    ]
    queued = [p for p in payloads]
    import json as _json

    class _RawClient:
        def __init__(self):
            self._q = list(queued)
        def brpop(self, keys, timeout=0):
            if not self._q:
                return None
            v = self._q.pop(0)
            return ('match_runs:queue', v if isinstance(v, str) else _json.dumps(v))

    class _Q:
        redis_mode = 'local'
        def __init__(self_inner):
            self_inner.redis_client = _RawClient()
    q._client = lambda: _Q()
    got = q.pop_batch('match_runs:queue', max_items=10, timeout_s=0.1)
    assert len(got) == 2
    assert got[0]['host_name'] == 'h1'
    assert got[1]['host_name'] == 'h2'


def test_pop_batch_uses_lpop_for_upstash():
    """Upstash REST path uses LPOP (no BRPOP available)."""
    queued = [{'team_id': 't1', 'host_name': 'h1', 'userinterface_name': 'u1',
               'source': 'monitor_localize', 'result': {}, 'enqueued_at': 'now'}]
    class _Q:
        redis_mode = 'upstash'
        def _redis_command(self_inner, cmd):
            if cmd[0] == 'LPOP':
                if not queued:
                    return {'result': None}
                v = queued.pop(0)
                import json as _json
                return {'result': _json.dumps(v)}
            return {'result': None}
    q._client = lambda: _Q()
    got = q.pop_batch('match_runs:queue', max_items=10, timeout_s=0.1)
    assert len(got) == 1
    assert got[0]['host_name'] == 'h1'


def test_queue_lengths_returns_dict():
    class _Q:
        redis_mode = 'local'
        def _redis_command(self, cmd):
            return {'result': 7}
    q._client = lambda: _Q()
    out = q.queue_lengths()
    assert out['match_runs:queue'] == 7
    assert out['match_runs:queue:change'] == 7
    assert out['match_runs:queue:alert'] == 7


# ---- worker throttle logic ----

def test_should_emit_first_emit():
    assert w._should_emit('h', 'd', 'tv_app', 'node', time.time(), 10.0) is True


def test_should_emit_same_verdict_within_throttle_is_false():
    now = 100.0
    w._should_emit('h', 'd', 'tv_app', 'node', now, 10.0)
    w._mark_emitted('h', 'd', 'tv_app', 'node', now)
    assert w._should_emit('h', 'd', 'tv_app', 'node', now + 5.0, 10.0) is False
    assert w._should_emit('h', 'd', 'tv_app', 'node', now + 11.0, 10.0) is True


def test_should_emit_verdict_changed_always_emits():
    now = 100.0
    w._should_emit('h', 'd', 'tv_app', 'node', now, 10.0)
    w._mark_emitted('h', 'd', 'tv_app', 'node', now)
    # Verdict changed → emit immediately.
    assert w._should_emit('h', 'd', 'tv_app', 'unknown', now + 0.1, 10.0) is True


def test_should_emit_alert_kinds_always_emit():
    """unknown / low_confidence / no_signal bypass the steady-state throttle."""
    now = 100.0
    w._should_emit('h', 'd', 'tv_app', 'node', now, 10.0)
    w._mark_emitted('h', 'd', 'tv_app', 'node', now)
    for alert_kind in ('unknown', 'low_confidence', 'no_signal'):
        assert w._should_emit('h', 'd', 'tv_app', alert_kind, now + 0.5, 10.0) is True, alert_kind


def test_prune_throttle_drops_stale_entries():
    now = 1_000_000.0
    # _should_emit does not store on its own; the caller calls _mark_emitted
    # after a successful write.  Replicate the real call sequence.
    w._should_emit('h1', 'd1', 'tv_app', 'node', now - 7200, 10.0)
    w._mark_emitted('h1', 'd1', 'tv_app', 'node', now - 7200)
    w._should_emit('h2', 'd2', 'tv_app', 'node', now - 10, 10.0)
    w._mark_emitted('h2', 'd2', 'tv_app', 'node', now - 10)
    w._prune_throttle(now, max_age_s=3600.0)
    # h1/d1 is 2h old → dropped; h2/d2 is 10s old → kept.
    assert ('h1', 'd1', 'tv_app') not in w._THROTTLE
    assert ('h2', 'd2', 'tv_app') in w._THROTTLE
    # Reset for the next test.
    w._THROTTLE.clear()


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
