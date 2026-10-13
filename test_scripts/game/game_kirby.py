#!/usr/bin/env python3
"""
Super Kirby Clash fight bot (TASK-51): a real-time fight loop on a Nintendo Switch, with a bot
that fires a Switch action every frame and Jev (or a fixed tactic) that picks the bot's tactic
on a 2 s / event cadence.

The script can play N fights in a row. With ``--start any`` (default) a menu driver first gets
the Switch to the start of the *Hornhead* quest fight from whatever screen is on; with
``--start fight`` the fight must already be on screen (today's behaviour, kept for one-shot runs).
After every fight the same menu driver plays the results → "Play the same quest" → Set Off →
fight loop so the next fight can start.
"""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_args, get_context, get_device
from shared.src.lib.game.kirby.menus import MenuDriver
from shared.src.lib.game.kirby.runner import KPI_FIELDS, KirbyRunner, VptIO, summary

_script_args = [
    "--chooser:str:jev:fixed|jev",
    "--max_duration:int:170",
    "--start:str:any:any|fight",
    "--fights:int:1",
]
_script_description = "Play one or more Super Kirby Clash boss fights on a Nintendo Switch with the Jev tactic chooser."
_arg_descriptions = {
    "chooser": "fixed: one tactic only (rush). jev: ask the Jev decision model every ~2 s or on event.",
    "max_duration": "Hard stop in seconds per fight; the run ends with max_duration (170 by default).",
    "start": "any: run the menu driver first (Hornhead quest from any screen). fight: the fight must already be on screen.",
    "fights": "Number of fights to chain. After each fight the menu driver re-opens the quest and starts the next one.",
}


@script("game_kirby", "Super Kirby Clash fight bot: real-time play on a Switch with Jev tactics",
        default_device="device1")
def main():
    args = get_args()
    context = get_context()
    device = get_device()
    io = VptIO(device, context)
    choose = None if args.chooser == "fixed" else _build_jev_chooser(context)
    outcome_writer = _outcome_writer(context.team_id) if args.chooser == "jev" else None

    metadata, success, error_message, last = play_fights(
        io, context, fights_n=int(args.fights), start=args.start, max_duration=int(args.max_duration),
        chooser_name=args.chooser, choose=choose, outcome_writer=outcome_writer)

    context.metadata = metadata
    context.overall_success = success
    context.error_message = error_message
    context.execution_summary = summary(last or {"chooser": args.chooser, "end_reason": ""},
                                        success, error_message)
    return success


def _step(message, success, details, command="play", shot="", shots=None):
    """``shots``: several screenshots for one step ``[{"path", "label"}]`` (the menu trail)."""
    shots = [x for x in (shots or []) if x.get("path")] + ([{"path": shot, "label": "end"}] if shot else [])
    return {
        "success": success, "message": message, "from_node": "game", "to_node": "game",
        "execution_time_ms": int(details.get("menu_s", 0) * 1000), "start_time": "", "end_time": "",
        "screenshot_path": shots[-1]["path"] if shots else None,
        "step_end_screenshot_path": shots[-1]["path"] if shots else None,
        "action_screenshots": [x["path"] for x in shots],
        "actions": [{"command": x["label"], "params": {}} for x in shots],
        "verifications": [{"verification_type": "kirby", "command": command, "label": message,
                           "success": success, "details": details}],
        "verification_results": [], "step_category": "kirby",
    }


def play_fights(io, context, fights_n, start, max_duration, chooser_name, choose, outcome_writer):
    """Menus -> fight, N times. Returns (metadata, success, error_message, last fight data)."""
    fights_n = max(int(fights_n), 1)
    fights_data: list = []
    menu_s_total = 0.0
    error_message = ""

    for i in range(1, fights_n + 1):
        context.record_step_immediately(_step(
            f"Fight {i}/{fights_n} starting", True, {"fight": i, "fights": fights_n, "start": start},
            shot=io.evidence(f"kirby_start_{i}")))

        menu_s, menu_steps = 0.0, 0
        if start == "any" or i > 1:
            report = MenuDriver(io).to_fight()
            menu_s, menu_steps = report["menu_s"], report["steps"]
            menu_s_total += menu_s
            shot = io.evidence(f"kirby_menu_{i}")
            context.record_step_immediately(_step(
                f"Menus → fight {i}", report["reached"],
                {"steps": menu_steps, "menu_s": menu_s, "screens": report["screens"], "error": report["error"]},
                command="menu", shot=shot, shots=report.get("shots")))
            if not report["reached"]:
                error_message = f"fight {i}: {report['error'] or 'menu driver did not reach the fight'}"
                break

        data = KirbyRunner(io, context, choose=choose, max_duration=max_duration).run(outcome_writer=outcome_writer)
        fights_data.append({
            "fight": i, "menu_s": menu_s, "menu_steps": menu_steps,
            **{k: data.get(k) for k in KPI_FIELDS},
        })
        if data.get("end_reason") not in ("fight_over", "max_duration"):
            error_message = f"fight {i}: end_reason={data.get('end_reason')}"
            break

    metadata = {
        "fights_played": len(fights_data),
        "fights_over": sum(1 for f in fights_data if f.get("end_reason") == "fight_over"),
        "chooser": chooser_name,
        "menu_s_total": round(menu_s_total, 2),
        "fights": fights_data,
    }
    return metadata, not error_message and len(fights_data) == fights_n, error_message, (fights_data[-1] if fights_data else None)


def _outcome_writer(team_id):
    """Attach the HP lost in the 2 s after a decision to that ai_decisions row (as game_pokemon.py does)."""
    from shared.src.lib.ai import decisions

    def fn(decision_ids, outcome):
        for did in decision_ids:
            try:
                decisions.set_outcome(did, team_id, outcome)
            except Exception as e:
                print(f"warning: set_outcome failed for {did}: {e}")
    return fn


def _build_jev_chooser(context):
    """Wire Jev (decisions.choose) with the same contract as ``game_pokemon.py``."""
    from shared.src.lib.ai import decisions, router
    team_id = context.team_id
    resolution = router.resolve_profile("jev", "text.decision", team_id)
    refs = {"game": "kirby", "script_result_id": getattr(context, "script_result_id", None) or "kirby"}

    def choose(state, options, instructions):
        out = decisions.choose(resolution, state=state, options=options, instructions=instructions,
                               log=True, refs=dict(refs))
        if not out.get("success"):
            return {}
        return {
            "choice": out.get("choice"),
            "confidence": out.get("confidence"),
            "probabilities": out.get("probabilities"),
            "cost": out.get("cost"),
            "ms": out.get("ms"),
            "decision_id": out.get("decision_id"),
        }
    return choose


main._script_args = _script_args
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "nintendo_switch",
}

if __name__ == "__main__":
    main()