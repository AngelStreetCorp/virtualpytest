#!/usr/bin/env python3
"""
Pokémon Blue showcase (TASK-33 phase 4): VirtualPyTest plays the real Game Boy game on a web host,
Jev-style — the harness reads the game's memory, lists the options with facts and decides; an LLM
strategist keeps the long-term plan and lessons. Each run resumes from the previous run's save and
memory and plays for a time budget.

The ROM is the owner's own copy and lives only in a private folder on the host (--private_dir), with
the saves and the runner memory. A private web server bound to 127.0.0.1 hands the ROM and the save to
the emulator page (shared/src/lib/game/pokemon/serve.py), so neither passes through actions, logs or
reports. The page itself is driven only through the executors (navigation + execute_javascript).
"""

import asyncio
import json
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
from shared.src.lib.game.pokemon import report as game_report
from shared.src.lib.game.pokemon import series as game_series
from shared.src.lib.game.pokemon import strategy
from shared.src.lib.game.pokemon.milestones import MILESTONES, badges, current
from shared.src.lib.game.pokemon.runner import Runner, SnapshotIO
from shared.src.lib.game.pokemon.serve import GameServer, rom_bytes
from shared.src.lib.game.pokemon.ui import UI_NAME
from shared.src.lib.game.pokemon.world import World

_script_args = [
    "--userinterface:str:" + UI_NAME,
    "--private_dir:str:/var/lib/vpt-private/pokemon",
    "--rom:str:pokemon_blue_fr_owner_cartridge.zip",
    "--save:str:latest",
    "--max_duration:int:170",
    "--strategist:str:llm:llm|fallback",
    "--chooser:str:jev:heuristic|jev",
    "--start:str:",
]
_script_description = "Play Pokémon Blue (the owner's own ROM) on a web host for a time budget, resuming from the last save."
_arg_descriptions = {
    'userinterface': f"The emulator userinterface ({UI_NAME})",
    'private_dir': 'Owner-only folder on the host with the ROM, the saves (state_<save>.json) and the memory (memory_<save>.json)',
    'rom': 'ROM file name in private_dir (the owner\'s own copy; .zip or .gb)',
    'save': 'Save to resume from and to write back (state_<save>.json / memory_<save>.json)',
    'max_duration': 'Seconds to play in this run (short runs: each one resumes the previous)',
    'strategist': 'llm: the AI usage text.game_strategy rewrites the plan on defeats and new milestones; fallback: fixed rules',
    'chooser': 'Battle moves: heuristic (expected damage), or jev (the decision model, called through the server)',
    'start': 'Empty: resume the save. "new": restart this save from power-on (title screen, empty memory). A time '
            'stamp YYYYMMDD-HHMMSS: restart from that backup of this save (state_<save>.<stamp>.json and its memory). '
            'The current save is backed up first either way.',
}
START = re.compile(r"^(new|\d{8}-\d{6})$")
REPORTED = ("milestone", "defeat", "strategy", "heal_start", "healed", "train_start", "trained", "gym_leader", "lost")


class VptGameIO:
    """The emulator page through the executors only: execute_javascript actions."""

    def __init__(self, device, context):
        self.device, self.context = device, context

    def js(self, script_text: str):
        from backend_host.src.orchestrator.execution_orchestrator import ExecutionOrchestrator
        result = asyncio.run(ExecutionOrchestrator.execute_actions(
            self.device, [{"command": "execute_javascript", "action_type": "web",
                           "params": {"script": script_text, "wait_time": 0}}],
            team_id=self.context.team_id, context=self.context))
        for r in reversed(result.get("results") or []):
            out = r.get("output_data") or {}
            if "result" in out:
                return out["result"]
        return None

    def wram(self):
        return self.js("() => vptGB.wram()") or [0] * 0x2000

    def read(self, addr, n=1):
        return self.js(f"() => vptGB.read({int(addr)}, {int(n)})")

    def press(self, key, hold_ms=90):
        button = {"A": "a", "B": "b", "START": "start", "SELECT": "select"}.get(key, key.lower())
        self.js(f"() => vptGB.hold('{button}', {int(hold_ms)})")
        time.sleep((int(hold_ms) + 20) / 1000)

    def wait(self, ms):
        time.sleep(ms / 1000)


