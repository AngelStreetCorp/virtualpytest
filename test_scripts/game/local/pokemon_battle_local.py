#!/usr/bin/env python3
"""
Play one Pokémon Blue battle locally from a private checkpoint with the battle options + a chooser
(TASK-33 phase 4b). The ROM and the checkpoint are the owner's private files: pass their paths; nothing
is copied or uploaded. Serve shared/src/lib/game/pokemon/web/ on 127.0.0.1 first.

  cd shared/src/lib/game/pokemon/web && python3 -m http.server 8767 --bind 127.0.0.1 &
  DISPLAY=:97 python test_scripts/game/local/pokemon_battle_local.py --rom <rom.zip|.gb> --state <lean.json> --chooser heuristic
  (--chooser jev talks to jev_bridge.py on VM 103 over ssh; copy it and decisions.py to /tmp/jevbridge/ there)
"""

import argparse
import json
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from playwright.sync_api import sync_playwright  # noqa: E402

from shared.src.lib.game.pokemon import battle  # noqa: E402
from shared.src.lib.game.pokemon.memory import ADDR, busy, screen_rows, text_box, text_box_open  # noqa: E402
from shared.src.lib.game.pokemon.rom import GameData  # noqa: E402

KEYS = {"A": "z", "B": "x", "UP": "ArrowUp", "DOWN": "ArrowDown", "LEFT": "ArrowLeft", "RIGHT": "ArrowRight"}


def rom_bytes(path):
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            return z.read(z.namelist()[0])
    return open(path, "rb").read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--chooser", choices=("heuristic", "first", "jev"), default="heuristic")
    ap.add_argument("--jev-bridge", default="ssh server sudo -n -u vpt_user /opt/virtualpytest/venv/bin/python /tmp/jevbridge/jev_bridge.py --decisions-file /tmp/jevbridge/decisions_main.py",
                    help="command of a decision bridge (one JSON per line in and out) on a machine holding the OpenRouter key")
    ap.add_argument("--url", default="http://127.0.0.1:8767/index.html")
    ap.add_argument("--seconds", type=float, default=150)
    a = ap.parse_args()
    rom = rom_bytes(a.rom)
    bridge = None
    if a.chooser == "jev":
        import subprocess
        bridge = subprocess.Popen(a.jev_bridge.split(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        while True:  # skip log lines until the bridge is ready
            line = bridge.stdout.readline()
            if line.startswith("{") and json.loads(line).get("ready"):
                break
    data = GameData(rom)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False)
        page = b.new_page(viewport={"width": 1280, "height": 720})
        page.goto(a.url)
        page.wait_for_function("() => typeof GameBoyCore !== 'undefined'")
        page.evaluate("(r) => vptGB.load(r)", rom.decode("latin-1"))
        page.wait_for_timeout(300)
        page.evaluate("(s) => vptGB.loadState(s)", open(a.state).read())
        page.wait_for_timeout(500)
        read = lambda addr, n=1: page.evaluate(f"() => vptGB.read({addr}, {n})")
        press = lambda k, ms=90, gap=350: (page.keyboard.down(KEYS[k]), page.wait_for_timeout(ms), page.keyboard.up(KEYS[k]), page.wait_for_timeout(gap))
        log, t0, turn = [], time.time(), 0
        while time.time() - t0 < a.seconds:
            kind = read(ADDR["in_battle"])[0]
            if kind == 0 and turn:
                break
            if battle.main_menu_open(read) and read(ADDR["menu_item"])[0] == 0 and read(ADDR["menu_cursor_x"])[0] in (7, 13):
                opts = battle.options(read, data)
                st = battle.state(read)
                extra = ""
                if a.chooser == "jev":
                    bridge.stdin.write(json.dumps({"state": battle.describe(read), "instructions": "Pick the option that wins this battle while keeping our Pokémon healthy.",
                                                   "options": [{"id": o["id"], "facts": battle.option_text(o)} for o in opts]}) + "\n")
                    bridge.stdin.flush()
                    line = bridge.stdout.readline()
                    while not line.startswith("{"):
                        line = bridge.stdout.readline()
                    out = json.loads(line)
                    choice = out.get("choice") or battle.heuristic_choice(opts)
                    extra = f" conf {out.get('confidence')} {out.get('ms')} ms ${out.get('cost')}"
                else:
                    choice = battle.heuristic_choice(opts) if a.chooser == "heuristic" else opts[0]["id"]
                turn += 1
                log.append({"turn": turn, "our_hp": st["ours"]["hp"], "enemy_hp": st["enemy"]["hp"], "choice": choice,
                            "options": {o["id"]: o["facts"] for o in opts}})
                print(f"turn {turn}: our {st['ours']['hp']} / enemy {st['enemy']['hp']} -> {choice}{extra}",
                      {o["id"]: (o["facts"].get("expected_damage"), o["facts"].get("pp_left")) for o in opts}, flush=True)
                opt = next(o for o in opts if o["id"] == choice)
                if read(ADDR["menu_cursor_x"])[0] != 7:
                    press("LEFT")
                press("A", gap=500)  # FIGHT -> move list
                for k in battle.keys_to_menu_item(read(ADDR["menu_item"])[0], opt["slot"]):
                    press(k)
                press("A", gap=600)
            elif text_box_open(read) or busy(read):
                press("A")
            else:
                page.wait_for_timeout(250)
        end = battle.state(read)
        result = {"chooser": a.chooser, "turns": turn, "our_hp": end["ours"]["hp"], "enemy_hp": end["enemy"]["hp"],
                  "won": end["enemy"]["hp"] == 0 and end["ours"]["hp"] > 0, "in_battle": read(ADDR["in_battle"])[0]}
        print(json.dumps(result))
        b.close()


if __name__ == "__main__":
    main()
