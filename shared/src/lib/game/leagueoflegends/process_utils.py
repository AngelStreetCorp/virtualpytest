"""In-process process queries and kills for the Windows League tooling.

The phase-0 and practice launchers run under ``pythonw.exe`` (no console), so every console program they spawn
(``tasklist``, ``taskkill``, ``cmd``) opens a console window that flashes on the user's desktop. ``psutil`` does the same
work in-process. Windows-only at runtime; ``psutil`` is imported lazily so macOS test runs do not need it.
"""

from __future__ import annotations

from typing import Iterable, List


def pids_by_name(image_name: str) -> List[int]:
    """PIDs of every process whose image name equals ``image_name`` (case-insensitive)."""
    import psutil

    wanted = image_name.casefold()
    pids: List[int] = []
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name") or ""
        if name.casefold() == wanted:
            pids.append(proc.pid)
    return pids


def is_running(image_name: str) -> bool:
    return bool(pids_by_name(image_name))


def kill_by_names(image_names: Iterable[str]) -> int:
    """Kill every process (and its children) matching one of ``image_names``. Returns the count killed."""
    import psutil

    killed = 0
    for image_name in image_names:
        for pid in pids_by_name(image_name):
            try:
                proc = psutil.Process(pid)
                for child in proc.children(recursive=True):
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
                proc.kill()
                killed += 1
            except psutil.Error:
                continue
    return killed
