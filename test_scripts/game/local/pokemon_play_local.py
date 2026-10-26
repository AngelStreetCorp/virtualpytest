#!/usr/bin/env python3
"""
Play Pokémon Blue locally for a time budget from a private checkpoint, and save where it stopped
(TASK-33 phase 4b). Each run is a resume: the emulator state plus the runner's memory (milestone memo,
learned world graph, decision log) are restored from the previous run's files.

  cd shared/src/lib/game/pokemon/web && python3 -m http.server 8767 --bind 127.0.0.1 &
  DISPLAY=:97 python test_scripts/game/local/pokemon_play_local.py --rom <rom> --state <in.json> \\
      --out-state <out.json> --memory <memory.json> --seconds 150 [--chooser jev]

ROM, states and memory are the owner's private files: never commit or upload them.
"""

import argparse
import json
import os
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from playwright.sync_api import sync_playwright  # noqa: E402

from shared.src.lib.game.pokemon import report as game_report  # noqa: E402
from shared.src.lib.game.pokemon import series as game_series  # noqa: E402
from shared.src.lib.game.pokemon.milestones import badges, current  # noqa: E402
from shared.src.lib.game.pokemon.runner import Runner, SnapshotIO  # noqa: E402
from shared.src.lib.game.pokemon.serve import GameServer  # noqa: E402
from shared.src.lib.game.pokemon.world import World  # noqa: E402

BUTTONS = {"A": "a", "B": "b", "START": "start", "SELECT": "select", "UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right"}
BRIDGE = "ssh server sudo -n -u vpt_user /opt/virtualpytest/venv/bin/python /tmp/jevbridge/jev_bridge.py"


class PageIO:
    def __init__(self, page):
        self.page = page

    def read(self, addr, n=1):
        return self.page.evaluate(f"() => vptGB.read({addr}, {n})")

    def wram(self):
        return self.page.evaluate("() => vptGB.wram()")

    def press(self, key, hold_ms=90):
        # same path as on a host: the page holds the Game Boy button (vptGB.hold)
        self.page.evaluate(f"() => vptGB.hold('{BUTTONS[key]}', {int(hold_ms)})")
        self.page.wait_for_timeout(int(hold_ms) + 20)

    def wait(self, ms):
        self.page.wait_for_timeout(ms)

    def save_state(self):
        return self.page.evaluate("() => vptGB.saveState()")

    def reboot(self):
        """BUG-0875: restart the emulator in the page (the ROM is loaded again, and the save with it)."""
        try:
            booted = self.page.evaluate("() => vptGB.boot()")
        except Exception:                      # noqa: BLE001 - a page that does not answer is gone
            return False
        return bool(isinstance(booted, dict) and booted.get("loaded"))


