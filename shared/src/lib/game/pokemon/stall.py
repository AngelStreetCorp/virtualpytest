"""Stuck detector for the long-play runner (TASK-33).

A run is *stalled* when it keeps playing but gets nowhere:
  - `no_progress`: no milestone completed, no new map and no new square (first visit since the milestone started)
    for N minutes of game time; time spent in an activity that has its own give-up (training, the Surf hunt) does not count,
    nor the first BATTLE_GRACE_MIN minutes of one battle (a gym leader's six turns-long fight is play, BUG-0706);
  - `same_spot`: the same (map, position) for M overworld ticks in a row (battles and menus do not count);
  - `no_progress_runs`: the same milestone ended 3 runs in a row with "no progress";
  - `deferred_end`: the story reads "done" while a milestone was only deferred (`*_deferred` in the memo): the defers carried
    the runner past goals it never met, so nothing is left to play though the game is not finished.

On a stall the run stops cleanly (the script still saves state and memory), `build_report` writes the
brief an agent diagnoses and fixes from (`scripts/pokemon_stall_review.py --fix`, started within a minute by the
codebox watcher `scripts/agent/pokemon_stall_watch.sh`), and a lock file keeps the long-play deployment from rerunning on
the same stall until the fix is deployed and the lock cleared (`--clear_stall`).
The alert itself is the platform's own: the stalled run FAILS with a "STALLED:" error, and so do the
runs the lock refuses, which is what the "Script failing repeatedly" rule
(infra/monitoring/grafana/alerting/vpt-alert-rules.json) mails about after 3 failures.

Game time counts the seconds of play, at most 5 s per tick: a stop between two runs adds nothing.
The counters live in the memo, so they carry over from one 10-minute run to the next.
"""

import json
import os
import time
from typing import Dict, List, Optional

NO_PROGRESS_MIN = 5           # default N: minutes of game time without a milestone, a new map or a new square
# How much real time one tick may add to the no-progress clock. A tick is normally a fraction of a second; when the
# browser page stops answering, every read waits out its 15 s timeout and a tick lasts a minute. The old 5 s cap
# hid that: a dead page looked like a slow game, so the stall needed 60 ticks (an hour) to be seen and the run
# outlived its budget instead of reporting the stall (2026-10-23).
TICK_DT_CAP_S = 60.0
# A longer gap is a stop between two runs, not a slow tick: it counts nothing (the run starts fresh).
STOP_GAP_S = 300.0
SAME_SPOT_TICKS = 300         # default M: overworld ticks on one (map, position), ~3.5 min at ~90 ticks/min
CELLS_MAX = 3000              # squares remembered per milestone; past it only milestones and maps count
NO_PROGRESS_RUNS = 3          # runs in a row ending "no progress" on the same milestone
BATTLE_GRACE_MIN = 15         # minutes of one battle that do not count as "no progress"; past it a wedged fight does
EXEMPT_PREFIXES = ("battle", "learn", "intro", "bad read")   # long fights and menus on one square are normal
EVENTS_IN_REPORT = 30
TEXT_LIMIT = 600


