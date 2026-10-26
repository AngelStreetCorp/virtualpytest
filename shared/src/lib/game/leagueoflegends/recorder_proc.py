"""Screen-recorder lifecycle for the LoL bot runs (psutil in-process: no console flash).

An ``ffmpeg -f gdigrab`` recorder started by a run that crashed or was killed kept recording the desktop for 10+ hours
(2026-10-18, four orphans). A run therefore (1) kills leftover recorders of earlier runs when it starts and (2) stops its own
recorder in a ``finally``: ``q`` on stdin so the mp4 is finalised, a kill after ``timeout_s``. The stream's own ffmpeg (no
gdigrab, or output under ``stream``) is never touched.
"""

from __future__ import annotations

from typing import Any, List, Sequence

RUN_FOLDER_MARKERS = ("garen-run-", "bench-run-")


def is_stale_run_recorder(cmdline: Sequence[str], markers: Sequence[str] = RUN_FOLDER_MARKERS) -> bool:
    """True for an ``ffmpeg -f gdigrab`` whose output path is a run folder; False for anything else (the stream's ffmpeg included)."""
    parts = [str(c) for c in cmdline]
    if not parts or "ffmpeg" not in parts[0].lower() or "gdigrab" not in parts:
        return False
    out = parts[-1].lower().replace("/", "\\")
    return "\\stream" not in out and any(mk in out for mk in markers)


def kill_stale_recorders(log: Any = print) -> List[int]:
    """Kill leftover run recorders; returns the PIDs killed."""
    try:
        import psutil
    except ImportError:
        return []
    killed: List[int] = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (p.info.get("name") or "").lower().startswith("ffmpeg") and is_stale_run_recorder(p.info.get("cmdline") or []):
                p.kill()
                killed.append(p.info["pid"])
        except Exception:  # noqa: BLE001 - gone already or access denied: not ours to fix
            continue
    if killed:
        log(f"[recorder] killed {len(killed)} leftover recorder(s): {killed}")
    return killed


def stop_recorder(proc: Any, timeout_s: float = 5.0, log: Any = print) -> str:
    """Stop our own recorder: ``q`` (finalises the mp4), then kill after ``timeout_s``. Returns "stopped ok" | "killed" | "not running"."""
    if proc is None or proc.poll() is not None:
        return "not running"
    try:
        proc.stdin.write(b"q\n")
        proc.stdin.flush()
        proc.wait(timeout=timeout_s)
        verdict = "stopped ok"
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        verdict = "killed"
    log(f"[recorder] {verdict}")
    return verdict
