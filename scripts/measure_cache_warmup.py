#!/usr/bin/env python3
"""Measure what warming the RIGHT variant scope at take-control is worth.

The unified graph cache is keyed per variant (`unified_<tree>_<team>_<scope>`).
Take-control used to warm `__base__` only, so the first run under a variant found
nothing and rebuilt the hierarchy mid-run — the host's own DB fetch plus the graph
build, not just a lookup (BUG-0202).

This measures that rebuild directly: the same scoped load, cold and warm. The cold
number is what a run pays today; the warm number is what it pays once take-control
warms the scope on screen. Run it **on a host** — it calls the same TreeManager the
run path calls, so nothing is simulated.

    cd /opt/virtualpytest
    sudo -u <service-user> venv/bin/python scripts/measure_cache_warmup.py \
        --userinterface example_tv --team <team-id> --variant base_5.30

No DB writes and no device needed — but `clear_unified_cache()` drops EVERY tree's
cached graph on that host, not just the one under test, so any run in flight will
rebuild its own. Run it on an idle host.

Measured on a lab host (14-tree hierarchy, DB on the same LAN): cold 0.078s, warm
0.010s — a 0.068s gain. The cold figure is ~10 serialized DB round trips, so it
scales with hierarchy size and DB latency; a 36-tree interface on a loaded remote
database is where this is worth measuring, and this script is how.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.getcwd())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--userinterface', required=True, help="e.g. example_tv")
    ap.add_argument('--team', required=True, help='team_id (uuid)')
    ap.add_argument('--variant', required=True, help='variant name, e.g. base_5.30')
    ap.add_argument('--repeat', type=int, default=3, help='cold/warm pairs to average')
    args = ap.parse_args()

    from backend_host.src.services.navigation.navigation_executor_tree_manager import (
        load_navigation_tree,
    )
    from shared.src.lib.utils.navigation_cache import clear_unified_cache

    def timed_load() -> tuple[float, bool]:
        started = time.time()
        result = load_navigation_tree(
            args.userinterface, args.team, variant_name=args.variant
        )
        elapsed = time.time() - started
        return elapsed, bool(result.get('success'))

    # One throwaway load so import cost and any per-process memo are not charged
    # to the first measured sample.
    warmup_elapsed, ok = timed_load()
    if not ok:
        print('FAILED: could not load the tree at all — check the interface name, '
              'team id and variant. Nothing below would be meaningful.')
        return 1
    print(f'(priming load: {warmup_elapsed:.3f}s)\n')

    cold, warm = [], []
    for i in range(1, args.repeat + 1):
        clear_unified_cache()
        c, _ = timed_load()          # cold: the rebuild a run pays today
        w, _ = timed_load()          # warm: what it pays once the scope is warmed
        cold.append(c)
        warm.append(w)
        print(f'  run {i}: cold {c:.3f}s   warm {w:.3f}s')

    avg_cold = sum(cold) / len(cold)
    avg_warm = sum(warm) / len(warm)
    print()
    print(f'run pays today (cold, wrong scope warmed) : {avg_cold:.3f}s')
    print(f'run pays after the fix (scope warmed)     : {avg_warm:.3f}s')
    print(f'GAIN on the first run in this scope       : {avg_cold - avg_warm:.3f}s')
    print()
    print('Caveats worth stating with the number:')
    print(' * measured on THIS host against THIS database — a remote or loaded DB')
    print('   moves the cold figure a lot (it is ~10 serialized round trips).')
    print(' * the gain is once per scope per host process, not per run.')
    print(' * take-control already fetched the hierarchy server-side either way;')
    print('   what the fix removes is the host redoing it for the right scope.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
