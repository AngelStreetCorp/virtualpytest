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
from shared.src.lib.game.ai_usage import AiUsage
from shared.src.lib.game.pokemon import report as game_report
from shared.src.lib.game.pokemon import stall as game_stall
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
    "--chooser:str:jev:heuristic|jev|flash",
    "--start:str:",
    f"--stall_minutes:int:{game_stall.NO_PROGRESS_MIN}",
    f"--stall_ticks:int:{game_stall.SAME_SPOT_TICKS}",
    "--clear_stall:str:",
]
_script_description = "Play Pokémon Blue (the owner's own ROM) on a web host for a time budget, resuming from the last save."
_arg_descriptions = {
    'userinterface': f"The emulator userinterface ({UI_NAME})",
    'private_dir': 'Owner-only folder on the host with the ROM, the saves (state_<save>.json) and the memory (memory_<save>.json)',
    'rom': 'ROM file name in private_dir (the owner\'s own copy; .zip or .gb)',
    'save': 'Save to resume from and to write back (state_<save>.json / memory_<save>.json)',
    'max_duration': 'Seconds to play in this run (short runs: each one resumes the previous)',
    'strategist': 'llm: the AI usage text.game_strategy rewrites the plan on defeats and new milestones; fallback: fixed rules',
    'chooser': 'Battle moves: heuristic (expected damage), jev (the paid decision model, called through the server), '
               'or flash (MiniMax M3.1 Flash, free: the volume lane plays on it so a run costs $0)',
    'start': 'Empty: resume the save. "new": restart this save from power-on (title screen, empty memory). A time '
            'stamp YYYYMMDD-HHMMSS: restart from that backup of this save (state_<save>.<stamp>.json and its memory). '
            'The current save is backed up first either way.',
    'stall_minutes': 'Stall detector: stop the run when no milestone completed, no new map and no new square was entered for this many minutes of game time',
    'stall_ticks': 'Stall detector: stop the run when the player stays on the same map position for this many overworld ticks',
    'clear_stall': 'yes: clear the stall lock of this save (after the cause is fixed) so the long-play deployment plays again',
}
START = re.compile(r"^(new|\d{8}-\d{6})$")
REPORTED = ("milestone", "defeat", "strategy", "heal_start", "healed", "train_start", "trained", "gym_leader", "lost")


class VptGameIO:
    """The emulator page: the game's own JavaScript, straight from the web controller.

    BUG-0876: the game used to ask for its JavaScript through the action executor, which
    photographs the page before and after every action. That photograph is a PAGE screenshot, and
    the page's command queue is one single channel: a page that stops painting (the host's window
    is occluded and the box is busy) hung the screenshot for ever, and every read and key press
    queued behind it waited out its own timeout - 25 s a game action, and the game never played
    another step (the stall of run 20261023-152314: the first hang in the host's journal is
    "Page screenshot timed out after 5s", and every "vptGB.wram()" behind it waited out its 15 s).
    The game talks to the page directly now: only the game is ever queued on the game's channel,
    so a page that stops painting costs the run its pictures, never its game.
    """

    def __init__(self, device, context):
        self.device, self.context = device, context

    def js(self, script_text: str):
        try:
            web = self.device._get_controller('web')
        except Exception as e:    # noqa: BLE001 - a device without a browser cannot play the game
            print(f"[game_pokemon] no web controller: {type(e).__name__}: {e}", flush=True)
            return None
        if web is None or not hasattr(web, "execute_javascript"):
            print("[game_pokemon] the web controller cannot run JavaScript", flush=True)
            return None
        try:
            out = asyncio.run(web.execute_javascript(script_text)) or {}
        except Exception as e:    # noqa: BLE001 - a dead controller is a dead page: the runner reads nothing
            print(f"[game_pokemon] the page did not answer: {type(e).__name__}: {e}", flush=True)
            return None
        if not out.get("success"):
            return None
        return out.get("result")

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

    def reboot(self):
        """BUG-0875: restart the emulator in the page (the ROM is loaded again, and the save with it),
        so a game whose loop is dead goes on playing instead of standing still. False when the page does
        not answer: the game is then really gone."""
        booted = self.js("() => vptGB.boot()")
        time.sleep(1.0)
        return bool(isinstance(booted, dict) and booted.get("loaded"))


