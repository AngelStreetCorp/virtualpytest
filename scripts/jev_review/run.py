#!/usr/bin/env python3
"""Jev screen-review shadow (TASK-38 goal 6). One bundle directory, four phases:

    run.py export   --bundle DIR [--team ID] [--sets agreed,disputed,human] [--limit N]   server
    run.py evidence --bundle DIR [--workers N]                                            codebox
    run.py decide   --bundle DIR [--team ID] [--limit N] [--workers N]                    server
    run.py report   --bundle DIR [--out FILE]                                             anywhere

export and decide need the .env loaded (run as vpt_user); evidence needs tesseract (deu+eng).
"""
import argparse
import json
import os
import sys

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts.jev_review import LAB_TEAM  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('phase', choices=('export', 'evidence', 'decide', 'report'))
    p.add_argument('--bundle', required=True, help='bundle directory')
    p.add_argument('--team', default=LAB_TEAM)
    p.add_argument('--sets', default='agreed,disputed,human')
    p.add_argument('--limit', type=int, default=None, help='export: rows per set; decide: decisions')
    p.add_argument('--workers', type=int, default=None, help='evidence: processes (default cpus-2); decide: threads (default 1)')
    p.add_argument('--out', default=None, help='report: output file (default <bundle>/report.md)')
    args = p.parse_args(argv)
    bundle = os.path.abspath(args.bundle)
    os.makedirs(bundle, exist_ok=True)
    if args.phase == 'export':
        from scripts.jev_review.export import SETS, run_export
        sets = [s.strip() for s in args.sets.split(',') if s.strip()]
        bad = [s for s in sets if s not in SETS]
        if bad:
            p.error(f"unknown set {bad}; choose from {SETS}")
        result = run_export(bundle, args.team, sets, args.limit)
    elif args.phase == 'evidence':
        from scripts.jev_review.evidence import run_evidence
        result = run_evidence(bundle, args.workers)
    elif args.phase == 'decide':
        from scripts.jev_review.decide import run_decide
        result = run_decide(bundle, args.team, args.limit, args.workers or 1)
    else:
        from scripts.jev_review.report import run_report
        print(run_report(bundle, out_path=args.out))
        return 0
    print(json.dumps(result, indent=1, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
