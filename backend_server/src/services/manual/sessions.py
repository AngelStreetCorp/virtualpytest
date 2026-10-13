"""Manual run sessions (TASK-42 §4.2 / §5 ManualRun).

A person performs a test case by hand and records each step's outcome.

Decisions taken from the code:

* Host/device: a manual result is stored in ``script_results`` like every
  other execution, and every scoped reader (TestReports, quality, summary)
  filters by this server's registered hosts. A manual session therefore names
  the registered ``host_name`` and host-local ``device_name`` (device id) it
  was performed on; both must be inside the caller's scope. That keeps manual
  results visible where the device's results are visible, and nowhere else.
* Identity: ``script_name`` = the test case name, ``script_type = 'manual'``,
  so a manual attempt never merges with automated attempts of the same test
  case in quality identities, and rerun paths can exclude it.
* The test case definition (current version) is copied into
  ``testcase_snapshot`` at creation; later edits do not change the session.
* Steps come from the request or, when omitted, from the test case graph
  (one step per executable node, in graph order).
* Outcome: success only when every required step passed and no step failed;
  ``skipped`` / ``blocked`` on a required step make the run fail; a missing
  required outcome blocks finalize until one is recorded.
  Evidence is optional and reported as missing per step.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend_server.src.services.analytics.scope import RunScope, ScopeError

OUTCOMES = ('passed', 'failed', 'skipped', 'blocked')
ENVIRONMENTS = ('dev', 'test', 'prod')
MAX_STEPS = 200
LABEL_MAX = 500
NOTE_MAX = 2000
URL_MAX = 2000
_GRAPH_SKIP_TYPES = {'start', 'success', 'failure', 'end'}


def validate_target(scope: RunScope, host_name: Any, device_name: Any,
                    hosts: Dict[str, Dict[str, Any]]) -> None:
    """The device must be registered on a host of this server and be in scope.

    ``device_name`` is the display name every script_results writer stores; a
    registered device without a display name is named by its id. ``hosts`` is
    the same registry snapshot the scope was built from.
    """
    if not isinstance(host_name, str) or not isinstance(device_name, str) or not host_name or not device_name:
        raise ScopeError('host_name and device_name are required', 400)
    devices = (hosts.get(host_name) or {}).get('devices')
    registered = any(
        (d.get('device_name') or d.get('device_id')) == device_name
        for d in (devices if isinstance(devices, list) else []) if isinstance(d, dict))
    if not registered or not scope.allows_device(host_name, device_name):
        raise ScopeError('host/device is not registered in your scope on this server', 404)


def steps_from_request(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or not raw or len(raw) > MAX_STEPS:
        raise ScopeError(f'steps must be a list of 1..{MAX_STEPS} items', 400)
    steps = []
    for item in raw:
        if not isinstance(item, dict):
            raise ScopeError('each step must be an object', 400)
        label = item.get('label')
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > LABEL_MAX:
            raise ScopeError(f'step label is required (1..{LABEL_MAX} characters)', 400)
        required = item.get('required', True)
        if not isinstance(required, bool):
            raise ScopeError('step required must be a boolean', 400)
        expected = item.get('expected')
        if expected is not None and (not isinstance(expected, str) or len(expected) > 1000):
            raise ScopeError('step expected must be a string of at most 1000 characters', 400)
        steps.append({'label': label.strip(), 'required': required,
                      'expected': (expected or '').strip() or None})
    return steps


def steps_from_graph(graph: Any) -> List[Dict[str, Any]]:
    nodes = graph.get('nodes') if isinstance(graph, dict) else None
    steps = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get('type') or '').lower()
        if node_type in _GRAPH_SKIP_TYPES:
            continue
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        label = data.get('label') or data.get('command') or node_type
        if not label:
            continue
        expected = data.get('expected') or data.get('description')
        steps.append({'label': str(label).strip()[:LABEL_MAX], 'required': True,
                      'expected': str(expected).strip()[:1000] if expected else None})
    return steps[:MAX_STEPS]


def build_snapshot(version_row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'testcase_id': str(version_row.get('testcase_id')),
        'version_number': version_row.get('version_number'),
        'testcase_name': version_row.get('testcase_name'),
        'description': version_row.get('description'),
        'userinterface_name': version_row.get('userinterface_name'),
        'graph_json': version_row.get('graph_json'),
        'snapshot_timestamp': version_row.get('snapshot_timestamp'),
    }


def step_updates(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_STEPS:
        raise ScopeError(f'steps must be a list of at most {MAX_STEPS} items', 400)
    updates = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get('ordinal'), int) or item['ordinal'] < 0:
            raise ScopeError('each step update needs an integer ordinal', 400)
        update: Dict[str, Any] = {'ordinal': item['ordinal']}
        if 'outcome' in item:
            if item['outcome'] is not None and item['outcome'] not in OUTCOMES:
                raise ScopeError(f'outcome must be one of {", ".join(OUTCOMES)} or null', 400)
            update['outcome'] = item['outcome']
        if 'note' in item:
            note = item['note']
            if note is not None and (not isinstance(note, str) or len(note) > NOTE_MAX):
                raise ScopeError(f'note must be a string of at most {NOTE_MAX} characters', 400)
            update['note'] = (note.strip() or None) if isinstance(note, str) else None
        if 'evidence_url' in item:
            url = item['evidence_url']
            if url is not None:
                if not isinstance(url, str) or len(url) > URL_MAX or not url.lower().startswith(('http://', 'https://')):
                    raise ScopeError('evidence_url must be an http(s) URL', 400)
            update['evidence_url'] = url
        updates.append(update)
    return updates


def present(session: Dict[str, Any], *, include_snapshot: bool) -> Dict[str, Any]:
    steps = session.get('steps') or []
    out = {k: v for k, v in session.items() if k != 'testcase_snapshot' or include_snapshot}
    out['actor_name'] = None
    out['steps'] = [{**s, 'evidence': s.get('evidence_url'), 'evidence_missing': s.get('evidence_url') is None}
                    for s in steps]
    out['summary'] = {
        'steps_total': len(steps),
        'steps_passed': sum(1 for s in steps if s.get('outcome') == 'passed'),
        'steps_failed': sum(1 for s in steps if s.get('outcome') == 'failed'),
        'steps_skipped': sum(1 for s in steps if s.get('outcome') == 'skipped'),
        'steps_blocked': sum(1 for s in steps if s.get('outcome') == 'blocked'),
        'required_without_outcome': sum(1 for s in steps if s.get('required') and s.get('outcome') is None),
        'steps_without_evidence': sum(1 for s in steps if s.get('evidence_url') is None),
    }
    return out


def require_actor(session: Dict[str, Any], actor: str, role: Optional[str]) -> None:
    if session.get('actor_id') != actor and role not in ('admin', 'service'):
        raise ScopeError('only the person running this manual session can change it', 403)
