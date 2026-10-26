"""
tests/backend_host/test_navigation_cancel.py — host side of "Stop cancels a running goto" (TASK-140 G7).
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    import sklearn  # noqa: F401
except ImportError:  # heavy ML dep, irrelevant here: stub any sklearn.* import
    import importlib.abc
    import importlib.machinery
    from unittest.mock import MagicMock

    class _Stub(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, name, path, target=None):
            if name == 'sklearn' or name.startswith('sklearn.'):
                return importlib.machinery.ModuleSpec(name, self, is_package=True)

        def create_module(self, spec):
            m = MagicMock(__path__=[], __name__=spec.name, __spec__=spec)
            return m

        def exec_module(self, module):
            pass

    sys.meta_path.insert(0, _Stub())

try:
    from flask import Flask
    from backend_host.src.services.navigation.navigation_executor import NavigationExecutor
    from backend_host.src.routes import host_navigation_routes as routes
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"host runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit


def _executor():
    ex = NavigationExecutor.__new__(NavigationExecutor)
    import threading
    ex._executions, ex._lock, ex._cancel_event = {}, threading.Lock(), threading.Event()
    return ex


def _running(ex, eid='e1', status='running'):
    ex._executions[eid] = {'execution_id': eid, 'status': status, 'start_time': time.time()}


def test_request_cancel_sets_flag_for_running_execution():
    ex = _executor()
    _running(ex)
    out = ex.request_cancel('e1')
    assert out['success'] and out['cancelled'] and ex._cancel_event.is_set()
    assert ex.get_execution_status('e1')['cancel_requested'] is True
    ex.clear_cancel()
    assert not ex._cancel_event.is_set()


def test_request_cancel_ignores_finished_and_unknown():
    ex = _executor()
    _running(ex, status='completed')
    out = ex.request_cancel('e1')
    assert out['success'] and out['cancelled'] is False and not ex._cancel_event.is_set()
    assert ex.request_cancel('nope')['success'] is False


def test_executor_loop_checks_flag_before_each_edge():
    src = Path(routes.__file__).parents[1].joinpath('services/navigation/navigation_executor.py').read_text()
    loop = src.index("for i, step in enumerate(navigation_path):\n                if self._cancel_event.is_set():")
    assert "cancelled=True" in src[loop:loop + 900]


def _client(ex):
    app = Flask(__name__)
    app.host_devices = {'device1': SimpleNamespace(navigation_executor=ex)}
    app.register_blueprint(routes.host_navigation_bp)
    return app.test_client()


def test_cancel_route():
    ex = _executor()
    _running(ex)
    c = _client(ex)
    r = c.post('/host/navigation/execution/e1/cancel?device_id=device1')
    assert r.status_code == 200 and r.get_json()['cancelled'] is True
    assert c.post('/host/navigation/execution/zz/cancel?device_id=device1').status_code == 404
    assert c.post('/host/navigation/execution/e1/cancel?device_id=other').status_code == 404
