"""Process-wide cached CodeIndex, rebuilt when the checkout's version (git HEAD or VERSION.txt) changes."""
import threading
from pathlib import Path
from typing import Optional

from .build import build_index, git_head
from .constants import PAUSE_S, WARM_DELAY_S
from .types import CodeIndex

_lock = threading.Lock()
_cache = {"repo": None, "head": None, "index": None, "warming": False}


def repo_root() -> str:
    """features/code-graph/lib/code_index/store.py -> repo root (same rule as docs_tools._docs_root)."""
    return str(Path(__file__).resolve().parents[4])


def _gevent_patched() -> bool:
    try:
        from gevent import monkey
        return monkey.is_module_patched("threading")
    except ImportError:
        return False


def _build(repo: str) -> CodeIndex:
    """The server is one gevent process: ~20 s of CPU on its loop would stall every request. The build runs in
    the calling greenlet and yields to the loop every few files, so nothing waits on a thread or a child process
    (a threadpool and a child-process build both hung inside the app: BUG-0700)."""
    if _gevent_patched():
        import gevent
        return build_index(repo, pause=lambda: gevent.sleep(PAUSE_S))  # >0: a 0 sleep skips polling sockets and timers
    return build_index(repo)


def get_index(repo: Optional[str] = None) -> CodeIndex:
    """Index of `repo` (default: this checkout). First call builds it (~15-25 s); later calls are free until the
    version moves."""
    repo = repo or repo_root()
    head = git_head(repo)
    with _lock:
        if _cache["index"] is None or _cache["repo"] != repo or _cache["head"] != head:
            _cache.update(repo=repo, head=head, index=_build(repo))
        return _cache["index"]


def warm(repo: Optional[str] = None) -> None:
    """Start building in the background so the first agent call does not wait. Idempotent."""
    if _cache["index"] is not None or _cache["warming"]:
        return
    _cache["warming"] = True

    def run():
        try:
            get_index(repo)
        finally:
            _cache["warming"] = False
    if _gevent_patched():
        import gevent
        gevent.spawn_later(WARM_DELAY_S, run)
        return
    threading.Thread(target=run, name="code-refs-warm", daemon=True).start()
