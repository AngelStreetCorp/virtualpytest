#!/usr/bin/env python3
"""An isolated backend_server for agent benchmarks: real database, no lab.

Atlas acts on any device the server can list (BUG-0914), so an agent benchmark must never run against a
server with hosts. This starts the backend from the current checkout with:

- no hosts: a fresh process on its own port that no host registers with (``getAllHosts`` → ``[]``);
- the MCP tools pointed at itself (``SERVER_BASE_URL``), so no tool reaches another server;
- no agent background workers (they consume shared queues), no server-metrics or infra-status writers.

The database and the AI routing are the real ones (from the repo ``.env``), so scripts, userinterfaces and
``ai_calls`` rows are real — clean up what a run creates.

Run from the repo root (codebox: copy the repo ``.env`` first):

    SERVER_PORT=5213 python3 scripts/agent/isolated_backend.py
    curl -s localhost:5213/server/health

Extra environment (``ATLAS_MEMORY=…`` etc.) passes through.
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = os.environ.setdefault("SERVER_PORT", "5213")
os.environ.setdefault("SERVER_BASE_URL", f"http://127.0.0.1:{PORT}")
os.environ.setdefault("SERVER_URL", f"http://127.0.0.1:{PORT}")
os.environ.setdefault("SERVER_NAME", "isolated-bench")
os.environ.setdefault("REPORT_SHARING_ENABLED", "false")
os.chdir(ROOT)

spec = importlib.util.spec_from_file_location("vpt_app", os.path.join(ROOT, "backend_server/src/app.py"))
app = importlib.util.module_from_spec(spec)
sys.modules["vpt_app"] = app
spec.loader.exec_module(app)


def _noop(*_args, **_kwargs):
    return None


app.start_agent_background_workers = _noop
import backend_server.src.lib.server.gunicorn_app as gunicorn_app  # noqa: E402

gunicorn_app._collect_server_metrics = _noop
gunicorn_app.collect_infra_status_forever = _noop
print(f"[isolated-backend] port {PORT}: background workers, metrics and infra status disabled", flush=True)
app.main()