def record(context, message, success, details, screenshot="", live_label=None):
    now = time.time()
    context.record_step_immediately({
        "live_label": live_label,
        "success": success, "message": message, "from_node": "game", "to_node": "game",
        "execution_time_ms": 0, "start_time": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
        "end_time": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
        "screenshot_path": screenshot or None, "step_end_screenshot_path": screenshot or None,
        "action_screenshots": [screenshot] if screenshot else [], "actions": [],
        "verifications": [{"verification_type": "pokemon", "command": "play", "label": message,
                           "success": success, "details": details}],
        "verification_results": [], "step_category": "pokemon",
    })


class _WithoutThePage:
    """The device as the screenshot helpers see it, with the web controller hidden.

    BUG-0876: a page screenshot is taken on the same Playwright channel as the game's JavaScript
    (the page's command queue), so it can block the game's reads and key presses - and a page that
    stops painting never answers a screenshot at all. The game's evidence is the host's own screen
    capture instead: it never touches the channel the game is played on.
    """

    def __init__(self, device):
        self._device = device

    def _get_controller(self, kind):
        if kind == 'web':
            return None
        return self._device._get_controller(kind)

    def __getattr__(self, name):
        return getattr(self._device, name)


def evidence(device, context, name):
    from shared.src.lib.utils.device_utils import capture_screenshot_for_script
    ok = capture_screenshot_for_script(_WithoutThePage(device), context, name)
    return context.screenshot_paths[-1] if ok and context.screenshot_paths else ""


def llm_complete(team_id, ai_usage):
    from shared.src.lib.ai import gateway

    def complete(prompt, system):
        t0 = time.time()
        out = {}
        # The strategist is a free model (Flash): a rate limit (HTTP 429) bills nothing, so the call is asked
        # again a few times before the run falls back to the fixed rules (2026-10-23: the whole account of the
        # provider was throttled for an hour by another job, and every run lost its strategist).
        for attempt in range(4):
            out = gateway.complete("text.game_strategy", prompt, system=system, max_tokens=500, team_id=team_id)
            ai_usage.record("strategy", out, int((time.time() - t0) * 1000))
            if out.get("success") or attempt == 3:
                break
            error = str(out.get("error") or "").lower()
            if "429" not in error and "rate limit" not in error and "rate_limit" not in error:
                break
            time.sleep(5 * (attempt + 1))
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


def model_choose(profile, team_id, refs, ai_usage, default_model):
    """Battle choices by one profile (usage text.decision). On a host, decisions.choose sends the
    call to the server (POST /server/ai/decide), which holds the key. Each call is logged to ai_decisions
    with `refs`, and outcomes are attached to those decisions when the battle ends. A failed call returns
    {} and the runner falls back to the heuristic for that turn.

    `resolve_profile` pins one profile with NO fallback: a free profile never lands on a paid hop, and
    a failing hop costs nothing but the turn."""
    from shared.src.lib.ai import decisions, router
    resolution = router.resolve_profile(profile, "text.decision", team_id)

    def choose(state, options, instructions):
        t0 = time.time()
        out = decisions.choose(resolution, state=state, options=options, instructions=instructions,
                               log=True, refs={**refs})
        ai_usage.record("battle", out, int((time.time() - t0) * 1000))
        if not out.get("success"):
            return {}
        return {"choice": out.get("choice"), "confidence": out.get("confidence"), "probabilities": out.get("probabilities"),
                "usage": out.get("usage"), "cost": out.get("cost"), "model": out.get("model") or default_model,
                "ms": out.get("ms") or int((time.time() - t0) * 1000),
                "decision_id": out.get("decision_id")}
    return choose


def jev_choose(team_id, refs, ai_usage):
    """Battle choices by Jev (profile jev, usage text.decision). Jev is a paid model (~$0.002 per fight),
    so it is the chooser of the dataset deployment, not of the free volume lane."""
    return model_choose("jev", team_id, refs, ai_usage, "jev")


def flash_choose(team_id, refs, ai_usage):
    """Battle choices by MiniMax M3.1 Flash (profile minimax-m3-1-flash): free and unlimited, so the
    volume lane plays at $0. The profile has no fallback, so a throttled or failing call returns {}
    and the runner falls back to the heuristic for that turn instead of paying for another hop."""
    return model_choose("minimax-m3-1-flash", team_id, refs, ai_usage, "MiniMax-M3.1-Flash")


