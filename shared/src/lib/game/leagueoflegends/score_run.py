"""TASK-131 goal 6: score a recorded League run folder, on its own (read-only, no game input).

A run folder holds ``timeline.json`` (from ``live_recorder``) and optionally ``shots/t<game second>.png`` and
``video.mp4``. :func:`score_run_dir` writes ``lol-scorecard.json`` + ``lol-scorecard.html`` next to it, with the
other scored runs of the same parent folder side by side. :func:`score_finished_runs` does that for every run that
has a timeline and a ``result.json`` (the bot writes it when the game ends) or a ``GameEnd`` event but no up-to-date scorecard, so a
loop on vpt-windows scores each game as soon as it is over, whoever played it.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any, Dict, List, Optional

from . import live_recorder, scorecard as sc
from .outcomes import finalize as finalize_rewards
from .turn_log import read_turns

JSON_NAME = "lol-scorecard.json"
HTML_NAME = "lol-scorecard.html"


def _others(run_dir: str) -> List[Dict[str, Any]]:
    cards = []
    for p in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(run_dir)), "*", JSON_NAME))):
        if os.path.dirname(p) == os.path.abspath(run_dir):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                cards.append(json.load(f))
        except (OSError, ValueError):
            continue
    return cards[-4:]


def cs_from_shots(run_dir: str) -> List[Dict[str, Any]]:
    """Exact CS series [{"t", "cs"}] read from ``shots/t<game second>.png`` (HUD counter); [] without shots or templates."""
    try:
        import cv2

        from . import cs_reader
    except ImportError:
        return []
    out = []
    for p in sorted(glob.glob(os.path.join(run_dir, "shots", "t*.png"))):
        img = cv2.imread(p)
        cs = None if img is None else cs_reader.read_cs(img)
        if cs is not None:
            out.append({"t": float(os.path.basename(p)[1:-4]), "cs": cs})
    return out


def score_run_dir(run_dir: str, with_others: bool = True) -> Dict[str, Any]:
    tl = live_recorder.load_timeline(os.path.join(run_dir, "timeline.json"))
    if not tl.get("cs_exact"):
        tl["cs_exact"] = cs_from_shots(run_dir)
    tl["meta"].setdefault("champion", "Garen")
    if not tl["meta"].get("assigned_position") or tl["meta"]["assigned_position"].upper() == "NONE":
        tl["meta"]["assigned_position"] = "top"  # Practice Tool reports no position; TASK-132 plays top
    ref = sc.reference_for(tl)
    attempts = []
    ap = os.path.join(run_dir, "lasthit", "attempts.json")
    if os.path.exists(ap):
        try:
            attempts = json.load(open(ap, encoding="utf-8")).get("attempts", [])
        except ValueError:
            attempts = []
    card = sc.laning_scorecard(tl, ref, attempts or None)  # owner scope 2026-10-19: the first 8 minutes; full game in card["full_game"]
    try:
        finalize_rewards(run_dir)  # rewards / outcomes into turns.jsonl, decisions.jsonl, reward_summary.json; never stops scoring
    except Exception:  # noqa: BLE001
        pass
    video = "video.mp4" if os.path.exists(os.path.join(run_dir, "video.mp4")) else None
    reward_summary = None
    try:
        reward_summary = json.load(open(os.path.join(run_dir, "reward_summary.json"), encoding="utf-8"))
    except (OSError, ValueError):
        pass
    sc.write_report(card, ref, os.path.join(run_dir, JSON_NAME), os.path.join(run_dir, HTML_NAME),
                    moments=sc.bad_moments(sc.window_timeline(tl, sc.LANING_END_S), ref), video_url=video,
                    others=_others(run_dir) if with_others else None,
                    turns=read_turns(os.path.join(run_dir, "turns.jsonl")), reward_summary=reward_summary)
    for legacy in ("scorecard.json", "scorecard.html"):  # readers of the first-generation names see the fresh overall too
        if os.path.exists(os.path.join(run_dir, legacy)):
            src = JSON_NAME if legacy.endswith("json") else HTML_NAME
            with open(os.path.join(run_dir, src), "rb") as f, open(os.path.join(run_dir, legacy), "wb") as g:
                g.write(f.read())
    _review(run_dir, card)
    return card


def _review(run_dir: str, card: Dict[str, Any]) -> None:
    """Per-game review: HTML timeline, training-data rows, reviewer-model ``review.md``. Never breaks scoring."""
    import traceback

    try:
        from . import game_review

        game_review.build_html(run_dir)
        root = os.environ.get("LOL_DATASET_ROOT") or (game_review.DATASET_ROOT_DEFAULT if os.name == "nt" else "")
        if root:
            game_review.write_dataset(run_dir, root)
        if os.environ.get("LOL_REVIEW_AI", "1" if os.name == "nt" else "0") == "1":  # a network call: on by default on the box only
            from . import game_review_ai

            game_review_ai.review_run_dir(run_dir, card)
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def _stale(run_dir: str) -> bool:
    tl, out = os.path.join(run_dir, "timeline.json"), os.path.join(run_dir, JSON_NAME)
    if not os.path.exists(tl) or (os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(tl)):
        return False
    if os.path.exists(os.path.join(run_dir, "result.json")):
        return True
    with open(tl, encoding="utf-8") as f:  # a human game recorded by live_recorder alone: over once GameEnd is in
        return '"GameEnd"' in f.read()


def score_finished_runs(root: str, pattern: str = "garen-run-*") -> List[str]:
    """Score every finished, unscored run under ``root``; returns the folders scored."""
    done = []
    for d in sorted(glob.glob(os.path.join(root, pattern))):
        if _stale(d):
            score_run_dir(d)
            done.append(d)
    return done


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import time

    ap = argparse.ArgumentParser(description="Score League run folders (TASK-131)")
    ap.add_argument("path", help="a run folder, or with --root the folder that holds garen-run-*")
    ap.add_argument("--root", action="store_true", help="score every finished unscored run under path")
    ap.add_argument("--watch", type=float, default=0, metavar="SECONDS", help="with --root: repeat every N seconds")
    a = ap.parse_args(argv)
    if not a.root:
        c = score_run_dir(a.path)
        print(a.path, c["overall"])
        return 0
    while True:
        for d in score_finished_runs(a.path):
            print("scored", d, flush=True)
        if not a.watch:
            return 0
        time.sleep(a.watch)


if __name__ == "__main__":
    raise SystemExit(main())
