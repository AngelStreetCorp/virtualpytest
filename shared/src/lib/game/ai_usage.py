"""
AI usage of one game run, for the report and the run log.

Every model call a game makes goes through ``AiUsage.record``: it keeps one row per step (provider/model,
tokens in/out, round-trip ms) and prints one log line. ``summary_lines`` renders the block for the report
(execution summary): total tokens in/out, cache read, cost when known, then one line per step.
A game that never calls a model says ``AI: none``. The numbers come from the router result (the same ones
``call_log`` stores per billed call); this module keeps no second tracker of spend.

Accepts both result shapes: ``gateway.complete`` (usage.prompt_tokens / completion_tokens / cache_read_tokens,
``provider_used``, ``fallback_used``) and ``decisions.choose`` (usage.input_tokens / output_tokens, ``ms``).
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

MAX_STEP_LINES = 40  # per-step lines in the summary; the log and metadata hold every step


class AiUsage:
    def __init__(self, game: str):
        self.game = game
        self.steps: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, step: str, out: Optional[dict], ms: Optional[int] = None) -> Dict[str, Any]:
        """Add one model call (``out`` is the router result, ``ms`` the measured round trip if the result has none)."""
        out = out or {}
        u = out.get("usage") or {}
        row = {
            "step": step,
            "provider": out.get("provider_used") or out.get("endpoint") or "",
            "model": out.get("model") or "",
            "fallback": bool(out.get("fallback_used")),
            "ok": bool(out.get("success")),
            "tokens_in": int(u.get("prompt_tokens", u.get("input_tokens", 0)) or 0),
            "tokens_out": int(u.get("completion_tokens", u.get("output_tokens", 0)) or 0),
            "cache_read": int(u.get("cache_read_tokens", 0) or 0),
            "cost": out.get("cost"),
            "ms": int(out.get("ms") or ms or 0),
        }
        with self._lock:
            row["n"] = len(self.steps) + 1
            self.steps.append(row)
        print(self.log_line(row), flush=True)
        return row

    def log_line(self, r: Dict[str, Any]) -> str:
        who = "/".join(x for x in (r["provider"], r["model"]) if x) or "?"
        cost = f" cost ${r['cost']:.5f}" if isinstance(r.get("cost"), (int, float)) else ""
        cache = f" cache {r['cache_read']}" if r["cache_read"] else ""
        return (f"[{self.game}] AI #{r['n']} {r['step']}: {who}{' (fallback)' if r['fallback'] else ''} "
                f"in {r['tokens_in']} out {r['tokens_out']}{cache} {r['ms']} ms{cost}{'' if r['ok'] else ' FAILED'}")

    def totals(self) -> Dict[str, Any]:
        with self._lock:
            rows = list(self.steps)
        costs = [r["cost"] for r in rows if isinstance(r.get("cost"), (int, float))]
        return {
            "calls": len(rows), "failed": sum(1 for r in rows if not r["ok"]),
            "fallbacks": sum(1 for r in rows if r["fallback"]),
            "models": sorted({"/".join(x for x in (r["provider"], r["model"]) if x) for r in rows} - {""}),
            "tokens_in": sum(r["tokens_in"] for r in rows), "tokens_out": sum(r["tokens_out"] for r in rows),
            "cache_read": sum(r["cache_read"] for r in rows),
            "cost": round(sum(costs), 6) if costs else None,
            "ms_avg": int(sum(r["ms"] for r in rows) / len(rows)) if rows else 0,
        }

    def metadata(self) -> Dict[str, Any]:
        return {**self.totals(), "steps": list(self.steps)}

    def summary_lines(self) -> List[str]:
        t = self.totals()
        if not t["calls"]:
            return ["AI: none"]
        failed = f", {t['failed']} failed" if t["failed"] else ""
        fb = f", {t['fallbacks']} on fallback" if t["fallbacks"] else ""
        cache = f" / cache read {t['cache_read']}" if t["cache_read"] else ""
        cost = f", cost ${t['cost']:.4f}" if t["cost"] is not None else ""
        head = (f"AI: {', '.join(t['models']) or '?'} - {t['calls']} calls{failed}{fb}; "
                f"tokens in {t['tokens_in']} / out {t['tokens_out']}{cache}{cost}; avg {t['ms_avg']} ms")
        lines = [head]
        rows = self.steps
        for r in rows[:MAX_STEP_LINES]:
            lines.append("  " + self.log_line(r).split("] ", 1)[1])
        if len(rows) > MAX_STEP_LINES:
            lines.append(f"  ... {len(rows) - MAX_STEP_LINES} more steps (all in the run log)")
        return lines

    def summary(self) -> str:
        return "\n".join(self.summary_lines())
