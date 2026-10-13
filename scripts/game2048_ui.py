#!/usr/bin/env python3
"""
Build the 2048 showcase user interfaces (TASK-33) as .vptree bundles.

Two UIs with the same tree; only the actions and node checks differ:

  entry -> game --+-- move_left / move_right / move_up / move_down   (action nodes)
                  +-- new_game                                        (action node)
                  +-- game_over                                       (checked; no-op action)

  game2048-web             web / host_vnc: Playwright navigate, arrow keys, JS for cookies + New Game
  game2048-android-mobile  android_mobile: Chrome via open_url, swipes, tap New Game + OK

Mobile swipe/tap coordinates are for a 1080x2340 phone (S21 FE) with the page at its
default zoom; the board centre is at (540, 1424).

Usage:
  python scripts/game2048_ui.py --out /tmp/game2048          # writes <name>.vptree per UI
Then import each bundle: POST /server/userinterface/import (file=<bundle>, name=<name>).
"""

import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from shared.src.lib.game.vptree import edge, manifest, node, write_bundle  # noqa: E402

URL = "https://classic.play2048.co/"

# Web: cookie wall (Ezoic, loads after the game) - poll for it for up to ~8 s.
JS_DISMISS_CONSENT = (
    "async () => { for (let i = 0; i < 32; i++) { const b = document.getElementById('ez-accept-necessary');"
    " if (b && b.offsetParent !== null) { b.click(); return true; } await new Promise(r => setTimeout(r, 250)); }"
    " return false; }"
)
# Web: the host's VNC display is 1280x720 - zoom the page out so the whole board is on screen
# (board ~275 px, tiles ~58 px) for the pixel reader.
JS_FIT_BOARD = "() => { document.body.style.zoom = '0.55'; window.scrollTo(0, 0); return true; }"
# Web: New Game mid-game asks confirm(); Playwright auto-dismisses dialogs, so accept it here.
JS_NEW_GAME = (
    "() => { const b = document.querySelector('.restart-button'); if (!b) return false;"
    " const c = window.confirm; window.confirm = () => true;"
    " try { b.click(); } finally { window.confirm = c; } return true; }"
)

MOBILE_BOARD_CENTRE = (540, 1424)
MOBILE_SWIPE = 200  # half length in px
MOBILE_NEW_GAME = (885, 884)
# Phone checks OCR an area of the HDMI capture (1280x720), never the full frame: on the full
# frame tesseract's output varies between identical frames (empty, "2048", or skipping the
# "Game over!" overlay), see BUG-0217. Board and header, each with a ~20 px margin.
MOBILE_CAPTURE_BOARD_AREA = {"x": 490, "y": 290, "width": 300, "height": 300}
MOBILE_CAPTURE_HEADER_AREA = {"x": 480, "y": 180, "width": 320, "height": 120}


def web_actions():
    return {
        "enter": [
            {"command": "open_browser", "action_type": "web", "params": {"wait_time": 1000}},
            {"command": "navigate_to_url", "action_type": "web", "params": {"url": URL, "wait_time": 2000}},
            {"command": "execute_javascript", "action_type": "web", "params": {"script": JS_DISMISS_CONSENT, "wait_time": 500}},
            {"command": "execute_javascript", "action_type": "web", "params": {"script": JS_FIT_BOARD, "wait_time": 500}},
        ],
        "new_game": [
            {"command": "execute_javascript", "action_type": "web", "params": {"script": JS_NEW_GAME, "wait_time": 500}},
        ],
        "moves": {d: [{"command": "press_key", "action_type": "web", "params": {"key": d}}]
                  for d in ("LEFT", "RIGHT", "UP", "DOWN")},
        # The graph drops edges without actions: a no-op that lets the overlay fade in (~2 s).
        "to_game_over": [
            {"command": "execute_javascript", "action_type": "web", "params": {"script": "() => true", "wait_time": 2000}},
        ],
        "game_check": {"verification_type": "web", "command": "waitForElementToAppear",
                       "params": {"search_term": ".restart-button", "timeout": 10000}},
        "over_check": {"verification_type": "web", "command": "waitForElementToAppear",
                       "params": {"search_term": ".game-over", "timeout": 5000}},
    }


def mobile_actions():
    cx, cy = MOBILE_BOARD_CENTRE
    s = MOBILE_SWIPE
    swipes = {
        "LEFT": (cx + s, cy, cx - s, cy),
        "RIGHT": (cx - s, cy, cx + s, cy),
        "UP": (cx, cy + s, cx, cy - s),
        "DOWN": (cx, cy - s, cx, cy + s),
    }
    return {
        "enter": [
            {"command": "open_url", "action_type": "remote",
             "params": {"url": URL, "package": "com.android.chrome", "wait_time": 4000}},
        ],
        # Only used mid-game (the script checks), where the page always asks for confirmation.
        "new_game": [
            {"command": "tap_coordinates", "action_type": "remote",
             "params": {"x": MOBILE_NEW_GAME[0], "y": MOBILE_NEW_GAME[1], "wait_time": 1000}},
            {"command": "click_element", "action_type": "remote", "params": {"element_id": "OK", "wait_time": 800}},
        ],
        "moves": {d: [{"command": "swipe", "action_type": "remote",
                       "params": {"from_x": fx, "from_y": fy, "to_x": tx, "to_y": ty, "duration": 150}}]
                  for d, (fx, fy, tx, ty) in swipes.items()},
        # The graph drops edges without actions: a read-only UI dump while the overlay fades in.
        "to_game_over": [
            {"command": "dump_elements", "action_type": "remote", "params": {"wait_time": 2000}},
        ],
        "game_check": {"verification_type": "text", "command": "waitForTextToAppear",
                       "params": {"text": "2048", "timeout": 10000, "area": MOBILE_CAPTURE_HEADER_AREA}},
        "over_check": {"verification_type": "text", "command": "waitForTextToAppear",
                       "params": {"text": "Game over", "timeout": 5000, "area": MOBILE_CAPTURE_BOARD_AREA}},
    }


def build_manifest(name, models, spec):
    tree_id = str(uuid.uuid4())
    nodes = [
        node(tree_id, "entry-node", "Entry", "entry", 0, 0),
        node(tree_id, "game", "game", "screen", 0, 200, [spec["game_check"]]),
        node(tree_id, "game_over", "game_over", "screen", 300, 200, [spec["over_check"]]),
        node(tree_id, "new_game", "new_game", "action", -300, 400, parent="game"),
    ]
    edges = [
        edge(tree_id, "entry-node", "game", spec["enter"], wait=1000),
        edge(tree_id, "game", "game_over", spec["to_game_over"], wait=0),
        edge(tree_id, "game", "new_game", spec["new_game"], wait=500, back=True),
    ]
    for i, direction in enumerate(("LEFT", "RIGHT", "UP", "DOWN")):
        node_id = f"move_{direction.lower()}"
        nodes.append(node(tree_id, node_id, node_id, "action", -150 + 150 * i, 400, parent="game"))
        edges.append(edge(tree_id, "game", node_id, spec["moves"][direction], wait=0, back=True))
    return manifest(name, models, tree_id, nodes, edges)


UIS = {
    "game2048-web": (["web"], web_actions),
    "game2048-android-mobile": (["android_mobile"], mobile_actions),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="Output directory for the .vptree bundles")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for name, (models, spec) in UIS.items():
        path = os.path.join(args.out, f"{name}.vptree")
        write_bundle(path, build_manifest(name, models, spec()))
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
