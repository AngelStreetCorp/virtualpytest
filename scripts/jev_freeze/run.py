#!/usr/bin/env python3
"""Freeze triage benchmark CLI (TASK-38 goal 5):

  run.py export --bundle DIR [--limit N]     # server, as vpt_user with the .env
  run.py facts  --bundle DIR [--workers N]   # codebox (cv2 + tesseract)
  run.py decide --bundle DIR [--limit N]     # server (OpenRouter key)
  run.py report --bundle DIR                 # anywhere
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))

from scripts.jev_freeze import LAB_TEAM  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('phase', choices=['export', 'facts', 'decide', 'report'])
    ap.add_argument('--bundle', required=True)
    ap.add_argument('--team-id', default=LAB_TEAM)
    ap.add_argument('--limit', type=int)
    ap.add_argument('--workers', type=int, default=0)
    a = ap.parse_args()
    os.makedirs(a.bundle, exist_ok=True)
    if a.phase == 'export':
        from scripts.jev_freeze.export import run_export
        out = run_export(a.bundle, a.team_id, a.limit)
    elif a.phase == 'facts':
        from scripts.jev_freeze.facts import run_facts
        out = run_facts(a.bundle, a.workers)
    elif a.phase == 'decide':
        from scripts.jev_freeze.decide import run_decide
        out = run_decide(a.bundle, a.team_id, a.limit)
    else:
        from scripts.jev_freeze.report import run_report
        print(run_report(a.bundle))
        return 0
    print(json.dumps(out, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
