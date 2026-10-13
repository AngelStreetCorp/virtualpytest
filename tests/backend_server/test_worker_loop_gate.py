"""One asyncio loop at a time per server worker (agent/async_utils.run_in_worker_loop).

Under gevent every request is a greenlet in one OS thread and asyncio's "a loop is running"
flag is per OS thread, so a second asyncio.run() while another greenlet's loop is parked
fails with "cannot be called from a running event loop". Live on the Pi server
(2026-10-04): an Atlas chat started while a Test Prompt exploration was running crashed.
The gevent cases run in a subprocess because monkey.patch_all() must not leak into the
rest of the suite.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _run_gevent(body: str) -> str:
    pytest.importorskip("gevent")
    script = "from gevent import monkey; monkey.patch_all()\n" + textwrap.dedent(body)
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60,
                            env={"PYTHONPATH": f"{ROOT}:{ROOT / 'backend_server' / 'src'}", "PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


CONCURRENT = """
import asyncio, gevent
{runner}

order = []

async def job(name):
    order.append(f"{{name}}-start")
    for _ in range(5):
        await asyncio.sleep(0.02)   # yields to the gevent hub, like a real LLM/HTTP wait
        gevent.sleep(0)
    order.append(f"{{name}}-end")
    return name

def worker(name):
    try:
        return run(job(name))
    except RuntimeError as exc:
        return f"{{name}}: {{exc}}"

results = gevent.joinall([gevent.spawn(worker, "chat"), gevent.spawn(worker, "testprompt")])
print([g.value for g in results])
print(order)
"""


def test_two_plain_asyncio_runs_collide_under_gevent():
    """The failure being fixed, reproduced: no gate, two greenlets, one crashes."""
    out = _run_gevent(CONCURRENT.format(runner="run = asyncio.run"))
    assert "cannot be called from a running event loop" in out


def test_gated_runs_queue_instead_of_crashing():
    out = _run_gevent(CONCURRENT.format(runner="from agent.async_utils import run_in_worker_loop as run"))
    results, order = out.strip().splitlines()
    assert results == "['chat', 'testprompt']"
    assert order == "['chat-start', 'chat-end', 'testprompt-start', 'testprompt-end']"


def test_both_import_paths_share_one_gate():
    out = _run_gevent("""
        import agent.async_utils as a
        import backend_server.src.agent.async_utils as b
        print(a is b, a._GATE is b._GATE)
    """)
    assert out.strip() == "False True"


def test_waiting_caller_is_told_and_nested_use_fails_fast():
    sys.path.insert(0, str(ROOT / "backend_server" / "src"))
    from agent.async_utils import run_in_worker_loop
    import asyncio

    told = []
    started = threading.Event()

    async def slow():
        started.set()
        await asyncio.sleep(0.2)
        return "slow"

    first = threading.Thread(target=lambda: run_in_worker_loop(slow()))
    first.start()
    started.wait(2)
    t0 = time.time()
    assert run_in_worker_loop(asyncio.sleep(0, result="second"), on_wait=lambda: told.append(True)) == "second"
    first.join()
    assert told == [True] and time.time() - t0 >= 0.1

    async def nested():
        return run_in_worker_loop(asyncio.sleep(0))
    with pytest.raises(RuntimeError, match="inside the worker's running event loop"):
        run_in_worker_loop(nested())
