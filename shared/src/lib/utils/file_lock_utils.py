"""
Cross-platform file locking utilities.

Linux/macOS: uses fcntl.flock()
Windows: uses msvcrt.locking() (no shared lock support; shared treated as exclusive)

This exists because `fcntl` is not available on Windows, but several utilities
need a best-effort inter-process lock to avoid concurrent writers.
"""

from __future__ import annotations

import os
from typing import IO


if os.name == "nt":
    import msvcrt

    def lock_file(f: IO[object], exclusive: bool = True) -> None:
        # msvcrt.locking locks a byte range starting at the current file position.
        try:
            f.seek(0)
        except Exception:
            pass

        # Windows does not provide a portable "shared" lock via msvcrt.
        # Treat shared as exclusive to preserve correctness.
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def unlock_file(f: IO[object]) -> None:
        try:
            try:
                f.seek(0)
            except Exception:
                pass
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            # Best-effort unlock. If the file is already unlocked/closed, ignore.
            pass

else:
    import fcntl

    def lock_file(f: IO[object], exclusive: bool = True) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)

    def unlock_file(f: IO[object]) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