def bridge(cmd):
    """The AI bridge on the server (jev_bridge.py): returns (choose, complete)."""
    proc = subprocess.Popen(cmd.split(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    while True:
        line = proc.stdout.readline()
        if line.startswith("{") and json.loads(line).get("ready"):
            break

    def ask(req):
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        while line and not line.startswith("{"):
            line = proc.stdout.readline()
        if not line:  # the bridge died: no AI answer, the runner falls back
            return {}
        return json.loads(line)

    def choose(state, options, instructions):
        return ask({"state": state, "options": options, "instructions": instructions})

    def complete(prompt, system):
        out = ask({"op": "complete", "prompt": prompt, "system": system})
        return out if out.get("success") else None
    return choose, complete


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--out-state", required=True)
    ap.add_argument("--memory", required=True, help="runner memory JSON (read if it exists, then rewritten)")
    ap.add_argument("--seconds", type=float, default=150)
    ap.add_argument("--chooser", choices=("heuristic", "jev"), default="heuristic")
    ap.add_argument("--strategist", choices=("fallback", "llm"), default="fallback")
    ap.add_argument("--report", default="", help="write the run's game report (video + decisions) to this HTML file")
    ap.add_argument("--runs", default="", help="keep the run as a segment of the long game in this private folder (series.py plays them)")
    a = ap.parse_args()
    rom = zipfile.ZipFile(a.rom).read(zipfile.ZipFile(a.rom).namelist()[0]) if a.rom.endswith(".zip") else open(a.rom, "rb").read()
    mem = json.load(open(a.memory)) if os.path.exists(a.memory) else {}
    world = World({int(k): {**v, "edges": v["edges"], "warps": [tuple(w) for w in v["warps"]]} for k, v in mem.get("world", {}).items()})
    import time as _time
    stamp = _time.strftime("%Y%m%d-%H%M%S")
    if a.runs:
        os.makedirs(a.runs, mode=0o700, exist_ok=True)
    video_out = os.path.join(a.runs, f"{stamp}.webm") if a.runs else os.path.splitext(a.out_state)[0] + ".webm"
    with GameServer(a.rom, a.state, a.out_state + ".new", port=8793, video_out=video_out) as srv, sync_playwright() as p:
        b = p.chromium.launch(headless=False)
        page = b.new_page(viewport={"width": 1280, "height": 720})
        page.goto(srv.url)
        page.wait_for_function("() => typeof GameBoyCore !== 'undefined'")
        page.evaluate("() => vptGB.boot()")
        page.evaluate("() => vptGB.fastOptions()")
        page.wait_for_timeout(500)
        rec_start = page.evaluate("() => vptGB.startRecording()")
        page_io = PageIO(page)
        io = SnapshotIO(page_io)
        ai = bridge(BRIDGE) if (a.chooser == "jev" or a.strategist == "llm") else (None, None)
        runner = Runner(io, rom, choose=ai[0] if a.chooser == "jev" else None,
                        complete=ai[1] if a.strategist == "llm" else None, memo=mem.get("memo", {}), world=world)
        start_ms = current(runner.read, runner.memo).id
        if mem:
            runner.rethink("resumed after a stop")
        t0 = _time.time()
        result = runner.run(a.seconds)
        rec = page.evaluate("() => vptGB.stopRecording()")
        page.evaluate("() => vptGB.upload()")
        page.wait_for_timeout(300)
        page.screenshot(path=os.path.splitext(a.out_state)[0] + ".png", clip={"x": 320, "y": 72, "width": 640, "height": 576})
        party = runner.party()
        summary = {"start_milestone": start_ms, "end_milestone": result["milestone"], "badges": badges(runner.read),
                   "money": runner.money(), "duration_s": _time.time() - t0,
                   "leader": f"{party[0]['name']} L{party[0]['level']}" if party else "?"}
        b.close()
    os.replace(a.out_state + ".new", a.out_state)
    rec = {"start": rec_start, **(rec or {})}
    if a.runs:
        game_series.save_run(a.runs, stamp, runner.log, rec, summary)
    else:
        game_series.finalize_video(video_out)
    if a.report:
        video = open(video_out, "rb").read() if os.path.exists(video_out) else None
        html_text = game_report.build_html(runner.log, video, rec.get("type", "video/webm"), rec["start"], summary,
                                           video_end=rec.get("end"))
        open(a.report, "w").write(html_text)
        print(f"report: {a.report} ({len(html_text) // 1024} KB), video {len(video or b'') // 1024} KB for "
              f"{rec.get('end', 0) - rec['start']:.0f} s, totals {game_report.totals(runner.log)}")
    log = mem.get("log", []) + runner.log
    json.dump({"memo": runner.memo, "world": {str(k): v for k, v in runner.world.maps.items()}, "log": log},
              open(a.memory, "w"), indent=1)
    print(json.dumps(result))
    for e in runner.log:
        if e["kind"] != "battle_choice" or e.get("enemy_hp") is not None:
            print(" ", {k: v for k, v in e.items() if k != "t"})


if __name__ == "__main__":
    main()