def record(context, message, success, details, screenshot=""):
    now = time.time()
    context.record_step_immediately({
        "success": success, "message": message, "from_node": "game", "to_node": "game",
        "execution_time_ms": 0, "start_time": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
        "end_time": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
        "screenshot_path": screenshot or None, "step_end_screenshot_path": screenshot or None,
        "action_screenshots": [screenshot] if screenshot else [], "actions": [],
        "verifications": [{"verification_type": "pokemon", "command": "play", "label": message,
                           "success": success, "details": details}],
        "verification_results": [], "step_category": "pokemon",
    })


def evidence(device, context, name):
    from shared.src.lib.utils.device_utils import capture_screenshot_for_script
    ok = capture_screenshot_for_script(device, context, name)
    return context.screenshot_paths[-1] if ok and context.screenshot_paths else ""


def llm_complete(team_id):
    from shared.src.lib.ai import gateway

    def complete(prompt, system):
        t0 = time.time()
        out = gateway.complete("text.game_strategy", prompt, system=system, max_tokens=500, team_id=team_id)
        if not out.get("success"):
            return None
        return {"content": out.get("content"), "usage": out.get("usage"), "model": out.get("model"),
                "cost": out.get("cost"), "ms": int((time.time() - t0) * 1000)}
    return complete


WATCHDOG_MARGIN_S = 180   # time past the budget for saving and the report before a stuck run is ended


def start_watchdog(seconds: int):
    """End the process when the run outlives its budget: a call that never returns (seen once on a host, in
    the action executor after a JS call) would otherwise hold the device for the scheduler's whole hour."""
    def watch():
        time.sleep(seconds)
        print(f"[game_pokemon] watchdog: still running {seconds} s after start, ending the stuck run", flush=True)
        os._exit(3)
    threading.Thread(target=watch, daemon=True, name="game-watchdog").start()


def jev_choose(team_id, refs):
    """Battle choices by Jev (profile jev, usage text.decision). On a host, decisions.choose sends the
    call to the server (POST /server/ai/decide), which holds the key. Each call is logged to ai_decisions
    with `refs`, and outcomes are attached to those decisions when the battle ends. A failed call returns
    {} and the runner falls back to the heuristic for that turn."""
    from shared.src.lib.ai import decisions, router
    resolution = router.resolve_profile("jev", "text.decision", team_id)

    def choose(state, options, instructions):
        t0 = time.time()
        out = decisions.choose(resolution, state=state, options=options, instructions=instructions,
                               log=True, refs={**refs})
        if not out.get("success"):
            return {}
        return {"choice": out.get("choice"), "confidence": out.get("confidence"), "probabilities": out.get("probabilities"),
                "usage": out.get("usage"), "cost": out.get("cost"), "model": out.get("model") or "jev",
                "ms": out.get("ms") or int((time.time() - t0) * 1000),
                "decision_id": out.get("decision_id")}
    return choose


def outcome_writer(team_id):
    """Runner's on_battle_end: attach the outcome to every decision_id of the just-ended battle."""
    from shared.src.lib.ai import decisions

    def fn(decision_ids, outcome):
        for did in decision_ids:
            if not did:
                continue
            try:
                decisions.set_outcome(did, team_id, outcome)
            except Exception as e:
                print(f"warning: set_outcome failed for {did}: {e}")
    return fn


def upload_game_report(html_text: str, run_id: str):
    """Upload the run's game report next to the script reports; returns its (signed) URL or ""."""
    import tempfile
    from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_text)
        local = f.name
    try:
        res = get_cloudflare_utils().upload_files(
            [{"local_path": local, "remote_path": f"script-reports/game/pokemon/{run_id}/game_report.html"}],
            for_report_assets=True)
        return res["uploaded_files"][0]["url"] if res.get("uploaded_files") else ""
    finally:
        os.unlink(local)


