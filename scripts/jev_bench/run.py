"""CLI for the Jev benchmark: B1 (2048) and B2 (Tetris) on the same seeded games per arm.

    python3 scripts/jev_bench/run.py --bench all --arms baseline,jev,llm --out /tmp/jev_bench/x

Runs on the server: AI arms call the providers in-process (``gateway.use_local_routing``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from scripts.jev_bench import b1_2048, b2_tetris  # noqa: E402
from scripts.jev_bench.common import ARMS, CostGuard, build_results_table, make_decide, write_jsonl  # noqa: E402

DEFAULT_TEAM = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"


def _play(bench: str, arm: str, seed: int, limit: int, team_id: str, guard: CostGuard, out_dir: str,
          decisions: list) -> dict:
    run_game = b1_2048.run_game if bench == "b1" else b2_tetris.run_game

    def on_decision(step, ctx, record):
        row = {"bench": bench, "arm": arm, "seed": seed, "step": step, "state": ctx["payload"]["state"],
               "options": ctx["payload"]["options"], "baseline_choice": record["baseline_choice"],
               "choice": record["choice"], "valid": record["valid"], "played": record["played"],
               "confidence": record["confidence"], "cost": record["cost"], "ms": record["ms"],
               "tokens_in": record["tokens_in"], "tokens_out": record["tokens_out"], "error": record["error"]}
        write_jsonl(os.path.join(out_dir, f"{bench}_{arm}.jsonl"), row)
        decisions.append(row)

    game = {"bench": bench, "arm": arm, "seed": seed,
            **run_game(seed, limit, make_decide(arm, team_id, guard), on_decision)}
    write_jsonl(os.path.join(out_dir, f"{bench}_games.jsonl"), game)
    return game


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Jev benchmark runner")
    ap.add_argument("--bench", default="all", choices=("b1", "b2", "all"))
    ap.add_argument("--arms", default="baseline,jev,llm")
    ap.add_argument("--seeds", type=int, default=None, help="games per arm (default 20 for b1, 10 for b2)")
    ap.add_argument("--max-moves", type=int, default=300, help="b1 moves per game")
    ap.add_argument("--max-pieces", type=int, default=200, help="b2 pieces per game")
    ap.add_argument("--max-cost", type=float, default=4.0, help="USD per AI arm")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--team-id", default=DEFAULT_TEAM)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in arms if a not in ARMS]
    if unknown:
        ap.error(f"unknown arms: {unknown}")
    if any(a != "baseline" for a in arms):
        from shared.src.lib.ai import gateway
        gateway.use_local_routing()

    out_dir = args.out or os.path.join(
        "/tmp/jev_bench", dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    os.makedirs(out_dir, exist_ok=True)
    b1, b2 = ("b1", 20, args.max_moves), ("b2", 10, args.max_pieces)
    benches = {"b1": [b1], "b2": [b2], "all": [b1, b2]}[args.bench]

    guard, decisions = CostGuard(args.max_cost), []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = []
        for bench, default_seeds, limit in benches:
            for suffix in [f"{arm}.jsonl" for arm in arms] + ["games.jsonl"]:
                open(os.path.join(out_dir, f"{bench}_{suffix}"), "w").close()
            for arm in arms:
                for seed in range(args.seeds if args.seeds is not None else default_seeds):
                    futures.append(pool.submit(_play, bench, arm, seed, limit, args.team_id, guard,
                                               out_dir, decisions))
        games = [f.result() for f in futures]

    table = build_results_table(games, decisions)
    with open(os.path.join(out_dir, "results.md"), "w", encoding="utf-8") as fh:
        fh.write(table)
    print(table)
    print(f"Written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
