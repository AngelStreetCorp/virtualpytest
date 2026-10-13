#!/usr/bin/env python3
"""
run_smoke — Layer 1 Atlas smoke wrapper around scripts/atlas_chat.py.

Contract (TASK-73 §5):
  * takes one free-text prompt,
  * asserts a non-empty reply,
  * asserts >= 1 tool call,
  * runs in < 60 s,
  * exits 0 on pass, 1 on assertion failure,
  * prints the prompt, the reply, and the list of tools called to stdout.

The wrapper is a *contract*; scripts/atlas_chat.py is the engine. The
parser (parse_events.py) is unit-tested so the smoke itself does not have
to wait for a real Atlas session to validate its assertion logic.

USAGE
    python3 scripts/ai-smoke/run_smoke.py [PROMPT] [options]

    PROMPT defaults to "List the available devices." (forces >= 1 tool
    call without needing a device context).

OPTIONS
    --server URL        Backend URL (default: env SERVER_URL or
                        https://virtualpytest.angelstreet.io). Forwarded
                        to atlas_chat.py.
    --auto-sign TOKEN   AUTO_SIGN_TOKEN (default: env AUTO_SIGN_TOKEN).
                        CI sets it as a secret; locally, copy from
                        backend_server/.env.
    --team-id UUID      Team UUID (default: env TEAM_ID or the well-known
                        smoke team). Forwarded to atlas_chat.py.
    --timeout SECONDS   Hard timeout for atlas_chat.py (default: 55 — 5 s
                        under the 60 s smoke budget for this wrapper's
                        own startup + teardown + print).
    --json              Emit the parsed SmokeResult as one JSON line on
                        stdout (for CI to ingest). Default: human-readable.

EXIT CODES
    0  smoke passed (reply non-empty, >= 1 tool call, no error events)
    1  smoke failed (assertion: see "FAIL: <reason>" on stderr)
    2  atlas_chat.py errored before SESSION_END (connection refused, 401,
       timeout, etc.)
    3  the device is locked by another session (n/a for the smoke — we
       do not pass --host/--device; preserved for atlas_chat.py parity)

NO SECRETS
    The smoke reads AUTO_SIGN_TOKEN and API_KEY from the environment only.
    It does not read .env, does not embed tokens, and does not log the
    auth header. The auto_sign is forwarded to atlas_chat.py via argv
    (which atlas_chat.py redacts from its own error output).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Local parser — kept in scripts/ai-smoke/ next to this wrapper.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_events import SmokeResult, parse_event_stream  # noqa: E402


# Default free-text prompt (Q1: free-text only, no structured case). The
# question is intentionally simple so it (a) doesn't need a device
# context, (b) always exercises the tool router, and (c) keeps the smoke
# fast. The owner can pass any other prompt via argv; the smoke asserts
# >= 1 tool call regardless.
DEFAULT_PROMPT = "List the available devices."

# Default team — same one scripts/atlas_chat.py uses when no TEAM_ID env
# is set. Kept in sync by the docs/agent/validation/TESTING.md guide.
DEFAULT_TEAM = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"

# Default server. CI overrides via env; local dev usually points to
# http://localhost:5109.
DEFAULT_SERVER = "https://virtualpytest.angelstreet.io"

# Path to the engine, relative to repo root. Resolved at call time so the
# wrapper works from any CWD.
ATLAS_CHAT = Path(__file__).resolve().parent.parent / "atlas_chat.py"


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Layer 1 Atlas smoke — < 60 s, free-text, >= 1 tool call.",
    )
    ap.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT,
                    help=f"Free-text prompt (default: {DEFAULT_PROMPT!r})")
    ap.add_argument("--server", default=os.environ.get("SERVER_URL", DEFAULT_SERVER),
                    help=f"Backend URL (default: {DEFAULT_SERVER!r})")
    ap.add_argument("--auto-sign", default=os.environ.get("AUTO_SIGN_TOKEN"),
                    dest="auto_sign",
                    help="AUTO_SIGN_TOKEN (env AUTO_SIGN_TOKEN). "
                         "Required in CI; locally copy from backend_server/.env.")
    ap.add_argument("--team-id", default=os.environ.get("TEAM_ID", DEFAULT_TEAM),
                    dest="team_id",
                    help=f"Team UUID (default: {DEFAULT_TEAM[:8]}...)")
    ap.add_argument("--timeout", type=int, default=55,
                    help="Hard timeout in seconds (default: 55)")
    ap.add_argument("--json", action="store_true",
                    help="Emit one JSON line on stdout (parsed SmokeResult).")
    return ap


def _format_human(prompt: str, result: SmokeResult, elapsed: float) -> str:
    """Human-readable stdout — what the agent-browser and a human will read."""
    tools = ", ".join(result.tool_names) if result.tool_names else "(none)"
    status = "PASS" if result.ok else "FAIL"
    lines = [
        f"== Atlas smoke ({status}, {elapsed:.1f}s) ==",
        f"prompt  : {prompt}",
        f"reply   : {result.reply or '(empty)'}",
        f"tools   : {tools}  (count={result.tool_call_count})",
    ]
    if result.error_events:
        lines.append(f"errors  : {len(result.error_events)} (first: {result.error_events[0][:200]})")
    if result.parse_errors:
        lines.append(f"parse   : {len(result.parse_errors)} non-JSON line(s) ignored")
    return "\n".join(lines)


def _format_json(prompt: str, result: SmokeResult, elapsed: float, rc: int) -> str:
    return json.dumps({
        "ok": result.ok,
        "elapsed_seconds": round(elapsed, 2),
        "atlas_chat_rc": rc,
        "prompt": prompt,
        "reply": result.reply,
        "tool_names": result.tool_names,
        "tool_call_count": result.tool_call_count,
        "error_events": result.error_events,
        "parse_errors": result.parse_errors,
        "session_ended": result.session_ended,
        "why_not_ok": None if result.ok else result.why_not_ok(),
    }, default=str)


def main() -> int:
    args = _build_argparser().parse_args()

    # Hard guard: do not silently send a 401. If the smoke is run without
    # a token and the server is the public one, the run wastes 60 s and
    # exits 2 with a confusing message. Better to fail fast here.
    if args.server.startswith("https://") and not args.auto_sign:
        print("run_smoke: refusing to run against an https server without --auto-sign "
              "(would just 401). Set AUTO_SIGN_TOKEN or pass --server http://localhost:5109.",
              file=sys.stderr)
        return 2

    if not ATLAS_CHAT.exists():
        print(f"run_smoke: engine not found at {ATLAS_CHAT}", file=sys.stderr)
        return 2

    cmd = [
        sys.executable, str(ATLAS_CHAT),
        args.prompt,
        "--server", args.server,
        "--team-id", args.team_id,
        "--timeout", str(args.timeout),
        "--json",
    ]
    if args.auto_sign:
        cmd += ["--auto-sign", args.auto_sign]

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout + 5,  # 5 s grace over atlas_chat.py's own timeout
            check=False,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        print(f"run_smoke: atlas_chat.py exceeded {args.timeout + 5}s hard limit "
              f"(elapsed {elapsed:.1f}s). Treating as smoke failure.",
              file=sys.stderr)
        return 2
    elapsed = time.monotonic() - t0

    result = parse_event_stream(proc.stdout)

    # atlas_chat.py's own exit code takes precedence for non-assertion
    # failures: connection refused, 401, timeout from inside atlas_chat
    # (rc=2), device busy (rc=3). We surface those as rc=2 so the smoke
    # contract stays 0/1.
    if proc.returncode != 0 and result.ok:
        # atlas_chat.py errored but the parser still found a clean run
        # (e.g. the WARN line made it print a non-zero but we still got
        # SESSION_END). Trust the engine's exit code.
        print(f"run_smoke: atlas_chat.py exited {proc.returncode} but the event stream "
              f"looked clean; treating as engine error.", file=sys.stderr)
        return 2
    if proc.returncode == 2:
        # Connection/timeout from the engine. Print stderr tail to help.
        tail = "\n".join((proc.stderr or "").splitlines()[-10:])
        print(f"run_smoke: atlas_chat.py connection/timeout (rc=2):\n{tail}",
              file=sys.stderr)
        return 2

    if args.json:
        print(_format_json(args.prompt, result, elapsed, proc.returncode))
    else:
        print(_format_human(args.prompt, result, elapsed))

    if not result.ok:
        print(f"FAIL: {result.why_not_ok()}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
