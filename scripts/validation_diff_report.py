#!/usr/bin/env python3
"""
validation_diff_report.py — generate a before/after.md for two `validation` runs.

Usage:
    AUTO_SIGN_TOKEN=... python3 scripts/validation_diff_report.py \\
        <before_script_result_id> <after_script_result_id> \\
        [--server https://rpitest.angelstreet.io] \\
        [--team 7fdeb4bb-3639-4ec3-959f-b54769a219ce]

Pulls both rows via /server/script-results/getAllScriptResults, compares the
top-line metrics and links to each run's HTML/verification-review reports, and
writes `before_after_<after_id>.md`.

Per-step pass/fail reconciliation is best done from the host journal (logs in
`vpt-host.service` show "Step N failed" lines); the helper inlines those if a
`--journal-before` and `--journal-after` text file is provided.
"""
from __future__ import annotations
import argparse, json, os, re, ssl, sys, urllib.parse, urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = {"User-Agent": "validation-diff-report/1.0"}

DEFAULT_SERVER = os.environ.get("VALIDATION_DIFF_SERVER", "https://rpitest.angelstreet.io")
DEFAULT_TEAM   = os.environ.get("VALIDATION_DIFF_TEAM",   "7fdeb4bb-3639-4ec3-959f-b54769a219ce")
DEFAULT_TOKEN  = os.environ.get("AUTO_SIGN_TOKEN")


def http_get_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, context=CTX, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_results(server: str, team: str, token: str, limit: int = 200) -> list[dict]:
    qs = urllib.parse.urlencode({"team_id": team, "auto_signed": token, "limit": limit})
    return http_get_json(f"{server}/server/script-results/getAllScriptResults?{qs}")


STEP_LINE = re.compile(
    r"\bStep\s+(?P<n>\d+)\s+(?P<verb>failed|completed|passed)"
)
FAIL_DETAIL = re.compile(
    r"Step\s+(?P<n>\d+)\s+failed:\s+(?P<reason>.+)"
)
PLAN_LINE = re.compile(
    r"_create_reachability_based_validation_sequence\][^\n]*\bStep\s+(?P<n>\d+):\s+(?P<edge>[^()]+?)\s+\("
)


def parse_step_outcomes(journal_path: str) -> tuple[dict[int, str], dict[int, str], dict[int, str]]:
    """Extract {step: PASS|FAIL}, {step: failure_reason}, {step: edge_label} from a host journal file.

    Steps that appear in the planning sequence but never produce a failure marker
    are assumed PASS (the validation engine only logs failures explicitly).
    """
    outcomes: dict[int, str] = {}
    reasons: dict[int, str] = {}
    plan: dict[int, str] = {}
    if not journal_path:
        return outcomes, reasons, plan
    try:
        text = open(journal_path).read()
    except OSError:
        return outcomes, reasons, plan

    # First pass — capture the plan (step -> "src → dst")
    for line in text.splitlines():
        mp = PLAN_LINE.search(line)
        if mp:
            plan[int(mp.group("n"))] = mp.group("edge").strip()

    # Second pass — explicit fail/pass markers
    for line in text.splitlines():
        m = STEP_LINE.search(line)
        if not m:
            continue
        step = int(m.group("n"))
        verb = m.group("verb")
        if verb == "failed":
            outcomes[step] = "FAIL"
            mr = FAIL_DETAIL.search(line)
            if mr:
                reasons[step] = mr.group("reason").strip()[:300]
        elif verb in ("completed", "passed"):
            outcomes.setdefault(step, "PASS")

    # Infer PASS for planned-but-not-failed steps
    for step in plan:
        outcomes.setdefault(step, "PASS")
    return outcomes, reasons, plan


def review_url(row: dict) -> str:
    meta = row.get("metadata") or {}
    rev = meta.get("verification_review_r2_url")
    if rev:
        return rev
    return ((meta.get("verification_review") or {}).get("verification_review_url")) or "n/a"


