"""Host disk cleanup: delete only EXPIRED capture files (dashboard "Fix now" for a full host disk).

Same retention classes as backend_host/scripts/hot_cold_archiver.py (root live files 1 h, archived hour folders 26 h,
reports and loose artifacts shrunk to the archiver's 'high pressure' 3 days), applied at once instead of on the
archiver's cadence. Safety rules, all enforced in ``_plan``:

- only inside the capture dirs of this host (``get_capture_base_directories``), only the named sub-folders;
- cold hour folders keep the 24 h the AVQ viewer and the circular buffer serve (floor: 26 h);
- hot (RAM) folders, the rotating 1 min slots in ``temp/``, manifests, configs, ``.env`` are never matched;
- a file touched in the last ``MIN_AGE_SECONDS`` is never deleted (a recording in use); symlinks are never followed.
"""

import fnmatch
import os
import shutil
import time
from typing import Dict, List, Tuple

ROOT_STALE_SECONDS = 3600          # archiver ROOT_STALE_MAX_AGE_SECONDS
ARCHIVE_STALE_SECONDS = 26 * 3600  # archiver ARCHIVE_STALE_MAX_AGE_SECONDS (never below 24 h)
REPORTS_STALE_SECONDS = 3 * 86400  # archiver 'high' tier reports window
VERIFICATION_STALE_SECONDS = 86400
MIN_AGE_SECONDS = 600
ROOT_ARTIFACT_PREFIXES = ('original_with_crop_', 'verification_failure_', 'kpi_failure_')

# (sub-folder, pattern, root-only?, max age): root-only rules sweep the live folder, the others its hour sub-folders.
_RULES: List[Tuple[str, str, bool, int]] = [
    ('captures', 'capture_*.jpg', True, ROOT_STALE_SECONDS),
    ('captures', 'capture_*.jpg', False, ARCHIVE_STALE_SECONDS),
    ('thumbnails', 'capture_*_thumbnail.jpg', True, ROOT_STALE_SECONDS),
    ('thumbnails', 'capture_*_thumbnail.jpg', False, ARCHIVE_STALE_SECONDS),
    ('segments', 'segment_*.ts', True, ROOT_STALE_SECONDS),
    ('segments', 'chunk_10min_*.mp4', False, ARCHIVE_STALE_SECONDS),
    ('metadata', 'capture_*.json', True, ROOT_STALE_SECONDS),
    ('metadata', 'chunk_10min_*.json', False, ARCHIVE_STALE_SECONDS),
]


def disk_usage_pct(path: str = '/') -> float:
    usage = shutil.disk_usage(path)
    return round(usage.used * 100.0 / usage.total, 1) if usage.total else 0.0


def _stale(path: str, patterns: Tuple[str, ...], max_age: float, now: float, recursive: bool, skip_root: bool = False) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    limit = max(max_age, MIN_AGE_SECONDS)
    if not os.path.isdir(path):
        return out
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        if not recursive:
            dirnames[:] = []
        elif skip_root and dirpath == path:
            filenames = []
        for name in filenames:
            if not any(fnmatch.fnmatch(name, p) for p in patterns):
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            if now - st.st_mtime > limit:
                out.append((full, st.st_size))
    return out


def _plan(capture_dirs: List[str], now: float) -> List[Tuple[str, int]]:
    plan: Dict[str, int] = {}
    for base in capture_dirs:
        for folder, pattern, root_only, age in _RULES:
            sub = os.path.join(base, folder)
            hits = _stale(sub, (pattern,), age, now, recursive=not root_only, skip_root=not root_only)
            plan.update(hits)
        plan.update(_stale(os.path.join(base, 'captures', 'verification_results'), ('*',), VERIFICATION_STALE_SECONDS, now, True))
        plan.update(_stale(os.path.join(base, 'reports'), ('*',), REPORTS_STALE_SECONDS, now, True))
        plan.update(_stale(base, tuple(p + '*' for p in ROOT_ARTIFACT_PREFIXES), REPORTS_STALE_SECONDS, now, False))
    return list(plan.items())


def run_cleanup(capture_dirs: List[str], dry_run: bool = True, now: float = None, disk_path: str = '/') -> Dict:
    """{freed_bytes, files, dry_run, disk_before, disk_after}; ``disk_after`` is None for a dry run."""
    now = time.time() if now is None else now
    disk_before = disk_usage_pct(disk_path)
    plan = _plan([d for d in capture_dirs if d and os.path.isdir(d)], now)
    freed = files = 0
    if dry_run:
        freed, files = sum(size for _, size in plan), len(plan)
    else:
        for path, size in plan:
            try:
                os.remove(path)
            except OSError:
                continue
            freed += size
            files += 1
    return {
        'freed_bytes': freed,
        'files': files,
        'dry_run': dry_run,
        'disk_before': disk_before,
        'disk_after': None if dry_run else disk_usage_pct(disk_path),
    }