class StallDetector:
    def __init__(self, memo: Dict, no_progress_min: float = NO_PROGRESS_MIN, same_spot_ticks: int = SAME_SPOT_TICKS):
        self.memo = memo
        self.no_progress_s = float(no_progress_min) * 60
        self.same_spot_ticks = int(same_spot_ticks)
        self.state = memo.setdefault("stall", {"progress_s": 0.0, "maps": [], "milestones": 0, "spot": None, "spot_ticks": 0})
        # BUG-0897: a run must not be killed by a measurement it did not spend. The no-progress clock
        # lives in the memo and carries over from one run to the next, so that a milestone that never
        # progresses is caught even when every run is short. The clock of a run that ended in a stall is
        # forgotten when the lock is cleared (forget_on_unlock) - but a run whose stall report never made
        # it back to the dispatcher leaves an overdue clock in the memo: the next run inherited it and the
        # detector fired on its very first tick. The run of 20261025-000846 played 16 seconds and the
        # report claimed "no milestone, no new map and no new square for 5 min of game time" - the time of
        # the run before it (300.19 s, already over the threshold), not of its own. A measurement that is
        # already overdue when a run starts is not that run's: the run starts its own.
        if float(self.state.get("progress_s") or 0.0) >= self.no_progress_s:
            self.state["progress_s"] = 0.0
        if int(self.state.get("spot_ticks") or 0) >= self.same_spot_ticks:
            self.state["spot_ticks"] = 0
        self._last = 0.0

    def observe(self, what: str, milestone: str, map_id: int, pos, done: int, now: Optional[float] = None,
                guarded: bool = False) -> Optional[str]:
        """Feed one tick; returns the stall reason ("no_progress" / "same_spot") or None.
        `guarded`: the tick belongs to an activity with its own give-up (training, the Surf hunt): no time accrues."""
        now = time.time() if now is None else now
        st = self.state
        gap = (now - self._last) if self._last else 0.0
        dt = 0.0 if gap > STOP_GAP_S else min(TICK_DT_CAP_S, gap)
        self._last = now
        if st.get("ms") != milestone:
            st["ms"], st["cells"] = milestone, []
        cell = f"{map_id}:{pos[0]}:{pos[1]}"
        cells = st.setdefault("cells", [])
        new_cell = cell not in cells and len(cells) < CELLS_MAX
        if new_cell:
            cells.append(cell)
        if done > st["milestones"] or map_id not in st["maps"] or new_cell:
            if map_id not in st["maps"]:
                st["maps"].append(map_id)
            st["milestones"] = max(done, st["milestones"])
            st["progress_s"] = 0.0
        elif not guarded:
            # BUG-0706: Blaine's fight alone took 4.7 min of the 5; a battle ends by itself, so only a wedged one counts
            st["battle_s"] = st.get("battle_s", 0.0) + dt if what.startswith("battle") else 0.0
            if st["battle_s"] == 0.0 or st["battle_s"] > BATTLE_GRACE_MIN * 60:
                st["progress_s"] += dt
        spot = [map_id, list(pos)]
        if what.startswith(EXEMPT_PREFIXES):
            pass
        elif st["spot"] == spot:
            st["spot_ticks"] += 1
        else:
            st["spot"], st["spot_ticks"] = spot, 1
        if st["progress_s"] >= self.no_progress_s:
            return "no_progress"
        if st["spot_ticks"] >= self.same_spot_ticks:
            return "same_spot"
        return None

    def reset(self) -> None:
        self.state.update(progress_s=0.0, spot=None, spot_ticks=0, cells=[])


def describe(reason: str, no_progress_min: float, same_spot_ticks: int) -> str:
    return {"no_progress": f"no milestone, no new map and no new square for {no_progress_min:g} min of game time",
            "same_spot": f"the same map position for {same_spot_ticks} ticks",
            "no_progress_runs": f"the same milestone ended {NO_PROGRESS_RUNS} runs in a row with no progress",
            "deferred_end": "the story ended only because milestones were deferred, the game is not finished"}.get(reason, reason)


def deferred_flags(memo: Dict) -> List[str]:
    return sorted(k for k, v in memo.items() if k.endswith("_deferred") and v)


def deferred_end(memo: Dict) -> Optional[str]:
    """A "story done" that rests on a deferred milestone is a stall ("deferred_end"); a real end returns None."""
    return "deferred_end" if deferred_flags(memo) else None


def stalled_message(detail: str, milestone: str, map_id: int, pos, report_path: str) -> str:
    """The error of a stalled run: what the failing-streak alert shows. Starts with STALLED so it is greppable."""
    return (f"STALLED: {detail} at {milestone} (map {map_id}, pos {tuple(pos)}). Report: {report_path}. "
            f"Auto-fix: the codebox watcher starts python3 scripts/pokemon_stall_review.py --fix {report_path}")


def note_run(memo: Dict, milestone: str, progressed: bool) -> Optional[str]:
    """Record how a run ended; returns "no_progress_runs" when this milestone has now had 3 in a row."""
    rec = memo.get("no_progress_runs") or {}
    if progressed:
        memo["no_progress_runs"] = {"milestone": milestone, "n": 0}
        return None
    n = rec.get("n", 0) + 1 if rec.get("milestone") == milestone else 1
    memo["no_progress_runs"] = {"milestone": milestone, "n": n}
    return "no_progress_runs" if n >= NO_PROGRESS_RUNS else None