def render_md(before: dict, after: dict,
              before_steps: dict[int, str], after_steps: dict[int, str],
              before_reasons: dict[int, str], after_reasons: dict[int, str],
              before_plan: dict[int, str], after_plan: dict[int, str]) -> str:
    out: list[str] = []
    out.append(f"# Validation diff — {before.get('id','?')[:8]} → {after.get('id','?')[:8]}\n")

    out.append("## Summary\n")
    out.append("| | before | after |")
    out.append("|---|---|---|")
    for label, key in [
        ("script_result_id", "id"),
        ("started_at", "started_at"),
        ("execution_time_ms", "execution_time_ms"),
        ("success", "success"),
        ("error_msg", "error_msg"),
    ]:
        out.append(f"| {label} | `{before.get(key,'')}` | `{after.get(key,'')}` |")

    # Named-variant the run was launched with (see docs/agent/ENHANCE_VARIANT.md).
    # Persisted by ScriptExecutor._build_start_metadata; absent on pre-Phase-1
    # runs and on base runs.
    def _variant_of(row: dict) -> str:
        meta = row.get("metadata") or {}
        v = meta.get("variant")
        return v if isinstance(v, str) and v else "(none)"
    before_variant = _variant_of(before)
    after_variant = _variant_of(after)
    out.append(f"| variant | `{before_variant}` | `{after_variant}` |")
    out.append("")

    # Cross-variant comparison warning (§3 polish in Phase 5). When the two runs
    # were launched with different variants, per-step plans may legitimately
    # diverge — e.g. one variant disables nodes the other enables — so flagging
    # apparent regressions/fixes can mislead the reader.
    if before_variant != after_variant:
        out.append(
            f"> ⚠️ **Comparing different variants** "
            f"(`{before_variant}` → `{after_variant}`). "
            f"Per-step plans may differ; treat the diff as informational, "
            f"not as a regression signal.\n"
        )

    if before_steps or after_steps:
        all_steps = sorted(set(before_steps) | set(after_steps))
        out.append("## Per-step diff\n")
        out.append("| step | edge | before | after | Δ | reason (after-FAIL only) |")
        out.append("|---|---|---|---|---|---|")
        flips_pf, regressions, unchanged_fail, unchanged_pass = 0, 0, 0, 0
        for s in all_steps:
            b = before_steps.get(s, "—")
            a = after_steps.get(s, "—")
            if b == "FAIL" and a == "PASS":
                delta = "✅ fixed"; flips_pf += 1
            elif b == "PASS" and a == "FAIL":
                delta = "❌ regressed"; regressions += 1
            elif b == "FAIL" and a == "FAIL":
                delta = "⏺ still fail"; unchanged_fail += 1
            elif b == "PASS" and a == "PASS":
                delta = "✓ pass"; unchanged_pass += 1
            else:
                delta = ""
            reason = after_reasons.get(s, "") if a == "FAIL" else ""
            edge = after_plan.get(s) or before_plan.get(s) or ""
            out.append(f"| {s} | {edge} | {b} | {a} | {delta} | {reason} |")
        out.append("")
        out.append(f"**Totals — fixed: {flips_pf}, regressed: {regressions}, "
                   f"still failing: {unchanged_fail}, still passing: {unchanged_pass}**\n")

    out.append("## Reports\n")
    for tag, row in (("before", before), ("after", after)):
        out.append(f"- {tag} HTML: {row.get('html_report_r2_url','n/a')}")
        out.append(f"- {tag} review.md: {review_url(row)}")
    return "\n".join(out) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("before_id")
    p.add_argument("after_id")
    p.add_argument("--server", default=DEFAULT_SERVER)
    p.add_argument("--team",   default=DEFAULT_TEAM)
    p.add_argument("--token",  default=DEFAULT_TOKEN)
    p.add_argument("--journal-before",
                   help="Path to a text file containing the host journal for the before-run")
    p.add_argument("--journal-after",
                   help="Path to a text file containing the host journal for the after-run")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    if not args.token:
        print("ERROR: AUTO_SIGN_TOKEN env var or --token required", file=sys.stderr)
        return 2

    rows = fetch_results(args.server, args.team, args.token, limit=400)
    by_id = {r.get("id"): r for r in (rows if isinstance(rows, list) else rows.get("script_results", []))}
    before = by_id.get(args.before_id)
    after  = by_id.get(args.after_id)
    if not before or not after:
        print(f"ERROR: could not find both ids in last 400 results "
              f"(before={'OK' if before else 'MISS'}, after={'OK' if after else 'MISS'})", file=sys.stderr)
        return 1

    bs, br, bp = parse_step_outcomes(args.journal_before)
    a_s, ar, ap = parse_step_outcomes(args.journal_after)

    md = render_md(before, after, bs, a_s, br, ar, bp, ap)
    out = args.out or f"before_after_{args.after_id}.md"
    with open(out, "w") as f:
        f.write(md)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
