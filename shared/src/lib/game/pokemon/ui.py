"""
Build the pokemon-blue-web userinterface (TASK-33 phase 4c) as a .vptree bundle.

  entry -> game        open the emulator page served by serve.GameServer (127.0.0.1, private)

Web only (host_vnc). Everything else is the runner: memory snapshots and held buttons through
execute_javascript actions (runner.SnapshotIO + the script's IO).

Usage:
  python -m shared.src.lib.game.pokemon.ui --out /tmp/pokemon     # writes pokemon-blue-web.vptree
Then import it: POST /server/userinterface/import (file=pokemon-blue-web.vptree, name=pokemon-blue-web).
"""

import argparse
import os
import uuid

from ..vptree import edge, manifest, node, write_bundle
from .serve import PORT

UI_NAME = "pokemon-blue-web"
MODELS = ["web"]


def build_manifest(port: int = PORT):
    tree_id = str(uuid.uuid4())
    check = {"verification_type": "web", "command": "waitForElementToAppear",
             "params": {"search_term": "#screen", "timeout": 15000}}
    nodes = [node(tree_id, "entry-node", "Entry", "entry", 0, 0),
             node(tree_id, "game", "game", "screen", 0, 200, [check])]
    edges = [edge(tree_id, "entry-node", "game", [
        {"command": "open_browser", "action_type": "web", "params": {"wait_time": 1000}},
        {"command": "navigate_to_url", "action_type": "web",
         "params": {"url": f"http://127.0.0.1:{port}/index.html", "wait_time": 3000}},
    ])]
    return manifest(UI_NAME, MODELS, tree_id, nodes, edges)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"{UI_NAME}.vptree")
    write_bundle(path, build_manifest())
    print(f"{UI_NAME}: {path}")


if __name__ == "__main__":
    main()
