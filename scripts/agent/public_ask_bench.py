#!/usr/bin/env python3
"""public_ask_bench.py — latency + answer check for the website widget endpoint (POST /server/public/ask).

Cases: tests/benchmarks/public_ask_cases.jsonl (kind = faq | docs | offtopic). Reports, per path (FAQ hit,
cached, model answer, off-topic decline), the count and p50/p90/max wall time as the visitor sees it, the
model-call count the server reports, the FAQ hit rate on the `faq` cases, and a per-case check (answer
contains one of `expect_any`; an off-topic case must come back without sources).

The endpoint allows 10 questions a minute and 100 a day per IP and each model answer costs the shared
daily budget (500), so the run sleeps between questions and the whole file is only 27 questions. Point it
at a local or lab server when you can; prod only for the before/after pair.

    python3 scripts/agent/public_ask_bench.py --url https://api.virtualpytest.com --label after --out /tmp/after.json
    python3 scripts/agent/public_ask_bench.py --only docs,offtopic --label before
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import requests

CASES = Path(__file__).resolve().parents[2] / "tests" / "benchmarks" / "public_ask_cases.jsonl"


def pct(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


def run_case(url: str, origin: str, case: dict, timeout: float) -> dict:
    started = time.time()
    try:
        r = requests.post(url.rstrip("/") + "/server/public/ask",
                          json={"question": case["question"], "language": case.get("lang", "en")},
                          headers={"Origin": origin}, timeout=timeout)
        body = r.json()
    except Exception as exc:  # noqa: BLE001
        return {"id": case["id"], "kind": case["kind"], "seconds": time.time() - started, "path": "error", "ok": False, "error": str(exc)[:120]}
    seconds = time.time() - started
    answer = body.get("answer", "") or ""
    sources = body.get("sources", []) or []
    if not body.get("success"):
        path = "error"
    elif body.get("faq"):
        path = "faq"
    elif body.get("cached"):
        path = "cached"
    elif not sources:
        path = "decline"
    else:
        path = "partial" if body.get("partial") else "model"
    if case["kind"] == "offtopic":
        ok = path in ("decline", "faq") and not sources
    else:
        expect = case.get("expect_any") or []
        ok = path != "error" and (not expect or any(e.lower() in answer.lower() for e in expect))
    return {"id": case["id"], "kind": case["kind"], "question": case["question"], "seconds": round(seconds, 3),
            "path": path, "ok": ok, "model_calls": body.get("model_calls", 0), "sources": sources,
            "answer": answer, "status": r.status_code}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://api.virtualpytest.com")
    ap.add_argument("--origin", default="https://virtualpytest.com")
    ap.add_argument("--label", default="run")
    ap.add_argument("--only", default="", help="comma list of kinds (faq,docs,offtopic)")
    ap.add_argument("--sleep", type=float, default=6.5, help="seconds between questions (rate limit is 10/min)")
    ap.add_argument("--timeout", type=float, default=90)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    kinds = {k for k in args.only.split(",") if k}
    cases = [json.loads(l) for l in CASES.read_text(encoding="utf-8").splitlines() if l.strip()]
    cases = [c for c in cases if not kinds or c["kind"] in kinds]
    results = []
    for i, case in enumerate(cases):
        res = run_case(args.url, args.origin, case, args.timeout)
        results.append(res)
        print(f"[{i + 1}/{len(cases)}] {res['id']:<14} {res['path']:<8} {res['seconds']:>7.2f}s calls={res.get('model_calls', '-')} {'ok' if res['ok'] else 'CHECK'}", flush=True)
        if i + 1 < len(cases):
            time.sleep(args.sleep)

    print(f"\n== {args.label}: {len(results)} questions against {args.url}")
    for path in ("faq", "cached", "model", "partial", "decline", "error"):
        secs = [r["seconds"] for r in results if r["path"] == path]
        if secs:
            calls = [r.get("model_calls", 0) for r in results if r["path"] == path]
            print(f"  {path:<8} n={len(secs):<3} p50={statistics.median(secs):6.2f}s p90={pct(secs, 90):6.2f}s max={max(secs):6.2f}s model_calls avg={sum(calls) / len(calls):.1f}")
    faq_cases = [r for r in results if r["kind"] == "faq"]
    if faq_cases:
        hits = sum(1 for r in faq_cases if r["path"] == "faq")
        print(f"  FAQ hit rate on faq cases: {hits}/{len(faq_cases)}")
    print(f"  checks passed: {sum(1 for r in results if r['ok'])}/{len(results)}")
    if args.out:
        Path(args.out).write_text(json.dumps({"label": args.label, "url": args.url, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
