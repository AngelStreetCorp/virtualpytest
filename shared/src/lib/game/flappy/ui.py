"""
Build the flappy-web userinterface (TASK-33 phase 3c) as a .vptree bundle.

  entry -> game --+-- start        (action node: reload the page, then Space: a fresh game)
                  +-- game_over    (checked; no-op action)

Web only (host_vnc). The flying itself is one execute_javascript action per step (runner.py).

Usage:
  python -m shared.src.lib.game.flappy.ui --out /tmp/flappy          # writes flappy-web.vptree
  python -m shared.src.lib.game.flappy.ui --out /tmp/flappy --url http://127.0.0.1:8765/
Then import it: POST /server/userinterface/import (file=flappy-web.vptree, name=flappy-web).
"""

import argparse
import os
import uuid

from ..vptree import edge, manifest, node, write_bundle
from .runner import UI_NAME

URL = "https://nebezb.com/floppybird/"
MODELS = ["web"]


def build_manifest(url: str = URL):
    tree_id = str(uuid.uuid4())
    game_check = {"verification_type": "web", "command": "waitForElementToAppear",
                  "params": {"search_term": "#gamescreen", "timeout": 10000}}
    # #scoreboard is display:none (no layout box) until the bird dies.
    over_check = {"verification_type": "web", "command": "waitForElementToAppear",
                  "params": {"search_term": "#scoreboard", "timeout": 8000}}
    nodes = [
        node(tree_id, "entry-node", "Entry", "entry", 0, 0),
        node(tree_id, "game", "game", "screen", 0, 200, [game_check]),
        node(tree_id, "game_over", "game_over", "screen", 300, 200, [over_check]),
        node(tree_id, "start", "start", "action", -150, 400, parent="game"),
    ]
    edges = [
        edge(tree_id, "entry-node", "game", [
            {"command": "open_browser", "action_type": "web", "params": {"wait_time": 1000}},
            {"command": "navigate_to_url", "action_type": "web", "params": {"url": url, "wait_time": 2500}},
        ], wait=0),
        edge(tree_id, "game", "start", [
            {"command": "navigate_to_url", "action_type": "web", "params": {"url": url, "wait_time": 2500}},
            {"command": "press_key", "action_type": "web", "params": {"key": "SPACE", "wait_time": 0}},
        ], back=True),
        # The graph drops edges without actions: a no-op.
        edge(tree_id, "game", "game_over",
             [{"command": "execute_javascript", "action_type": "web", "params": {"script": "() => true", "wait_time": 0}}]),
    ]
    return manifest(UI_NAME, MODELS, tree_id, nodes, edges)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="Output directory for the .vptree bundle")
    parser.add_argument("--url", default=URL, help="The game page (default: the public one)")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{UI_NAME}.vptree")
    write_bundle(path, build_manifest(args.url))
    print(f"{UI_NAME}: {path}")


if __name__ == "__main__":
    main()