# The battle choosers that call a model. "heuristic" is not in it: it calls no model and costs nothing.
CHOOSERS = {"jev": jev_choose, "flash": flash_choose}


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
    if (args.clear_stall or "").strip().lower() == "yes":
        print(f"[game_pokemon] stall lock of save {args.save} cleared: {game_stall.clear(pdir, args.save)}", flush=True)
        clearing = True
    else:
        clearing = False
        lock = game_stall.locked(pdir, args.save)
        if lock:
            # the long-play deployment keeps firing: refuse cheaply and FAIL, so the failing-streak alert keeps going until a person clears it
            context.error_message = (f"STALLED: save {args.save} is locked since the stall at {lock.get('milestone')} "
                                     f"({lock.get('reason')}). Report: {lock.get('report')}. Diagnose: python3 scripts/pokemon_stall_review.py "
                                     f"{lock.get('report')}; after the fix rerun with --clear_stall yes")
            context.overall_success = False
            return False
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
    if clearing:
        game_stall.forget_on_unlock(mem.get("memo", {}))   # counters and way-marks of the stalled run (BUG-0694)
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
        ai_usage = AiUsage("game_pokemon")
        refs = {"game": "pokemon", "save": args.save,
                "script_result_id": getattr(context, "script_result_id", None) or run_stamp}
        runner = Runner(SnapshotIO(io), rom_bytes(rom_path),
                        choose=CHOOSERS[args.chooser](context.team_id, refs, ai_usage)
                        if args.chooser in CHOOSERS else None,
                        complete=llm_complete(context.team_id, ai_usage) if args.strategist == "llm" else None,
                        memo=mem.get("memo", {}), world=world,
                        on_battle_end=outcome_writer(context.team_id)
                        if args.chooser in CHOOSERS else None)
        start = {"milestone": current(runner.read, runner.memo).id, "party": runner.party(), "money": runner.money(),
                 "badges": badges(runner.read), "resumed": bool(boot.get("resumed"))}
        if start["resumed"] and mem:
            # the run was stopped: the strategist reviews its plan from the save and its memory only
            runner.rethink("resumed after a stop")
        how = f"backup {start_from} of save {args.save}" if start_from not in ("", "new") else \
            f"save {args.save}" if start["resumed"] else f"new game, save {args.save}"
        record(context, f"Started at {start['milestone']} ({how})",
               bool(boot.get("loaded")), start, evidence(device, context, "pokemon_start"))
        base_event = runner.event

        def live_event(kind, **facts):
            """Each notable event is a platform step the moment it happens, so Run Tests shows it live."""
            base_event(kind, **facts)
            if kind in REPORTED:
                e = runner.log[-1]
                detail = ", ".join(f"{k}={v}" for k, v in e.items() if k not in ("t", "kind", "known"))
                record(context, f"{kind}: {detail}"[:300], kind not in ("defeat", "lost"), e,
                       live_label=f"{kind.replace('_', ' ')} - {detail}"[:60])
        runner.event = live_event
        detector = game_stall.StallDetector(runner.memo, args.stall_minutes, args.stall_ticks)
        result = runner.run(max(10, int(args.max_duration) - (time.time() - t0) - 15), stall=detector)
        rec = io.js("() => vptGB.stopRecording()") or {}
        saved = io.js("() => vptGB.upload()")
        if start["party"] and not runner.party():
            # BUG-0872: the game is gone (the page died, or the ROM restarted by itself): its empty memory
            # must never be written over the save. The run of 20261023-132854 would have replaced the
            # 8-badge game with a title screen.
            print(f"[game_pokemon] the game is gone (party {len(start['party'])} -> 0): the save is kept as it is",
                  flush=True)
            saved = False
        time.sleep(0.5)

    done = runner.memo.get("done", [])
    progressed = len(done) > len(mem.get("memo", {}).get("done", [])) or result["counts"].get("walk", 0) > 0
    # the same milestone ending 3 runs in a row with "no progress" is a stall too
    # BUG-0662: a run that ends with the story done (every milestone done or deferred) has nothing left to play.
    # A story that is "done" only because milestones were deferred is blocked, not finished: that is a stall too.
    story_done = bool(result["counts"].get("story done"))
    stall_reason = result.get("stalled") or (game_stall.deferred_end(runner.memo) if story_done else
                                             game_stall.note_run(runner.memo, result["milestone"], progressed))
    if result.get("emulator_gone"):
        # BUG-0872: the emulator page died: the game is fine, the page is not. This is not a stalled run, so
        # there is no report and no lock (the dispatcher keeps playing the save), and the run is not counted
        # as a run without progress either.
        stall_reason = None
    saved_names = {"state": os.path.basename(state_in), "memory": os.path.basename(memory_path), "backup_stamp": None}
    if saved and os.path.exists(state_new):
        # back up the save and its memory under one time stamp (what --start restarts from), then replace them
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        saved_names["backup_stamp"] = stamp
        for path, kind in ((state_in, "state"), (memory_path, "memory")):
            if os.path.exists(path):
                shutil.copy2(path, os.path.join(pdir, f"{kind}_{args.save}.{stamp}.json"))
        os.replace(state_new, state_in)
    log = (mem.get("log", []) + runner.log)[-2000:]
    # BUG-0897: the stall report and the lock are written BEFORE the memory and before the long upload
    # of the game report. A run that dies in between (the report of the run of 20261024-213405 was
    # never written) leaves the save unlocked with an overdue no-progress clock in its memory: the
    # dispatcher starts the next run without --clear_stall yes and that run is killed by the clock of
    # the run before it within seconds (the run of 20261025-000846: 16 s of play, then a stall).
    stall_detail = stall_report_path = None
    if stall_reason:
        stall_detail = game_stall.describe(stall_reason, args.stall_minutes, args.stall_ticks)
        report = game_stall.build_report(reason=stall_reason, detail=stall_detail, milestone=result["milestone"],
                                         map_id=result["map"], pos=result["pos"], log=runner.log, memo=runner.memo,
                                         save=args.save, run_id=run_stamp, saved=saved_names, private_dir=pdir)
        stall_report_path = game_stall.write_report(pdir, report)
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
    kpis = {"milestones_done": done, "milestone": result["milestone"], "milestones_total": len(MILESTONES),
            "badges": badges(runner.read), "party": runner.party(), "money": runner.money(),
            "battle_decisions": sum(1 for e in runner.log if e["kind"] == "battle_choice"),
            "defeats": sum(1 for e in runner.log if e["kind"] == "defeat"),
            "plan": mem_s.get("plan"), "lessons": mem_s.get("lessons"), "rules": mem_s.get("rules"),
            "ticks": result["ticks"], "ticks_by_kind": result["counts"], "play_duration_s": round(time.time() - t0, 1),
            "resumed": start["resumed"], "start": start_from or "save", "saved": bool(saved), "start": {k: start[k] for k in ("milestone", "money", "badges")},
            "game_report_url": report_url, "video_kb": len(video or b"") // 1024, "ai": game_report.totals(runner.log)}
    record(context, "Game report: the run's video with every decision overlaid" + ("" if report_url else " (upload failed)"),
           bool(report_url), {"game_report_url": report_url, "video_kb": kpis["video_kb"], "ai": kpis["ai"]})
    record(context, f"KPI: milestone {result['milestone']}, badges {kpis['badges']}, {kpis['battle_decisions']} battle "
                    f"decisions, {kpis['defeats']} defeats, saved={kpis['saved']}", bool(saved) and progressed, kpis,
           evidence(device, context, "pokemon_end"))
    kpis["ai_usage"] = ai_usage.metadata()
    context.metadata = kpis
    context.overall_success = bool(saved) and progressed
    if not context.overall_success:
        context.error_message = ("the emulator page died" if result.get("emulator_gone") else
                                 "save failed" if not saved else "no progress in this run")
    if stall_reason:
        # the stalled run FAILS and locks the save; the codebox watcher starts an agent that fixes it and clears the lock
        context.overall_success = False
        context.error_message = game_stall.stalled_message(stall_detail, result["milestone"], result["map"], result["pos"],
                                                           stall_report_path)
        context.metadata = {**kpis, "stall": {"reason": stall_reason, "report": stall_report_path}}
        record(context, "STALLED: " + stall_detail, False, {"report": stall_report_path, "milestone": result["milestone"]})
    context.execution_summary = (f"Pokémon Blue: {result['milestone']} | badges {kpis['badges']} | "
                                 f"plan: {kpis['plan']} | saved={kpis['saved']}\n" + ai_usage.summary())
    return context.overall_success


main._script_args = _script_args
main._target_rules = {"target_type": "host", "host_os": "all"}   # the host target: Playwright on the host, device_id "host"

if __name__ == "__main__":
    main()
