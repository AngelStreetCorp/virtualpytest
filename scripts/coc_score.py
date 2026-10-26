#!/usr/bin/env python3
"""
Score the most-recent Clash of Clans run (TASK-81 §81.1.8).

Mirrors `scripts/<game>_score.py` patterns: a thin wrapper that reads the
last script's results row, parses the event log (saved next to the report),
and prints the GAME_BOTS §4 level-1 ``metric=`` line. Used by the
research loop and by hand to grade a run without trusting the assistant's
self-report.

Three ways to call it:

    # 1. From JSON the script wrote (default location -- on the Pi):
    scripts/coc_score.py

    # 2. From an explicit JSON file (when the script lives on a different host):
    scripts/coc_score.py /var/lib/vpt/coc_frames/<run_id>_events.json

    # 3. From a script_results metadata dict (when the JSON is gone):
    scripts/coc_score.py --from-script-results <script_result_id>

The metric is a single integer between 0 and 10; it is the count of
"smoke-pass" criteria the run hit:

    +1  cycles_completed >= 1  (any §81.1.2 full chain cycle landed)
    +1  cycles_observed >= 5   (the loop actually ran multiple cycles)
    +1  actions_fired >= 3     (at least three tree actions dispatched)
    +1  gold_gained > 0  OR  elixir_gained > 0  OR  dark_elixir_gained > 0
    +1  stop_reason == time_cap or max_cycles  (clean budget exit)
    +1  attack_attempted == False   (§R1 stayed locked)
    +1  buy_surface_refused == 0    (no real-money surface blocked a tap)
    +1  account_warning_seen == False  (§R5 stayed quiet)
    +1  guard_scan_count > 0   (the guard actually ran, not just imported)
    +1  event_log has at least one action_fired entry

A 7/10 is the minimum to call the bot "behaving like the spec" on a
tutorial account; 9-10 needs a non-tutorial account.

§81.1.9 adds two bonus criteria tied to the run-video recorder:

    +1  run_video_recorded -- the local MP4 was produced
    +1  run_video_uploaded -- the R2 URL is on the JSON

That gives a 12-point scale: 9/12 is the new bar for "behaving like the
spec" on a tutorial account (the video carries evidence even when the
chain can't fire), 11/12 needs the chain AND the video.
"""

import argparse
import json
import os
import sys


DEFAULT_EVENTS_JSON = "/var/lib/vpt/coc_frames/latest_events.json"

METRIC_KEYS = (
    "cycles_completed", "cycles_observed", "actions_fired",
    "gold_gained", "elixir_gained", "dark_elixir_gained",
    "stop_reason", "attack_attempted", "buy_surface_refused",
    "account_warning_seen", "guard_scan_count",
    "event_log", "play_duration_s",
)


