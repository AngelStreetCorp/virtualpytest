"""Shared helpers for the Jev benchmark runner: arms, JSONL logging, cost guard, results table.

An arm takes a decision context ``ctx`` (payload, legal ids, baseline choice, llm prompt/system/parser,
team id) and returns a record with the chosen option id. The AI arms import the AI modules lazily so
the baseline path and the tests work without them configured.
"""

from __future__ import annotations

import json
import statistics
import threading
import time
from typing import Any, Callable, Dict, List, Tuple

Record = Dict[str, Any]
Ctx = Dict[str, Any]
Decide = Callable[[Ctx], Record]

_write_lock = threading.Lock()

# Per bench: the two game-summary fields shown as "score" and "extra" in the results table.
BENCH_KEYS = {"b1": ("score", "max_tile"), "b2": ("rows", "pieces")}


class CostGuard:
    """Thread-safe running cost per arm; an arm is over budget once its total reaches the limit."""

    def __init__(self, limit_usd: float) -> None:
        self.limit_usd = limit_usd
        self.totals: Dict[str, float] = {}
        self._lock = threading.Lock()

    def over(self, arm: str) -> bool:
        with self._lock:
            return self.totals.get(arm, 0.0) >= self.limit_usd

    def record(self, arm: str, cost: float) -> None:
        with self._lock:
            self.totals[arm] = self.totals.get(arm, 0.0) + cost


def write_jsonl(path: str, record: Dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with _write_lock, open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


def _record(choice: Any, **extra: Any) -> Record:
    rec = {"choice": choice, "confidence": None, "cost": 0.0, "ms": 0, "tokens_in": 0,
           "tokens_out": 0, "error": ""}
    rec.update(extra)
    return rec


# --------------------------------------------------------------------------- arms
def baseline_arm(ctx: Ctx) -> Record:
    return _record(ctx["baseline_choice"])


def jev_arm(ctx: Ctx) -> Record:
    from shared.src.lib.ai import decisions, router

    resolution = router.resolve_profile("jev", "text.decision", ctx["team_id"])
    payload = ctx["payload"]
    out = decisions.choose(resolution, payload["state"], payload["options"],
                           instructions=payload["instructions"], log=False)
    usage = out.get("usage") or {}
    return _record(out.get("choice"), confidence=out.get("confidence"),
                   cost=float(out.get("cost") or 0.0), ms=int(out.get("ms") or 0),
                   tokens_in=int(usage.get("input_tokens") or 0),
                   tokens_out=int(usage.get("output_tokens") or 0), error=out.get("error") or "")


def llm_arm(ctx: Ctx) -> Record:
    from shared.src.lib.ai import gateway

    started = time.monotonic()
    out = gateway.complete("text", ctx["prompt"], system=ctx["system"], max_tokens=300,
                           temperature=0.0, team_id=ctx["team_id"])
    ms = int((time.monotonic() - started) * 1000)
    usage = out.get("usage") or {}
    tokens_in, tokens_out = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    cost = out.get("cost")
    if cost is None:  # gpt-4.1-mini rates
        cost = tokens_in * 0.4e-6 + tokens_out * 1.6e-6
    choice = ctx["parser"](out.get("content") or "") if out.get("success") else None
    return _record(choice, cost=float(cost), ms=ms, tokens_in=tokens_in, tokens_out=tokens_out,
                   error=out.get("error") or "")


ARMS: Dict[str, Decide] = {"baseline": baseline_arm, "jev": jev_arm, "llm": llm_arm}


def make_decide(arm: str, team_id: str, guard: CostGuard) -> Decide:
    """Wrap an arm: stop (``aborted``) once the arm is over budget, else record its cost."""
    def decide(ctx: Ctx) -> Record:
        if arm != "baseline" and guard.over(arm):
            return _record(None, aborted=True, error="aborted: cost limit")
        rec = ARMS[arm]({**ctx, "team_id": team_id})
        guard.record(arm, rec["cost"])
        return rec
    return decide


# --------------------------------------------------------------------------- results
def _percentile(values: List[int], pct: float) -> int:
    ordered = sorted(values)
    return ordered[int(round(pct / 100.0 * (len(ordered) - 1)))] if ordered else 0


def build_results_table(games: List[Record], decisions: List[Record]) -> str:
    """Markdown table per bench x arm. Baseline has no validity/agreement/cost/latency."""
    games_by: Dict[Tuple[str, str], List[Record]] = {}
    decisions_by: Dict[Tuple[str, str], List[Record]] = {}
    for g in games:
        games_by.setdefault((g["bench"], g["arm"]), []).append(g)
    for d in decisions:
        decisions_by.setdefault((d["bench"], d["arm"]), []).append(d)

    lines = ["# Jev benchmark results", ""]
    for bench in sorted({b for b, _ in games_by}):
        a, b = BENCH_KEYS[bench]
        header = ["arm", "games", f"{a} mean", f"{a} median", f"{b} mean", f"{b} median", "validity %",
                  "agreement %", "cost $", "cost/decision $", "latency p50 ms", "latency p95 ms"]
        lines += [f"## {bench}", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        for arm in sorted(a for b, a in games_by if b == bench):
            gs, ds = games_by[(bench, arm)], decisions_by.get((bench, arm), [])
            scores, extras = [g[a] for g in gs], [g[b] for g in gs]
            cells = [arm, str(len(gs)), f"{statistics.mean(scores):.1f}", f"{statistics.median(scores):.1f}",
                     f"{statistics.mean(extras):.1f}", f"{statistics.median(extras):.1f}"]
            if arm == "baseline" or not ds:
                cells += ["-"] * 6
            else:
                valid = [d for d in ds if d["valid"]]
                agree = [d for d in valid if d["choice"] == d["baseline_choice"]]
                total = sum(d["cost"] for d in ds)
                lat = [d["ms"] for d in ds]
                cells += [f"{100.0 * len(valid) / len(ds):.1f}", f"{100.0 * len(agree) / len(ds):.1f}",
                          f"{total:.4f}", f"{total / len(ds):.5f}", str(_percentile(lat, 50)),
                          str(_percentile(lat, 95))]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)
