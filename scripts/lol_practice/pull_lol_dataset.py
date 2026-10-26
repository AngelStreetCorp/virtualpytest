#!/usr/bin/env python3
"""Mac side: copy the League training data and reviews from vpt-windows, then refresh REVIEW_LOG.md.

    python3 scripts/lol_practice/pull_lol_dataset.py [--no-log]

- ``C:\\virtualpytest\\lol-dataset\\`` (one ``<game>.jsonl`` per game + ``crops/``) -> ``~/vpt-deliverables/lol-dataset/``
- every ``review.md`` / ``review.json`` / ``review.html`` of ``C:\\virtualpytest\\*run-*`` folders -> ``~/vpt-deliverables/lol-reviews/<run>/``
- the run's ``timeline.json`` + ``shots/`` + ``lasthit/`` (frames) so the Mac can review it; a run whose review was not written by
  Opus (``review.json`` provider != anthropic) is re-reviewed HERE with ``claude-opus-5-5`` straight from the Anthropic API
  (key from the Mac .env, never printed) and ``review.md`` / ``review.json`` are copied back into the run folder on the box
- the RULE lines of all reviews -> ``docs/agent/game/lol/REVIEW_LOG.md`` (this checkout)
Runs every 10 minutes from the launchd agent made by ``install_pull_agent.sh`` (a no-op when nothing is new).
"""
import json
import os
import subprocess
import sys

HOST = "vpt-windows"
HOME = os.path.expanduser("~")
DATASET = os.path.join(HOME, "vpt-deliverables", "lol-dataset")
REVIEWS = os.path.join(HOME, "vpt-deliverables", "lol-reviews")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ssh(cmd: str) -> str:
    return subprocess.run(["ssh", HOST, cmd], capture_output=True, text=True, timeout=120).stdout


def scp(remote: str, local: str) -> bool:
    return subprocess.run(["scp", "-q", "-r", f"{HOST}:{remote}", local], capture_output=True, timeout=600).returncode == 0


def main() -> int:
    os.makedirs(DATASET, exist_ok=True)
    have = set(os.listdir(DATASET))
    n = 0
    for name in ssh(r"dir /b C:\virtualpytest\lol-dataset 2>nul").split():
        if name.endswith(".jsonl"):  # rewritten per game: always refresh the small file
            n += scp(f"C:/virtualpytest/lol-dataset/{name}", DATASET)
    crops = ssh(r"dir /b C:\virtualpytest\lol-dataset\crops 2>nul").split()
    os.makedirs(os.path.join(DATASET, "crops"), exist_ok=True)
    local_crops = set(os.listdir(os.path.join(DATASET, "crops")))
    for g in crops:
        if g not in local_crops:
            scp(f"C:/virtualpytest/lol-dataset/crops/{g}", os.path.join(DATASET, "crops"))
    for run in ssh(r"dir /b /ad C:\virtualpytest").split():
        if "run-" not in run:
            continue
        out = os.path.join(REVIEWS, run)
        for f in ("review.md", "review.json", "review.html"):
            if not os.path.exists(os.path.join(out, f)) or f != "review.html":
                os.makedirs(out, exist_ok=True)
                scp(f"C:/virtualpytest/{run}/{f}", out)
    sys.path.insert(0, ROOT)
    for run in ssh(r"dir /b /ad C:\virtualpytest").split():
        out = os.path.join(REVIEWS, run)
        if "run-" not in run or not os.path.exists(os.path.join(out, "review.json")):
            continue  # only games the box already reviewed (older runs are not re-reviewed: cost)
        for f in ("timeline.json", "shots", "lasthit"):
            if not os.path.exists(os.path.join(out, f)):
                scp(f"C:/virtualpytest/{run}/{f}", out)
        rj = os.path.join(out, "review.json")
        done = False
        if os.path.exists(rj):
            try:
                done = json.load(open(rj)).get("provider") == "anthropic"
            except ValueError:
                pass
        if done or not os.path.exists(os.path.join(out, "timeline.json")):
            continue
        from shared.src.lib.game.leagueoflegends.game_review_ai import review_run_dir

        r = review_run_dir(out, force=True, backend="anthropic")
        print("opus review", run, r.get("ok"), r.get("model"), r.get("cost_usd"))
        if r.get("provider") == "anthropic":
            for f in ("review.md", "review.json"):
                scp(os.path.join(out, f).replace(os.sep, "/"), f"C:/virtualpytest/{run}/{f}")
    try:  # the progress page (static) after every pull: ~/vpt-deliverables/lol-progress/index.html
        from shared.src.lib.game.leagueoflegends import progress

        progress.main([])
    except Exception as e:  # noqa: BLE001
        print("progress page failed:", e)
    if "--no-log" not in sys.argv:
        sys.path.insert(0, ROOT)
        from shared.src.lib.game.leagueoflegends.game_review_ai import collect_review_log

        added = collect_review_log(REVIEWS, os.path.join(ROOT, "docs", "agent", "game", "lol", "REVIEW_LOG.md"))
        print("review log rows added:", added)
    print("dataset files refreshed:", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
