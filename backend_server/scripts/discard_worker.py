#!/usr/bin/env python3
"""
VirtualPyTest discard background worker (two systemd services, both installed disabled).

- `vpt-discard-scripts`:   `discard_worker.py`              — Sherlock on the Redis queue p2_scripts.
- `vpt-discard-incidents`: `discard_worker.py --incidents`  — Nightwatch alert triage: polls the
  `alerts` table every ALERT_DISCARD_POLL_S (30) seconds (backend_server/src/agent/core/nightwatch_handler.py).
"""

import os
import signal
import sys
import time
from pathlib import Path


RUNNING = True


def _setup_paths() -> Path:
    """Ensure project modules are importable when launched from systemd."""
    project_root = Path(__file__).resolve().parents[2]
    backend_src = project_root / "backend_server" / "src"

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    if str(backend_src) not in sys.path:
        sys.path.insert(0, str(backend_src))

    return project_root


def _handle_signal(signum, _frame):
    global RUNNING
    print(f"[@discard_worker] Received signal {signum}, stopping...")
    RUNNING = False


def _run_incidents() -> int:
    """Alert triage loop: no Redis, the alerts table is the queue."""
    from agent.core.nightwatch_handler import NightwatchHandler

    poll_s = max(5, int(os.getenv("ALERT_DISCARD_POLL_S", "30")))
    handler = NightwatchHandler()
    print(f"[@discard_worker] Alert triage started: poll={poll_s}s min_duration={handler.min_duration_s}s "
          f"repeat_window={handler.repeat_window_h}h daily_max={handler.daily_max}")
    while RUNNING:
        try:
            handler.run_once()
        except Exception as e:
            print(f"[@discard_worker] Alert triage cycle failed: {e}")
        for _ in range(poll_s):
            if not RUNNING:
                break
            time.sleep(1)
    print("[@discard_worker] Worker stopped")
    return 0


def main() -> int:
    project_root = _setup_paths()

    # Load .env from project root when running under systemd.
    try:
        from shared.src.lib.utils.app_utils import load_environment_variables
        load_environment_variables(str(project_root))
    except Exception as e:
        print(f"[@discard_worker] Warning: failed to load env file: {e}")

    from agent.core.manager import QAManagerAgent
    from shared.src.lib.ai import gateway as ai_gateway

    # Runs on the server: resolve AI routes and call providers in-process (TASK-30).
    ai_gateway.use_local_routing()
    # Every AI call of this worker is background monitoring work (TASK-87 call log); per-alert host / device
    # and the script result of a Sherlock review are bound where the call is made.
    from shared.src.lib.ai import caller as ai_caller
    ai_caller.set_process_default(origin='monitoring', job='discard_worker')

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if "--incidents" in sys.argv[1:]:
        return _run_incidents()

    redis_url = os.getenv("REDIS_URL", "")
    print("[@discard_worker] Starting analyzer worker")
    print(f"[@discard_worker] REDIS_URL configured: {bool(redis_url)}")

    agent = QAManagerAgent(agent_id="analyzer", is_background=True)

    # analyzer.yaml deliberately omits background_queues so the backend server
    # (app.py:start_agent_background_workers) does NOT also consume the queue —
    # this dedicated service owns it. But start_background() reads the same
    # config, so without this the worker exits 1 at startup. Inject the queue
    # here, local to this service, rather than re-adding it to the shared YAML.
    if not agent.agent_config.get("background_queues"):
        agent.agent_config["background_queues"] = ["p2_scripts"]
        print("[@discard_worker] Injected background queue: p2_scripts")

    started = agent.start_background()
    if not started:
        print("[@discard_worker] ERROR: analyzer background failed to start")
        return 1

    print("[@discard_worker] Analyzer background started")

    try:
        while RUNNING and agent.background_running:
            time.sleep(5)
    finally:
        try:
            agent.stop_background()
        except Exception as e:
            print(f"[@discard_worker] Warning while stopping background: {e}")
        print("[@discard_worker] Worker stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
