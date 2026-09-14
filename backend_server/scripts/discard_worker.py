#!/usr/bin/env python3
"""
VirtualPyTest analyzer/discard background worker.

Runs Sherlock queue processing as a standalone systemd service (`vpt-discard-scripts`).
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


def main() -> int:
    project_root = _setup_paths()

    # Load .env from project root when running under systemd.
    try:
        from shared.src.lib.utils.app_utils import load_environment_variables
        load_environment_variables(str(project_root))
    except Exception as e:
        print(f"[@discard_worker] Warning: failed to load env file: {e}")

    from agent.core.manager import QAManagerAgent

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    redis_url = os.getenv("REDIS_URL", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    print("[@discard_worker] Starting analyzer worker")
    print(f"[@discard_worker] REDIS_URL configured: {bool(redis_url)}")
    print(f"[@discard_worker] OPENROUTER_API_KEY configured: {bool(openrouter_key)}")

    agent = QAManagerAgent(agent_id="analyzer", is_background=True)
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
