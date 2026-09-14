#!/usr/bin/env python3
"""
Rebuild transcript manifests from disk for all active capture directories.

Usage:
  python backend_host/scripts/rebuild_transcript_manifests.py
  python backend_host/scripts/rebuild_transcript_manifests.py --capture capture1 --capture capture2
  python backend_host/scripts/rebuild_transcript_manifests.py --capture /var/www/html/stream/capture1
"""
import argparse
import json
import logging
import os
import sys
from typing import List

# Ensure project root is on sys.path when running as a script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend_host.scripts.hot_cold_archiver import rebuild_transcript_manifest_from_disk  # noqa: E402
from shared.src.lib.utils.storage_path_utils import (  # noqa: E402
    get_capture_base_directories,
    get_stream_base_path,
)


def resolve_capture_paths(captures: List[str]) -> List[str]:
    if not captures:
        return []

    base = get_stream_base_path()
    resolved = []
    for cap in captures:
        if os.path.sep in cap or '/' in cap or '\\' in cap:
            path = cap
        else:
            path = os.path.join(base, cap)
        resolved.append(path)
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Rebuild transcript manifests from disk for active captures.'
    )
    parser.add_argument(
        '--capture',
        action='append',
        default=[],
        help='Capture folder name (e.g., capture1) or full path. Can be specified multiple times.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Compute manifests but do not write files.',
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    logger = logging.getLogger('rebuild_transcript_manifests')

    if args.capture:
        capture_dirs = resolve_capture_paths(args.capture)
        logger.info(f"Using {len(capture_dirs)} capture paths from --capture args")
    else:
        capture_dirs = get_capture_base_directories()
        logger.info(f"Loaded {len(capture_dirs)} capture directories from active_captures.conf")

    if not capture_dirs:
        logger.error('No capture directories found. Aborting.')
        return 1

    rebuilt = 0
    for capture_dir in capture_dirs:
        if not os.path.isdir(capture_dir):
            logger.warning(f"Skip (not a directory): {capture_dir}")
            continue

        manifest = rebuild_transcript_manifest_from_disk(capture_dir)
        total_chunks = manifest.get('total_chunks', 0)
        available_hours = manifest.get('available_hours', [])

        logger.info(
            f"{os.path.basename(capture_dir)}: {total_chunks} chunks across {len(available_hours)} hours"
        )

        if args.dry_run:
            continue

        manifest_path = os.path.join(capture_dir, 'transcript', 'transcript_manifest.json')
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        with open(manifest_path + '.tmp', 'w') as f:
            json.dump(manifest, f, indent=2)
        os.replace(manifest_path + '.tmp', manifest_path)
        rebuilt += 1

    logger.info(f"Done. Wrote {rebuilt} transcript manifest file(s).")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
