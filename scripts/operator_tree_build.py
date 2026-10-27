#!/usr/bin/env python3
"""One Forge `build-tree-web` chat for an operator web app (TASK-178), reusing the UC-04 chat driver.

    UC04_DIR=~/vpt-deliverables/<operator>-web UC04_HOST=host-clone-2 UC04_DEVICE=host \
        python3 scripts/operator_tree_build.py --ui web-<operator> --max-nodes 12

The folder holds prompt.md and target.env (URL, and the login as `{env:<CODENAME>_APP_LOGIN}` /
`{env:<CODENAME>_APP_PASSWORD}` placeholders: the host resolves them when it types, see secret_text.py).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench_tree_build as b  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ui", required=True)
    ap.add_argument("--max-nodes", type=int, default=12)
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--tag", default="run1")
    a = ap.parse_args()
    t = b.target()
    _, prompt, _ = b.build_prompt(t, a.ui, a.max_nodes)
    d = b.run_dir(f"{a.ui}-{a.tag}")
    res = b.chat(prompt, a.ui, os.path.join(d, "events.jsonl"), [], a.max_nodes, a.timeout)
    json.dump(res, open(os.path.join(d, "run.json"), "w"), indent=1)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
