#!/usr/bin/env python3
"""
AVQ monitor — continuous per-minute audio/video quality worker.

Standalone process (vpt-avq.service), intentionally SEPARATE from capture_monitor.py
/ detector.py so it can never perturb the realtime detection hot path. Once per
minute, for every active capture device it:
  1. measures AVQ via avq_analyze.analyze_device() (reads JPEGs + MP3 chunks only)
  2. writes one quality_metrics row to Supabase

Reads only derived files — never the USB capture card (no MS2109 contention).
See docs/agent/AVQ_IMPLEMENTATION.md.

Run standalone for testing (no service needed):
    python3 avq_monitor.py --once            # one pass over all devices, then exit
    python3 avq_monitor.py --once capture1    # one pass, single device
    python3 avq_monitor.py                    # continuous, every 60s
"""
import os
import sys
import time
import logging

# features/avq/backend_host/avq_monitor.py -> project root is three levels up
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
backend_host_dir = os.path.join(project_root, 'backend_host')
sys.path.insert(0, project_root)

# --- env (project .env then backend_host .env), same order as incident_manager ---
try:
    from dotenv import load_dotenv
    for p in (os.path.join(project_root, '.env'),
              os.path.join(backend_host_dir, 'src', '.env')):
        if os.path.exists(p):
            load_dotenv(p, encoding='utf-8-sig')
except ImportError:
    pass

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [avq] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger('avq')

from avq_analyze import analyze_device  # noqa: E402
from shared.src.lib.utils.storage_path_utils import (  # noqa: E402
    get_capture_base_directories, get_capture_folder,
    get_device_info_from_capture_folder,
)

WINDOW_SECONDS = int(os.getenv('AVQ_WINDOW_SECONDS', '60'))
INTERVAL_SECONDS = int(os.getenv('AVQ_INTERVAL_SECONDS', '60'))
HOST_NAME = os.getenv('HOST_NAME', 'unknown')


def _device_folders():
    """Active capture folders (e.g. ['capture1', 'capture2'])."""
    folders = []
    for base in get_capture_base_directories():
        folder = get_capture_folder(base)
        if folder:
            folders.append(folder)
    return folders


def run_once(only_folder=None, store=True):
    folders = [only_folder] if only_folder else _device_folders()
    if not folders:
        logger.warning("no active capture devices found")
        return []

    results = []
    for folder in folders:
        try:
            info = get_device_info_from_capture_folder(folder)
            metrics = analyze_device(folder, WINDOW_SECONDS)
            logger.info("[%s] vMOS=%s aMOS=%s blur=%s block=%s lkfs=%s sil=%ss "
                        "frames=%s (%sms)",
                        folder, metrics.get('video_mos'), metrics.get('audio_mos'),
                        metrics.get('blurriness_score'), metrics.get('blockiness_score'),
                        metrics.get('loudness_lkfs'), metrics.get('silence_seconds'),
                        metrics.get('_frames'), metrics.get('_elapsed_ms'))
            if store:
                from features.avq.lib.quality_metrics_db import store_quality_metrics
                store_quality_metrics(HOST_NAME, info, metrics)
            results.append((folder, metrics))
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] analyze failed: %s", folder, e)
    return results


def run_forever():
    logger.info("AVQ monitor started: host=%s window=%ss interval=%ss",
                HOST_NAME, WINDOW_SECONDS, INTERVAL_SECONDS)
    while True:
        start = time.time()
        run_once(store=True)
        # align to the interval (skip if a pass overran)
        sleep = INTERVAL_SECONDS - (time.time() - start)
        if sleep > 0:
            time.sleep(sleep)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:]]
    once = '--once' in args
    no_store = '--no-store' in args
    folder = next((a for a in args if not a.startswith('--')), None)
    if once:
        run_once(only_folder=folder, store=not no_store)
    else:
        run_forever()
