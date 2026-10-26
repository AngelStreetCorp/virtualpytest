"""TASK-134: one benchmark game. usage: run_llm_bench.py <rule|claude-haiku-5-5|claude-sonnet-5-5|haiku-coach|jev-coach|duo> [seconds] [blue|red] [enemytop]

Reuses run_garen_bot.main() unchanged (game start, scripted start sequence, recorder, scorecard, exit) and only swaps the bot
class for :class:`llm_policy.LlmBot`, which stops at 5:00 game time. Model calls go to LLM_RELAY_URL (default 127.0.0.1:8787, an ssh -R tunnel).
"""
import os
import sys

contestant = sys.argv[1]
ENEMY_TOP = "enemytop" in sys.argv  # 4th argument: an enemy bot lanes top against Garen
sys.argv = [sys.argv[0], sys.argv[2] if len(sys.argv) > 2 else "420"] + sys.argv[3:]
sys.path.insert(0, r"C:\virtualpytest\bench")  # own copy of run_garen_bot.py and of the lib (bench_cycle.sh); never the bot session's
import run_garen_bot as rgb  # noqa: E402

from shared.src.lib.game.leagueoflegends.coach_policy import CoachBot  # noqa: E402
from shared.src.lib.game.leagueoflegends.llm_policy import LlmBot  # noqa: E402

_bots = []


def _make(*a, **k):
    if contestant in ("haiku-coach", "jev-coach", "duo"):  # round 2: the rule bot plays, the model / Jev / both coach
        b = CoachBot(*a, kind=contestant, log_dir=str(rgb.OUT), **k)
    else:
        b = LlmBot(*a, model=contestant, log_dir=str(rgb.OUT), **k)
    _bots.append(b)
    return b


rgb.GarenBot = _make
if ENEMY_TOP:  # round 3 probe: an enemy bot lanes top against Garen (queue 3140, Practice Tool unchanged)
    import functools

    rgb.PracticeConfig = functools.partial(rgb.PracticeConfig, enemy_top_bot=True)
_save = rgb.live_recorder.save_timeline


def _save_with_deaths(tl, path):  # minion deaths seen by the bot's watcher go into the timeline before it is saved/scored
    if _bots and getattr(_bots[0], "deaths", None) is not None:
        tl["minion_deaths"] = _bots[0].deaths
        w = _bots[0].watcher
        if w is not None and getattr(w, "cs", None):  # exact HUD CS readings (2.5 Hz): the scorecard's farm and the deaths check use them
            tl["cs_exact"] = [{"t": round(t, 2), "cs": c} for t, c in w.cs]
    _save(tl, path)


rgb.live_recorder.save_timeline = _save_with_deaths
sys.exit(rgb.main())