def _short(v):
    return v[:TEXT_LIMIT] + "…" if isinstance(v, str) and len(v) > TEXT_LIMIT else v


def _counters(st: Optional[Dict]) -> Optional[Dict]:
    """The stall counters without the square list (only its size)."""
    if not isinstance(st, dict):
        return st
    return {**{k: v for k, v in st.items() if k != "cells"}, "cells": len(st.get("cells") or [])}


def last_plan(log: List[Dict], memo: Dict) -> Dict:
    """The last strategist plan: from this run's log when it has one, else from the memory."""
    from . import strategy
    for e in reversed(log):
        if e.get("kind") == "strategy" and e.get("plan"):
            return {"plan": _short(e["plan"]), "trigger": e.get("trigger"), "reason": _short(e.get("reason")), "source": e.get("source")}
    return {"plan": _short(strategy.memory(memo).get("plan")), "trigger": None, "reason": None, "source": "memory"}


def build_report(*, reason: str, detail: str, milestone: str, map_id: int, pos, log: List[Dict], memo: Dict,
                 save: str, run_id: str, saved: Dict, private_dir: str) -> Dict:
    """The stall report: the brief for the review-and-fix agent. `saved` names the state and memory files."""
    events = [{k: _short(v) for k, v in e.items() if k not in ("prompt", "answer", "known")} for e in log[-EVENTS_IN_REPORT:]]
    return {"kind": "pokemon_stall", "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "run_id": run_id, "save": save,
            "reason": reason, "detail": detail, "milestone": milestone, "map": map_id, "pos": list(pos),
            "done": list(memo.get("done", [])), "key_memo": {k: memo[k] for k in ("key_guard_talks", "walls", "bad_warps", "warp_retried", "balls_taken") if k in memo},
            "deferred": deferred_flags(memo),
            "last_events": events, "last_plan": last_plan(log, memo), "saves": saved, "private_dir": private_dir,
            "stall_counters": _counters(memo.get("stall")), "no_progress_runs": memo.get("no_progress_runs")}


def lock_path(private_dir: str, save: str) -> str:
    return os.path.join(private_dir, f"stall_{save}.lock.json")


def write_report(private_dir: str, report: Dict) -> str:
    """Write the report and the lock next to the saves (private: they name positions and plans of the owner's game)."""
    path = os.path.join(private_dir, f"stall_{report['save']}_{report['run_id']}.json")
    for p, body in ((path, report), (lock_path(private_dir, report["save"]), {"report": path, "run_id": report["run_id"],
                                                                              "reason": report["reason"], "milestone": report["milestone"]})):
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(body, f, indent=1)
    return path


def locked(private_dir: str, save: str) -> Optional[Dict]:
    """The lock of an uncleared stall, or None. While it exists, the long-play deployment's runs refuse to start."""
    try:
        return json.load(open(lock_path(private_dir, save)))
    except (OSError, ValueError):
        return None


def clear(private_dir: str, save: str) -> bool:
    try:
        os.unlink(lock_path(private_dir, save))
        return True
    except OSError:
        return False


# BUG-0694: what a cleared stall forgets. The counters gave up (HM teach tries); the way-marks (exits and doors found
# blocked, the edge entered by, the "lost" note) may be what walled the run in: the stall 20261019-160255 kept Route 5's
# exits to Saffron and Cerulean marked from older milestones and ping-ponged in its gate house. The runner relearns any
# that are real within a few ticks.
# BUG-0738: the one-way hop tiles are way-marks too, and a wrong one walls the player in: the stall 20261020-175235
# sealed the only way out of the player's pocket in the Viridian gym (10, 4), a square the runner's own step had been
# read to be a hop tile. They are dropped with the rest: the runner relearns the real ones by walking on them.
CLEARED_ON_UNLOCK = ("stall", "no_progress_runs", "hm_tries", "bad_exits", "bad_warps", "warp_retried", "entry", "lost",
                     "hops")


def forget_on_unlock(memo: Dict) -> None:
    """Drop the memo keys a cleared stall must not carry into the next run."""
    for k in CLEARED_ON_UNLOCK:
        memo.pop(k, None)
