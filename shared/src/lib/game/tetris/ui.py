"""
Build the tetris-web userinterface (TASK-33 phase 3) as a .vptree bundle.

  entry -> game --+-- start / rotate / left / right / down / quit   (action nodes, one key each)
                  +-- game_over                                       (checked; no-op action)

Web only (host_vnc). The runner reads the key actions of the action nodes once and fires them
in batches through the action executor (runner.py); navigation is used for entry, start and
the game-over check.

Usage:
  python -m shared.src.lib.game.tetris.ui --out /tmp/tetris     # writes tetris-web.vptree
Then import it: POST /server/userinterface/import (file=tetris-web.vptree, name=tetris-web).
"""

import argparse
import os
import uuid

from ..vptree import edge, manifest, node, write_bundle
from .runner import UI_NAME

URL = "https://jakesgordon.com/games/tetris/"
MODELS = ["web"]

# The "Press Space to Play." line is hidden with an inline `visibility: hidden` while a game
# runs. The web check passes on any element with a layout box (hidden ones too), so the
# checks match on that inline style instead.
GAME_OVER_SELECTOR = '#start:not([style*="hidden"])'


def _key(key, wait=0):
    return [{"command": "press_key", "action_type": "web", "params": {"key": key, "wait_time": wait}}]


def build_manifest():
    tree_id = str(uuid.uuid4())
    game_check = {"verification_type": "web", "command": "waitForElementToAppear",
                  "params": {"search_term": "#canvas", "timeout": 10000}}
    over_check = {"verification_type": "web", "command": "waitForElementToAppear",
                  "params": {"search_term": GAME_OVER_SELECTOR, "timeout": 5000}}
    enter = [
        {"command": "open_browser", "action_type": "web", "params": {"wait_time": 1000}},
        {"command": "navigate_to_url", "action_type": "web", "params": {"url": URL, "wait_time": 2000}},
    ]
    nodes = [
        node(tree_id, "entry-node", "Entry", "entry", 0, 0),
        node(tree_id, "game", "game", "screen", 0, 200, [game_check]),
        node(tree_id, "game_over", "game_over", "screen", 300, 200, [over_check]),
    ]
    edges = [
        edge(tree_id, "entry-node", "game", enter, wait=500),
        # The graph drops edges without actions: a no-op.
        edge(tree_id, "game", "game_over",
             [{"command": "execute_javascript", "action_type": "web", "params": {"script": "() => true", "wait_time": 300}}]),
    ]
    keys = [("start", "SPACE", 300), ("rotate", "UP", 0), ("left", "LEFT", 0), ("right", "RIGHT", 0),
            ("down", "DOWN", 0), ("quit", "ESCAPE", 300)]
    for i, (node_id, key, wait) in enumerate(keys):
        nodes.append(node(tree_id, node_id, node_id, "action", -375 + 150 * i, 400, parent="game"))
        edges.append(edge(tree_id, "game", node_id, _key(key, wait), back=True))
    return manifest(UI_NAME, MODELS, tree_id, nodes, edges)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="Output directory for the .vptree bundle")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{UI_NAME}.vptree")
    write_bundle(path, build_manifest())
    print(f"{UI_NAME}: {path}")


if __name__ == "__main__":
    main()