def _load_events_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _grade(p):
    """Returns (score, max_score, breakdown).

    Since §81.1.9 added 2 video criteria the scale is 12 (the tutorial
    criterion went with the removed tutorial bot, TASK-100)."""
    k = p.get("kpis") or {}
    cycles_completed = k.get("cycles_completed", 0) or 0
    cycles_observed = (p.get("cycles_observed", 0) or
                       k.get("cycles_observed", 0) or 0)
    actions_fired = k.get("actions_fired", 0) or 0
    gold = k.get("gold_gained", 0) or 0
    elixir = k.get("elixir_gained", 0) or 0
    dark = k.get("dark_elixir_gained", 0) or 0
    stop = k.get("stop_reason", "")
    attack = k.get("attack_attempted", False)
    buy_refused = k.get("buy_surface_refused", 0) or 0
    warned = k.get("account_warning_seen", False)
    guard_scans = k.get("guard_scan_count", 0) or 0
    play_duration_s = k.get("play_duration_s", 0) or 0
    events = p.get("event_log", []) or []
    action_fired_count = sum(1 for e in events if e.get("kind") == "action_fired")
    # §81.1.9 video evidence: prefer the run_video block; fall back to
    # kpi-style fields if the script_results metadata dumped only kpis.
    rv = p.get("run_video") or {}
    rv_local = (rv.get("local_path") or
                p.get("run_video_path") or k.get("run_video_path") or "")
    rv_r2 = (rv.get("r2_url") or
             p.get("run_video_r2_url") or k.get("run_video_r2_url") or "")
    rv_chunks = (rv.get("chunks") or
                 p.get("run_video_chunk_count") or k.get("run_video_chunk_count") or 0)
    rv_disabled = (rv.get("disabled_reason") or
                   p.get("run_video_disabled_reason") or
                   k.get("run_video_disabled_reason") or "")

    rows = [
        ("cycles_completed>=1",
         bool(cycles_completed), f"cycles_completed={cycles_completed}"),
        ("cycles_observed>=5",
         bool(cycles_observed >= 5), f"cycles_observed={cycles_observed}"),
        ("actions_fired>=3",
         bool(actions_fired >= 3), f"actions_fired={actions_fired}"),
        ("any_resource_gained",
         bool((gold or elixir or dark) > 0),
         f"gold={gold} elixir={elixir} dark={dark}"),
        ("clean_budget_exit",
         stop in ("time_cap", "max_cycles", "completed"),
         f"stop_reason={stop}"),
        ("R1_locked (attack==False)",
         not bool(attack), f"attack_attempted={attack}"),
        ("no_buy_surface_block",
         bool(buy_refused == 0),
         f"buy_surface_refused={buy_refused}"),
        ("R5_quiet (no warning)",
         not bool(warned), f"account_warning_seen={warned}"),
        ("guard_ran (scan_count>0)",
         bool(guard_scans > 0), f"guard_scan_count={guard_scans}"),
        ("action_fired_in_log",
         bool(action_fired_count >= 1),
         f"action_fired events={action_fired_count}"),
        # §81.1.9 video criteria
        ("run_video_recorded",
         bool(rv_local and not rv_disabled),
         f"local_path={rv_local!r} chunks={rv_chunks} disabled={rv_disabled!r}"),
        ("run_video_uploaded_to_R2",
         bool(rv_r2),
         f"r2_url={rv_r2!r}"),
    ]
    score = sum(1 for _, hit, _ in rows if hit)
    rows.append(("play_duration_s (context)", None, f"{play_duration_s}s"))
    return score, len(rows) - 1, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("events_json", nargs="?", default=DEFAULT_EVENTS_JSON,
                    help="Path to the run's events.json (default: %(default)s)")
    ap.add_argument("--quiet", action="store_true", help="Just print metric=<n>.")
    ap.add_argument("--json", action="store_true", help="Print the full grade JSON instead.")
    args = ap.parse_args()

    payload = _load_events_json(args.events_json)
    if payload is None:
        print(f"coc_score: events.json not found at {args.events_json}", file=sys.stderr)
        return 2

    score, max_n, rows = _grade(payload)

    if args.json:
        print(json.dumps({
            "events_json": args.events_json,
            "score": score,
            "max": max_n,
            "rows": [{"name": n, "hit": (h is None and "context" or h),
                      "note": note} for n, h, note in rows],
            "kpis": payload.get("kpis", {}),
            "userinterface": payload.get("userinterface", ""),
            "device_model": payload.get("device_model", ""),
            "play_duration_s": payload.get("play_duration_s", 0),
            "cycles_observed": payload.get("cycles_observed", 0),
            "run_video": payload.get("run_video", {}),
        }, ensure_ascii=False, indent=2))
    elif args.quiet:
        print(f"metric={score}")
    else:
        print("=== Clash of Clans run grade ===")
        print(f"file:        {args.events_json}")
        ui = payload.get("userinterface", "?")
        device = payload.get("device_model", "?")
        print(f"interface:   {ui}  device: {device}")
        print(f"score:       {score} / {max_n}")
        print()
        print(f"{'criterion':<32} {'hit':<5} note")
        print("-" * 70)
        for n, hit, note in rows:
            mark = ""
            if hit is True:
                mark = "OK"
            elif hit is False:
                mark = "FAIL"
            else:
                mark = "   "
            print(f"{n:<32} {mark:<5} {note}")
        print()
        print(f"metric={score}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
