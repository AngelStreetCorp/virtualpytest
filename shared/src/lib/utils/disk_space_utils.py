"""
Disk space utilities.

One place that answers "how full is the filesystem behind this path, and which
mount is that". Three callers need the same answer for different reasons:

- the host metric, so the dashboard watches the filesystems that can actually
  fill rather than only `/` (a host reported Disk=9.8% while the 960 GB /data
  holding every capture, reference and report was at 100% — BUG-0198);
- the screenshot path, so an ENOSPC failure can name the mount instead of
  surfacing as a failed verification;
- the archiver, so retention can tighten as a mount fills.

`shutil.disk_usage` rather than `os.statvfs`, so the same code answers on the
Windows hosts too.
"""

from __future__ import annotations

import os
import shutil
from typing import Dict, List, Optional, Sequence, Tuple

_GB = 1024 ** 3

# Host disk lines on the worst monitored mount (TASK-156). Mirrors DISK_WARNING_PERCENT /
# DISK_ERROR_PERCENT in frontend/src/components/dashboard/hostHealth.ts. Higher than the infra
# VM page (80/90): a full-profile host with 4 capture devices sits near 84 % while healthy.
HOST_DISK_WARNING_PERCENT = 85.0
HOST_DISK_ERROR_PERCENT = 95.0


# Trend rule (TASK-156 goal 4): the outage took 1.5 days, so a host that gains >= 10 points in the
# window and would reach 100 % within 24 h at that pace warns while still under the absolute line.
HOST_DISK_TREND_WINDOW_HOURS = 6
HOST_DISK_TREND_MIN_ELAPSED_HOURS = 2.0
HOST_DISK_TREND_MIN_RISE = 10.0
HOST_DISK_TREND_LOOKAHEAD_HOURS = 24.0


def host_disk_hours_to_full(old_percent: float, new_percent: float, elapsed_hours: float) -> Optional[float]:
    """Hours until 100 % at the pace between two samples; None when the disk is not clearly filling."""
    if elapsed_hours < HOST_DISK_TREND_MIN_ELAPSED_HOURS:
        return None
    rise = new_percent - old_percent
    if rise < HOST_DISK_TREND_MIN_RISE:
        return None
    return max(0.0, (100.0 - new_percent) / (rise / elapsed_hours))


def host_disk_filling_fast(old_percent: float, new_percent: float, elapsed_hours: float) -> bool:
    eta = host_disk_hours_to_full(old_percent, new_percent, elapsed_hours)
    return eta is not None and eta <= HOST_DISK_TREND_LOOKAHEAD_HOURS


def host_disk_severity(percent: Optional[float]) -> Optional[str]:
    """'error' from 95 %, 'warning' from 85 %, None below or when unknown."""
    if percent is None:
        return None
    if percent >= HOST_DISK_ERROR_PERCENT:
        return 'error'
    return 'warning' if percent >= HOST_DISK_WARNING_PERCENT else None


def _existing_ancestor(path: str) -> str:
    """Nearest existing directory at or above `path`.

    The path handed in is often a file that could not be created (the ENOSPC
    case), so statting it directly would fail.
    """
    p = os.path.abspath(path)
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def mount_point_for(path: str) -> str:
    """Mount point of the filesystem holding `path`; the drive root on Windows."""
    p = _existing_ancestor(path)
    if os.name == 'nt':
        drive, _ = os.path.splitdrive(p)
        return drive + os.sep if drive else p
    while p != os.sep and not os.path.ismount(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p or os.sep


def usage_for(path: str) -> Optional[Dict]:
    """{mount, total_gb, used_gb, free_gb, percent, free_percent} or None."""
    p = _existing_ancestor(path)
    try:
        usage = shutil.disk_usage(p)
    except OSError:
        return None
    if usage.total <= 0:
        return None
    return {
        'mount': mount_point_for(p),
        'total_gb': round(usage.total / _GB, 2),
        'used_gb': round(usage.used / _GB, 2),
        'free_gb': round(usage.free / _GB, 2),
        'percent': round(100.0 * usage.used / usage.total, 2),
        'free_percent': round(100.0 * usage.free / usage.total, 2),
    }


def worst_usage(paths: Sequence[str]) -> Tuple[Optional[Dict], List[Dict]]:
    """(fullest mount, every distinct mount) for the given paths.

    Deduplicated by device id, so a host whose stream tree lives on `/` reports
    one entry rather than the same filesystem twice. The first path to reach a
    filesystem names it.
    """
    seen_devices = set()
    entries: List[Dict] = []
    for path in paths:
        if not path:
            continue
        probe = _existing_ancestor(path)
        try:
            device_id = os.stat(probe).st_dev
        except OSError:
            continue
        if device_id in seen_devices:
            continue
        usage = usage_for(probe)
        if not usage:
            continue
        seen_devices.add(device_id)
        entries.append(usage)
    if not entries:
        return None, []
    return max(entries, key=lambda entry: entry['percent']), entries


def describe_out_of_space(path: str) -> str:
    """Operator-facing reason for an ENOSPC, naming the mount that is full."""
    usage = usage_for(path)
    if not usage:
        return f'the host is out of disk space while writing {path}'
    return (
        f"the host is out of disk space on {usage['mount']} "
        f"({usage['free_gb']:.1f} GB free of {usage['total_gb']:.1f} GB)"
    )
