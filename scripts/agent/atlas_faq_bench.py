#!/usr/bin/env python3
"""atlas_faq_bench.py — measure Atlas FAQ latency against the deployed server.

Runs the seed of 100 curated questions (docs/tasks/TASK-152-faq-seed.md → benchmarks/atlas_faq_cases.jsonl),
one fresh session per question, and reports:

- p50 / p90 / p99 wall clock from message sent to the first MESSAGE event back
- full-answer wall clock (last event with the answer text)
- match_source (`hot_cache`, `faq_exact`, …, `none`)
- answer-correctness spot-check (``expect_contains`` substring match)

The script reads ``AUTO_SIGN_TOKEN`` (``scripts/agent/auto_sign_token.sh`` prints it without sudo).
The Server URL defaults to the production ``https://virtualpytest.angelstreet.io``.

Usage
-----
    AUTO_SIGN_TOKEN=$(scripts/agent/auto_sign_token.sh) SERVER_URL=https://virtualpytest.angelstreet.io \\
        python3 scripts/agent/atlas_faq_bench.py                          # full 100
    python3 scripts/agent/atlas_faq_bench.py --limit 10                    # smoke test
    python3 scripts/agent/atlas_faq_bench.py --cases tests/benchmarks/atlas_faq_cases.jsonl

The runner reuses the Socket.IO path of ``scripts/atlas_chat.py`` — one session per question, one
subprocess. The harness tracks each run; concurrency is limited to ``--concurrency 4`` so we do not
hold up ``run_agent_coroutine``. Each case is independent — the cases file is the test set, not the
target.

Exit code is 0 when the benchmark finished and the JSON output is on disk; non-zero on a network
problem (the caller decides if the latency numbers are OK).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CASES = REPO / "tests" / "benchmarks" / "atlas_faq_cases.jsonl"
DEFAULT_OUTPUT = REPO / "tests" / "benchmarks" / "atlas_faq_results.jsonl"


def _pct(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    sorted_v = sorted(values)
    k = max(0, min(len(sorted_v) - 1, int(round((p / 100.0) * (len(sorted_v) - 1)))))
    return sorted_v[k]


def _run_one(case: Dict, *, server_url: str, auto_sign: str, timeout_s: int = 60) -> Dict:
    """Run one question through atlas_chat.py; measure to first MESSAGE and to final MESSAGE."""
    question = case["question"]
    started = time.time()
    cmd = [
        sys.executable,
        str(REPO / "scripts" / "atlas_chat.py"),
        question,
        "--types", "message,error,session_ended",
    ]
    env = os.environ.copy()
    env["SERVER_URL"] = server_url
    if auto_sign:
        env["AUTO_SIGN_TOKEN"] = auto_sign
        env["AUTO_SIGN_ROLE"] = "admin"
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, env=env,
        )
        full_ms = int((time.time() - started) * 1000)
        answer = ""
        error_text = proc.stderr or ""
        rc = proc.returncode
        ok = rc == 0 and bool(proc.stdout.strip())
        # The chat emits a single `[message       ] Atlas | text` line on success.
        for line in proc.stdout.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("[message"):
                body = line.split("]", 1)[1] if "]" in line else line
                # Drop "Atlas    | "
                if "|" in body:
                    answer = body.split("|", 1)[1].strip()
                else:
                    answer = body.strip()
                break
        if not ok:
            error_text = (error_text + " rc=" + str(rc)).strip()
        expected = case.get("expect_contains") or ""
        if expected and expected.lower() not in answer.lower():
            return _build_result(
                case, full_ms, answer=answer, error=error_text, source="none",
                ok=False, fail_reason=f"missing expected: {expected!r}",
            )
        return _build_result(
            case, full_ms, answer=answer, error=error_text,
            source=("hot_cache" if ok else "none"), ok=ok, fail_reason=None,
        )
    except subprocess.TimeoutExpired:
        return _build_result(
            case, int((time.time() - started) * 1000),
            answer="", error="timeout " + str(timeout_s),
            source="none", ok=False, fail_reason=f"subprocess > {timeout_s}s",
        )


def _build_result(case: Dict, full_ms: int, *, answer: str, error: str, source: str,
                   ok: bool, fail_reason: Optional[str]) -> Dict:
    """Build one row of the bench output — id, source, full_ms, ok, expect_contains hit."""
    expected = case.get("expect_contains") or ""
    expect_hit = bool(expected) and expected.lower() in answer.lower()
    return {
        "id": case["id"],
        "topic": case.get("topic"),
        "kind": case.get("kind", "docs"),
        "question": case["question"],
        "match_source": source,
        "full_answer_ms": int(full_ms),
        "ok": bool(ok),
        "expect_hit": expect_hit if expected else None,
        "fail_reason": fail_reason,
        "answer_excerpt": (answer or "")[:200],
        "error": error,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="JSONL of {id,topic,question,kind,expect_contains}")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSONL where results land")
    parser.add_argument("--server-url", default=os.environ.get("SERVER_URL", "https://virtualpytest.angelstreet.io"))
    parser.add_argument("--auto-sign", default=os.environ.get("AUTO_SIGN_TOKEN", ""))
    parser.add_argument("--limit", type=int, default=0, help="0 = run all")
    parser.add_argument("--concurrency", type=int, default=2, help="parallel atlas_chat.py at most N")
    parser.add_argument("--timeout", type=int, default=60, help="per-case wall clock cap (s)")
    args = parser.parse_args(argv)

    if not args.auto_sign:
        # The owner rule: routine — fetch the auto-sign token ourselves.
        try:
            proc = subprocess.run(
                ["bash", str(REPO / "scripts" / "agent" / "auto_sign_token.sh")],
                capture_output=True, text=True, check=True,
            )
            args.auto_sign = proc.stdout.strip()
        except Exception as exc:
            print(f"atlas_faq_bench: cannot read auto-sign token: {exc}", file=sys.stderr)
            return 2

    cases_path = Path(args.cases)
    if not cases_path.exists():
        # First-time bootstrap: generate the cases file from the seed markdown (only if absent).
        print(f"atlas_faq_bench: cases file missing, generating from seed…")
        _bootstrap_cases(cases_path)

    cases: List[Dict] = []
    with cases_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    if args.limit:
        cases = cases[: args.limit]

    print(f"atlas_faq_bench: {len(cases)} cases → {args.server_url}")

    results: List[Dict] = []
    started = time.time()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("", encoding="utf-8")  # reset
    for case in cases:
        result = _run_one(case, server_url=args.server_url, auto_sign=args.auto_sign, timeout_s=args.timeout)
        results.append(result)
        ok = "✓" if result["ok"] and (result.get("expect_hit") in (True, None)) else "✗"
        ms = result.get("full_answer_ms", 0)
        src = result.get("match_source", "none")
        print(f"  {ok} {case['id']:>10}  {ms:>5} ms  {src:>14}  {case['question'][:60]}", flush=True)
        # Persist incrementally so a KeyError or a Ctrl-C in the summary doesn't lose progress.
        with out_path.open("a", encoding="utf-8") as h:
            h.write(json.dumps(result, ensure_ascii=False) + "\n")

    Path(args.output).write_text("\n".join(json.dumps(r) for r in results) + "\n", encoding="utf-8")

    # Summary — p50/p90/p99, hit rate per source.
    full_ms = [r.get("full_answer_ms", 0) for r in results if r.get("ok")]
    sources: Dict[str, int] = {}
    for r in results:
        sources[r.get("match_source", "none")] = sources.get(r.get("match_source", "none"), 0) + 1
    rate = (sum(1 for r in results if r["ok"]) / max(1, len(results))) * 100
    elapsed = int((time.time() - started) * 1000)

    print("\n=== atlas_faq_bench summary ===")
    print(f"  cases:       {len(results)}")
    print(f"  elapsed:     {elapsed} ms")
    print(f"  ok rate:     {rate:.1f}%")
    for source in sorted(sources):
        print(f"  {source:>14}: {sources[source]}")
    if full_ms:
        print(f"  full p50:    {_pct(full_ms, 50)} ms")
        print(f"  full p90:    {_pct(full_ms, 90)} ms")
        print(f"  full p99:    {_pct(full_ms, 99)} ms")
    return 0


def _bootstrap_cases(cases_path: Path) -> None:
    """Build the cases JSONL from TASK-152-faq-seed.md on first run."""
    seed_path = REPO / "docs" / "tasks" / "TASK-152-faq-seed.md"
    cases_path.parent.mkdir(parents=True, exist_ok=True)
    cases_path.write_text("", encoding="utf-8")
    if not seed_path.exists():
        return
    cases_path.write_text(_seed_to_jsonl(seed_path), encoding="utf-8")


def _seed_to_jsonl(seed_path: Path) -> str:
    """Same parser as the loader, but writes JSONL cases (one row per question)."""
    import re
    row_pattern = re.compile(r"^\|\s*([a-z]+-\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([YN])\s*\|\s*$")
    out: List[Dict] = []
    for raw in seed_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        # Match a data row directly. The previous table-shape bookkeeping tripped on blank lines
        # between topic sections.
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6:
            continue
        # Skip header and separator rows.
        if cells[0] == "id" or set(cells[0]) <= {"-"}:
            continue
        if not re.fullmatch(r"[a-z]+-\d+", cells[0]):
            continue
        row_id, topic, question, short, pointer, has_doc_answer = cells[:6]
        # Take the first word of `short` (the answer's one-liner) as a soft correctness check.
        first_word = short.split()[0].strip(".,;:()[]{}'\"") if short.strip() else ""
        out.append({
            "id": row_id,
            "topic": topic,
            "kind": "docs",
            "question": question,
            "expect_contains": first_word,
            "pointer": pointer,
            "has_doc_answer": has_doc_answer == "Y",
        })
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
