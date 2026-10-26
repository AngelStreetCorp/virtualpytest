#!/usr/bin/env python3
"""Log a headless Claude Code run (``claude -p --output-format json``) in ai_calls (BUG-0721).

    python3 scripts/ai_report_claude_cli.py <result.json> --script promo/run_builder.sh

One row per model in the result's ``modelUsage`` (tokens, cache read / write, the CLI's cost), usage
``external:claude_cli``, endpoint ``anthropic`` (the owner's key), origin ``script``. Never fails the caller: a
report error is printed and the exit code stays 0.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.src.lib.ai import gateway  # noqa: E402
from shared.src.lib.ai.provider_client import CallUsage  # noqa: E402


def report(result: dict, script: str) -> int:
    rows = 0
    ok = not result.get("is_error") and result.get("subtype", "success") == "success"
    ms = int(result.get("duration_api_ms") or result.get("duration_ms") or 0)
    for model, u in (result.get("modelUsage") or {}).items():
        cache_read, cache_write = int(u.get("cacheReadInputTokens") or 0), int(u.get("cacheCreationInputTokens") or 0)
        cost = u.get("costUSD")
        used = CallUsage(tokens_in=int(u.get("inputTokens") or 0) + cache_read + cache_write,
                         tokens_out=int(u.get("outputTokens") or 0), cache_read=cache_read, cache_write=cache_write,
                         web_searches=int(u.get("webSearchRequests") or 0),
                         cost=float(cost) if isinstance(cost, (int, float)) and cost > 0 else None)
        gateway.report_external_call("external:claude_cli", endpoint="anthropic", model=model, call_usage=used, ok=ok,
                                     ms=ms, script=script, error_type=None if ok else "other")
        rows += 1
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("result")
    parser.add_argument("--script", required=True)
    args = parser.parse_args()
    try:
        n = report(json.load(open(args.result)), args.script)
        print(f"ai_calls: {n} row(s) reported for {args.script}")
    except Exception as e:  # noqa: BLE001
        print(f"ai_calls report failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
