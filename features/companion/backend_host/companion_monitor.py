#!/usr/bin/env python3
"""
Live-TV companion service (vpt-companion.service, TASK-05).

Standalone process, intentionally SEPARATE from capture_monitor.py (like vpt-avq): it only reads
what capture already writes — the newest ``capture_*.json`` in the device's metadata folder (its
blackscreen / motion / localize fields and the frame filename), the frame JPEG itself, and
``last_zapping.json`` — and writes its result to ``<metadata>/companion.json``, which the
feature's host route serves.

EXPERIMENTAL — OFF BY DEFAULT, like transcription. Two gates, both needed:
- per host: ``ENABLE_COMPANION=true``. The unit ships ``ENABLE_COMPANION=false`` (it wins over the
  .env, which python-dotenv never overrides), so turn it on for one host with a drop-in:
      sudo systemctl edit vpt-companion.service
        [Service]
        Environment=ENABLE_COMPANION=true
      sudo systemctl restart vpt-companion.service
- per device: ``DEVICE{N}_COMPANION=true`` in the host .env.
Off, the service only sleeps: the pipeline (OpenCV, AI client) is never imported and no AI call
is made.

Run by hand (same as the unit): python3 companion_monitor.py
"""
import logging
import os
import re
import sys
import time

# features/companion/backend_host/companion_monitor.py -> project root is three levels up
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
sys.path.insert(0, project_root)

try:
    from dotenv import load_dotenv
    for p in (os.path.join(project_root, '.env'),
              os.path.join(project_root, 'backend_host', 'src', '.env')):
        if os.path.exists(p):
            load_dotenv(p, encoding='utf-8-sig')
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s [companion] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger('companion')

_TRUTHY = ('1', 'true', 'yes', 'on')
TICK_S = 1.0
# Rewrite the result at least this often so the host route can tell a live service from a dead one.
KEEPALIVE_S = 10.0


def companion_enabled() -> bool:
    """The per-host switch (ENABLE_COMPANION, default off: experimental)."""
    return os.environ.get('ENABLE_COMPANION', '').strip().lower() in _TRUTHY


def enabled_devices() -> list:
    ids = []
    for key, value in os.environ.items():
        m = re.fullmatch(r'DEVICE(\d+)_COMPANION', key)
        if m and value.strip().lower() in _TRUTHY:
            ids.append(f'device{m.group(1)}')
    return sorted(ids)


def newest_capture_json(metadata_dir: str):
    """Path of the newest capture_*.json by mtime, or None.

    Not ctime: on Windows that is the creation time. A later rewrite of an older frame's JSON (zap
    results) can win for one tick; the next tick picks the newest frame again.
    """
    best, best_mtime = None, -1.0
    try:
        with os.scandir(metadata_dir) as entries:
            for entry in entries:
                name = entry.name
                if not (name.startswith('capture_') and name.endswith('.json')):
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if mtime > best_mtime:
                    best, best_mtime = entry.path, mtime
    except OSError:
        return None
    return best


def _load(path: str):
    import json
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _idle(reason: str) -> None:
    logger.info('%s; idling', reason)
    while True:
        time.sleep(3600)


def run() -> None:
    if not companion_enabled():
        _idle('off on this host (ENABLE_COMPANION is not true; see this file\'s header to enable)')
    devices = enabled_devices()
    if not devices:
        _idle('no device has DEVICE{N}_COMPANION=true')
    # Imported only when on, so a disabled host never loads OpenCV or the AI client.
    from features.companion.backend_host.companion import create_companion
    from features.companion.lib.store import result_path, write_result
    from shared.src.lib.utils.storage_path_utils import (
        get_capture_folder_from_device_id, get_captures_path, get_metadata_path,
    )

    companion = create_companion()
    folders = {d: get_capture_folder_from_device_id(d) for d in devices}
    last_written = {}
    logger.info('started for %s', ', '.join(f'{d} ({f})' for d, f in folders.items()))
    while True:
        for device_id, folder in folders.items():
            try:
                metadata_dir = get_metadata_path(folder)
                latest = newest_capture_json(metadata_dir)
                analysis = _load(latest) if latest else None
                if analysis and analysis.get('filename'):
                    frame = os.path.join(get_captures_path(folder), analysis['filename'])
                    companion.observe(device_id, frame, metadata_dir, analysis)
                result = companion.result(device_id)
                prev = last_written.get(device_id)
                if result is not None and (prev is None or prev[1] != result or time.time() - prev[0] > KEEPALIVE_S):
                    write_result(result_path(device_id), result)
                    last_written[device_id] = (time.time(), result)
            except Exception as e:  # noqa: BLE001 — one device must never stop the others
                logger.warning('[%s] tick failed: %s', device_id, e)
        time.sleep(TICK_S)


if __name__ == '__main__':
    run()
