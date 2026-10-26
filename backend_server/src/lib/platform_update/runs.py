"""
Update-run model of the Platform update page (TASK-95).

One run = one maintenance window with seven steps (0 prerequisites, 1 backup, 2 bundle, 3 deploy, 4 migrations,
5 testing, 6 close; TASK-109). The operator triggers
the steps one by one from the page; this module only keeps the state and the log, it runs nothing.

Storage: ``<state_dir>/platform-update/<run_id>.json`` + ``<run_id>.log`` (state dir = integration_state,
OUTSIDE the project tree so a deploy cannot wipe the run it is part of — CONTRACTS #23).

Step states: ``pending`` (not reachable yet), ``waiting`` (the operator's turn), ``running``, ``done``,
``failed``. Run status: ``active`` | ``ok`` | ``failed`` | ``rolled_back``. Only one run is active at a time.

The window has a ``scope`` and ``device_ids``; a run is always ``platform``. Device-scoped windows are
standalone (``windows.py``, TASK-97, created from Settings) and are merged with the run's window by the
``/maintenance`` route.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

STEPS: List[Dict[str, Any]] = [
    {'index': 0, 'key': 'prerequisites', 'title': 'Prerequisites'},
    {'index': 1, 'key': 'backup', 'title': 'Backup'},
    {'index': 2, 'key': 'bundle', 'title': 'Bundle'},
    {'index': 3, 'key': 'deploy', 'title': 'Deploy'},
    {'index': 4, 'key': 'migrations', 'title': 'Migrations'},
    {'index': 5, 'key': 'testing', 'title': 'Testing'},
    {'index': 6, 'key': 'close', 'title': 'Close'},
]
PREREQ_STEP, BACKUP_STEP, BUNDLE_STEP, DEPLOY_STEP, MIGRATIONS_STEP, TESTING_STEP = 0, 1, 2, 3, 4, 5
# Step layout of a stored run. A run written before TASK-109 has no ``layout``: its step numbers mean other
# things, so the step routes refuse it (``LEGACY_MESSAGE``) instead of migrating it.
LAYOUT = 2
LEGACY_MESSAGE = 'This update was started before the 7-step change; close it and start a new one'
LAST_STEP = len(STEPS) - 1

CONTROL_ACTIONS = ('pause', 'resume', 'abort')
STEP_STATES = ('pending', 'waiting', 'running', 'done', 'failed')
FINAL_STATUSES = ('ok', 'failed', 'rolled_back')
SCOPES = ('platform', 'devices')
NOTICE_HOURS = 2  # how long a closed run still shows its "done" notice
LOG_TAIL = 500


class PlatformUpdateError(Exception):
    """Base: message is safe to show to the operator; ``code`` is the HTTP status."""
    code = 400


class ActiveRunExists(PlatformUpdateError):
    code = 409


class RunNotFound(PlatformUpdateError):
    code = 404


class StepOrderError(PlatformUpdateError):
    code = 409


class LegacyRun(PlatformUpdateError):
    code = 409


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _parse(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PlatformUpdateError('invalid date')
    try:
        dt = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        raise PlatformUpdateError(f'invalid date: {value}')
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class RunStore:
    """File-backed store; one instance per directory (tests pass a tmp dir)."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self._lock = threading.RLock()

    # -- files --------------------------------------------------------------------------------
    def _json(self, run_id: str) -> Path:
        if not run_id or not all(c.isalnum() or c in '-_' for c in run_id):
            raise RunNotFound('run not found')
        return self.dir / f'{run_id}.json'

    def log_path(self, run_id: str) -> Path:
        self._json(run_id)
        return self.dir / f'{run_id}.log'

    def _save(self, run: Dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._json(run['id'])
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(run, ensure_ascii=True), encoding='utf-8')
        os.replace(tmp, path)

    def get(self, run_id: str) -> Dict[str, Any]:
        path = self._json(run_id)
        if not path.is_file():
            raise RunNotFound('run not found')
        return json.loads(path.read_text(encoding='utf-8'))

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.dir.is_dir():
            return []
        runs = []
        for p in self.dir.glob('*.json'):
            try:
                runs.append(json.loads(p.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                continue
        runs.sort(key=lambda r: r.get('started_at', ''), reverse=True)
        return runs[:limit]

    def active(self) -> Optional[Dict[str, Any]]:
        return next((r for r in self.list_runs(200) if r.get('status') == 'active'), None)

    # -- log ----------------------------------------------------------------------------------
    def log(self, run_id: str, line: str, step: Optional[int] = None) -> None:
        stamp = _now().strftime('%Y-%m-%d %H:%M:%S')
        prefix = f'[step {step}] ' if step is not None else ''
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.log_path(run_id), 'a', encoding='utf-8') as fh:
                for part in str(line).splitlines() or ['']:
                    fh.write(f'{stamp} {prefix}{part}\n')

    def log_lines(self, run_id: str, tail: int = LOG_TAIL) -> List[str]:
        path = self.log_path(run_id)
        if not path.is_file():
            return []
        return path.read_text(encoding='utf-8').splitlines()[-tail:]

    # -- transitions --------------------------------------------------------------------------
    def start(self, started_by: str, window_start: Optional[str] = None, window_end: Optional[str] = None,
              note: str = '', scope: str = 'platform', device_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        if scope not in SCOPES:
            raise PlatformUpdateError(f'scope must be one of {", ".join(SCOPES)}')
        if scope == 'devices':
            raise PlatformUpdateError("an update run covers the platform; create a device window in Settings")
        start_dt = _parse(window_start) if window_start else _now()
        end_dt = _parse(window_end) if window_end else start_dt + timedelta(hours=1)
        if end_dt <= start_dt:
            raise PlatformUpdateError('the end of the window must be after its start')
        with self._lock:
            if self.active():
                raise ActiveRunExists('an update run is already active; close it first')
            run = {
                'id': datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6],
                'status': 'active',
                'started_by': started_by or 'unknown',
                'started_at': _iso(_now()),
                'window_start': _iso(start_dt),
                'window_end': _iso(end_dt),
                'scope': scope,
                'device_ids': [] if scope == 'platform' else list(device_ids or []),
                'note': (note or '')[:500],
                'closed_at': None,
                'close_message': None,
                'layout': LAYOUT,
                'control': {'pause': False, 'abort': False},
                'steps': [{'index': s['index'], 'key': s['key'], 'title': s['title'],
                           'state': 'pending', 'detail': None, 'data': {},
                           'started_at': None, 'finished_at': None} for s in STEPS],
            }
            self._advance(run)
            self._save(run)
            self.log(run['id'], f'Run started by {run["started_by"]}, window {run["window_start"]} -> {run["window_end"]}')
            return run

    @staticmethod
    def _advance(run: Dict[str, Any]) -> None:
        """The first step that is not done becomes ``waiting`` if it was ``pending``."""
        for step in run['steps']:
            if step['state'] == 'done':
                continue
            if step['state'] == 'pending':
                step['state'] = 'waiting'
            break

    def _require_active(self, run_id: str) -> Dict[str, Any]:
        run = self.get(run_id)
        if run['status'] != 'active':
            raise StepOrderError('this run is closed')
        return run

    def begin_step(self, run_id: str, index: int) -> Dict[str, Any]:
        with self._lock:
            run = self._require_active(run_id)
            if not 0 <= index < LAST_STEP:  # step 6 is closed through close_run
                raise StepOrderError('unknown step')
            for earlier in run['steps'][:index]:
                if earlier['state'] != 'done':
                    raise StepOrderError(f'step {earlier["index"]} ({earlier["title"]}) is not done yet')
            step = run['steps'][index]
            if step['state'] == 'running':
                raise StepOrderError('this step is already running')
            if step['state'] == 'done':
                raise StepOrderError('this step is already done')
            step['state'] = 'running'
            step['started_at'] = _iso(_now())
            step['finished_at'] = None
            self._save(run)
            self.log(run_id, f'{step["title"]}: started', index)
            return run

    def finish_step(self, run_id: str, index: int, ok: bool, detail: str = '',
                    data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            run = self._require_active(run_id)
            step = run['steps'][index]
            if step['state'] != 'running':
                raise StepOrderError('this step is not running')
            step['state'] = 'done' if ok else 'failed'
            step['detail'] = (detail or '')[:1000]
            if data:
                step['data'].update(data)
            step['finished_at'] = _iso(_now())
            self._advance(run)
            self._save(run)
            self.log(run_id, f'{step["title"]}: {"done" if ok else "FAILED"}{" - " + detail if detail else ""}', index)
            return run

    def mark_failed(self, run_id: str, index: int, detail: str) -> Dict[str, Any]:
        """A finished step turns out not to hold (e.g. the code deployment was rolled back): it is ``failed``
        again and later steps are blocked until it is re-run."""
        with self._lock:
            run = self._require_active(run_id)
            step = run['steps'][index]
            if step['state'] == 'pending':
                raise StepOrderError('this step has not started')
            step['state'] = 'failed'
            step['detail'] = (detail or '')[:1000]
            step['finished_at'] = _iso(_now())
            self._save(run)
            self.log(run_id, f'{step["title"]}: FAILED - {detail}', index)
            return run

    def request_control(self, run_id: str, action: str, by: str = '') -> Dict[str, Any]:
        """TASK-128 G12: ``pause`` / ``resume`` / ``abort`` flags of a running deploy. They are only read by the deploy loop
        at its safe points (between machines), never mid-machine. ``abort`` cannot be taken back."""
        if action not in CONTROL_ACTIONS:
            raise PlatformUpdateError(f'action must be one of {", ".join(CONTROL_ACTIONS)}')
        with self._lock:
            run = self._require_active(run_id)
            control = run.setdefault('control', {'pause': False, 'abort': False})
            if control.get('abort'):
                raise StepOrderError('the deploy is already being aborted')
            if action == 'abort':
                control['abort'] = True
                control['pause'] = False
            else:
                control['pause'] = action == 'pause'
            control['by'], control['at'] = by or 'unknown', _iso(_now())
            self._save(run)
            self.log(run_id, f'Deploy {action} requested by {control["by"]} (taken at the next safe point, between machines)', DEPLOY_STEP)
            return run

    def control(self, run_id: str) -> Dict[str, Any]:
        return self.get(run_id).get('control') or {'pause': False, 'abort': False}

    def clear_control(self, run_id: str) -> None:
        with self._lock:
            run = self._require_active(run_id)
            run['control'] = {'pause': False, 'abort': False}
            self._save(run)

    def set_data(self, run_id: str, index: int, data: Dict[str, Any]) -> None:
        """Merge ``data`` into a step without changing its state (progress that is not a transition)."""
        with self._lock:
            run = self._require_active(run_id)
            run['steps'][index]['data'].update(data)
            self._save(run)

    def close(self, run_id: str, status: str, message: str = '') -> Dict[str, Any]:
        if status not in FINAL_STATUSES:
            raise PlatformUpdateError(f'status must be one of {", ".join(FINAL_STATUSES)}')
        with self._lock:
            run = self._require_active(run_id)
            if status == 'ok':
                for step in run['steps'][:LAST_STEP]:
                    if step['state'] != 'done':
                        raise StepOrderError(
                            f'cannot close as ok: step {step["index"]} ({step["title"]}) is not done')
            if any(s['state'] == 'running' for s in run['steps']):
                raise StepOrderError('a step is still running')
            last = run['steps'][LAST_STEP]
            last['state'] = 'done'
            last['finished_at'] = _iso(_now())
            last['detail'] = status
            run['status'] = status
            run['closed_at'] = _iso(_now())
            run['close_message'] = (message or '')[:500]
            self._save(run)
            self.log(run_id, f'Run closed: {status}{" - " + message if message else ""}', LAST_STEP)
            return run

    # -- public views -------------------------------------------------------------------------
    def with_log(self, run: Dict[str, Any]) -> Dict[str, Any]:
        return {**run, 'log': self.log_lines(run['id'])}

    def maintenance(self) -> Dict[str, Any]:
        """What every logged-in user may see: the window, who started it, the current step. No log, no detail."""
        run = self.active()
        if run:
            current = next((s for s in run['steps'] if s['state'] != 'done'), run['steps'][LAST_STEP])
            return {'active': True, 'window': {
                'id': run['id'], 'source': 'run', 'run_id': run['id'], 'scope': run['scope'], 'device_ids': run['device_ids'],
                'window_start': run['window_start'], 'window_end': run['window_end'],
                'started_by': run['started_by'], 'note': run['note'], 'reason': run['note'],
                'current_step': {'index': current['index'], 'title': current['title'], 'state': current['state']},
            }, 'notice': None}
        for run in self.list_runs(5):
            closed = run.get('closed_at')
            if closed and _now() - _parse(closed) < timedelta(hours=NOTICE_HOURS):
                return {'active': False, 'window': None, 'notice': {
                    'id': run['id'], 'source': 'run', 'run_id': run['id'], 'scope': run['scope'], 'status': run['status'],
                    'closed_at': closed, 'message': run.get('close_message') or ''}}
            break
        return {'active': False, 'window': None, 'notice': None}


def is_legacy(run: Dict[str, Any]) -> bool:
    return run.get('layout') != LAYOUT


def default_store() -> RunStore:
    from backend_server.src.lib.utils.integration_state import state_path
    return RunStore(state_path('platform-update'))


def require_backup(run: Dict[str, Any]) -> None:
    """TASK-128 G12: a deploy never starts without the step 1 backup of THIS run (the server enforces it, not the page)."""
    step = run['steps'][BACKUP_STEP]
    if step['state'] != 'done' or not (step['data'].get('backup') or {}).get('ok'):
        raise StepOrderError('step 1 (Backup) must be done in this run before the deploy: it is what a roll back restores from')