@script("game_pokemon", "Pokémon Blue showcase: long play with memory, strategy and resume", default_device="host")
def main():
    args, context, device = get_args(), get_context(), get_device()
    context.userinterface = context.userinterface_name = args.userinterface
    pdir = args.private_dir
    rom_path = os.path.join(pdir, args.rom)
    state_in = os.path.join(pdir, f"state_{args.save}.json")
    memory_path = os.path.join(pdir, f"memory_{args.save}.json")
    start_from = (args.start or "").strip()
    if start_from and not START.match(start_from):
        context.error_message = f'--start must be "new" or a backup time stamp YYYYMMDD-HHMMSS, not {start_from!r}'
        context.overall_success = False
        return False
    # where this run starts: the save (resume), nothing (a new game), or a backup of the save
    state_src, memory_src = state_in, memory_path
    if start_from == "new":
        state_src, memory_src = "", ""
    elif start_from:
        state_src = os.path.join(pdir, f"state_{args.save}.{start_from}.json")
        memory_src = os.path.join(pdir, f"memory_{args.save}.{start_from}.json")
        if not os.path.exists(state_src):
            context.error_message = f"No backup state_{args.save}.{start_from}.json in the private folder"
            context.overall_success = False
            return False
    state_new = os.path.join(pdir, f".state_{args.save}.new")
    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    runs_dir = os.path.join(pdir, "runs")  # per-run video + events: the segments of the long game
    os.makedirs(runs_dir, mode=0o700, exist_ok=True)
    video_out = os.path.join(runs_dir, f"{run_stamp}.webm")
    if not os.path.exists(rom_path):
        context.error_message = f"ROM not found in the private folder ({pdir})"
        context.overall_success = False
        return False

    tree = device.navigation_executor.load_navigation_tree(args.userinterface, context.team_id)
    if not tree.get("success"):
        context.error_message = f"Navigation tree loading failed: {tree.get('error')}"
        context.overall_success = False
        return False
    context.tree_id = tree["tree_id"]

    mem = json.load(open(memory_src)) if memory_src and os.path.exists(memory_src) else {}
    world = World({int(k): {**v, "warps": [tuple(w) for w in v["warps"]]} for k, v in mem.get("world", {}).items()})
    io = VptGameIO(device, context)
    t0 = time.time()
    start_watchdog(int(args.max_duration) + WATCHDOG_MARGIN_S)
    with GameServer(rom_path, state_src, state_new, video_out=video_out):
        nav = asyncio.run(device.navigation_executor.execute_navigation(
            tree_id=context.tree_id, userinterface_name=args.userinterface, target_node_label="game",
            team_id=context.team_id, context=context))
        if not nav.get("success"):
            context.error_message = f"Could not open the emulator page: {nav.get('error')}"
            context.overall_success = False
            return False
        for _ in range(40):  # the emulator scripts come from the CDN
            if io.js("() => typeof GameBoyCore !== 'undefined' && typeof vptGB !== 'undefined'"):
                break
            time.sleep(0.5)
        boot = io.js("() => vptGB.boot()") or {}
        io.js("() => vptGB.fastOptions()")   # text fast, animations off, battle style set
        time.sleep(1.0)
        rec_start = io.js("() => vptGB.startRecording()") or time.time()
        refs = {"game": "pokemon", "save": args.save,
                "script_result_id": getattr(context, "script_result_id", None) or run_stamp}
        runner = Runner(SnapshotIO(io), rom_bytes(rom_path),
                        choose=jev_choose(context.team_id, refs) if args.chooser == "jev" else None,
                        complete=llm_complete(context.team_id) if args.strategist == "llm" else None,
                        memo=mem.get("memo", {}), world=world,
                        on_battle_end=outcome_writer(context.team_id) if args.chooser == "jev" else None)
        start = {"milestone": current(runner.read, runner.memo).id, "party": runner.party(), "money": runner.money(),
                 "badges": badges(runner.read), "resumed": bool(boot.get("resumed"))}
        if start["resumed"] and mem:
            # the run was stopped: the strategist reviews its plan from the save and its memory only
            runner.rethink("resumed after a stop")
        how = f"backup {start_from} of save {args.save}" if start_from not in ("", "new") else \
            f"save {args.save}" if start["resumed"] else f"new game, save {args.save}"
        record(context, f"Started at {start['milestone']} ({how})",
               bool(boot.get("loaded")), start, evidence(device, context, "pokemon_start"))
        result = runner.run(max(10, int(args.max_duration) - (time.time() - t0) - 15))
        for e in runner.log:
            if e["kind"] in REPORTED:
                record(context, f"{e['kind']}: " + ", ".join(f"{k}={v}" for k, v in e.items() if k not in ("t", "kind", "known"))[:300],
                       e["kind"] not in ("defeat", "lost"), e)
        rec = io.js("() => vptGB.stopRecording()") or {}
        saved = io.js("() => vptGB.upload()")
        time.sleep(0.5)

    if saved and os.path.exists(state_new):
        # back up the save and its memory under one time stamp (what --start restarts from), then replace them
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for path, kind in ((state_in, "state"), (memory_path, "memory")):
            if os.path.exists(path):
                shutil.copy2(path, os.path.join(pdir, f"{kind}_{args.save}.{stamp}.json"))
        os.replace(state_new, state_in)
    log = (mem.get("log", []) + runner.log)[-2000:]
    fd = os.open(memory_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"memo": runner.memo, "world": {str(k): v for k, v in runner.world.maps.items()}, "log": log}, f)

    # the run's game report: its video with every decision overlaid (prompt, answer, tokens, cost)
    party = runner.party()
    summary_r = {"start_milestone": start["milestone"], "end_milestone": result["milestone"], "badges": badges(runner.read),
                 "money": runner.money(), "duration_s": result.get("seconds") or (time.time() - t0),
                 "leader": f"{party[0]['name']} L{party[0]['level']}" if party else "?"}
    rec = {"start": rec_start, **rec}
    game_series.save_run(runs_dir, run_stamp, runner.log, rec, summary_r, save=args.save)  # a segment of the long game
    video = open(video_out, "rb").read() if os.path.exists(video_out) else None
    html_text = game_report.build_html(runner.log, video, rec.get("type", "video/webm"), rec["start"], summary_r,
                                       video_end=rec.get("end"))
    report_url = upload_game_report(html_text, getattr(context, "script_result_id", None) or run_stamp)
    mem_s = strategy.memory(runner.memo)
    done = runner.memo.get("done", [])
    kpis = {"milestones_done": done, "milestone": result["milestone"], "milestones_total": len(MILESTONES),
            "badges": badges(runner.read), "party": runner.party(), "money": runner.money(),
            "battle_decisions": sum(1 for e in runner.log if e["kind"] == "battle_choice"),
            "defeats": sum(1 for e in runner.log if e["kind"] == "defeat"),
            "plan": mem_s.get("plan"), "lessons": mem_s.get("lessons"), "rules": mem_s.get("rules"),
            "ticks": result["ticks"], "ticks_by_kind": result["counts"], "play_duration_s": round(time.time() - t0, 1),
            "resumed": start["resumed"], "start": start_from or "save", "saved": bool(saved), "start": {k: start[k] for k in ("milestone", "money", "badges")},
            "game_report_url": report_url, "video_kb": len(video or b"") // 1024, "ai": game_report.totals(runner.log)}
    progressed = len(done) > len(mem.get("memo", {}).get("done", [])) or result["counts"].get("walk", 0) > 0
    record(context, "Game report: the run's video with every decision overlaid" + ("" if report_url else " (upload failed)"),
           bool(report_url), {"game_report_url": report_url, "video_kb": kpis["video_kb"], "ai": kpis["ai"]})
    record(context, f"KPI: milestone {result['milestone']}, badges {kpis['badges']}, {kpis['battle_decisions']} battle "
                    f"decisions, {kpis['defeats']} defeats, saved={kpis['saved']}", bool(saved) and progressed, kpis,
           evidence(device, context, "pokemon_end"))
    context.metadata = kpis
    context.overall_success = bool(saved) and progressed
    if not context.overall_success:
        context.error_message = "save failed" if not saved else "no progress in this run"
    context.execution_summary = (f"Pokémon Blue: {result['milestone']} | badges {kpis['badges']} | "
                                 f"plan: {kpis['plan']} | saved={kpis['saved']}")
    return context.overall_success


main._script_args = _script_args
main._target_rules = {"target_type": "device", "host_os": "all", "device_model": "host_vnc"}

if __name__ == "__main__":
    main()
