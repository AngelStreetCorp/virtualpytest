#!/usr/bin/env python3
"""
AI bridge for local game runs (TASK-33 4b): one JSON request per line on stdin, one result per line
on stdout.
- {state, options: [{id, facts}], instructions} -> decisions.choose (Jev): {success, choice,
  confidence, probabilities, usage, cost, ms, model, error}
- {op: "complete", prompt, system} -> gateway.complete("text.game_strategy"): {success, content,
  model, error, usage}

It must run where the OpenRouter key is (VM 103, as vpt_user): decision models are server-side only
(shared/src/lib/ai/decisions.py). Runs from the deployed tree; --decisions-file loads a newer
decisions.py when the deployed build predates it.

  ssh server sudo -n -u vpt_user /opt/virtualpytest/venv/bin/python <path>/jev_bridge.py [--decisions-file <path>]
"""

import argparse
import importlib.util
import json
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--root", default="/opt/virtualpytest")
ap.add_argument("--profile", default="jev")
ap.add_argument("--team-id", default="7fdeb4bb-3639-4ec3-959f-b54769a219ce")
ap.add_argument("--decisions-file", default="")
a = ap.parse_args()
sys.path.insert(0, a.root)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(f"{a.root}/.env")
from shared.src.lib.ai import router, usages  # noqa: E402

if a.decisions_file:
    spec = importlib.util.spec_from_file_location("shared.src.lib.ai.decisions", a.decisions_file)
    decisions = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = decisions
    spec.loader.exec_module(decisions)
else:
    from shared.src.lib.ai import decisions  # noqa: E402
if "text.decision" not in usages.USAGES:  # a deployed build older than the key
    usages.register(usages._u("text.decision", "Decision (closed choice)", "Decision models picking among options (TASK-38)"))

if "text.game_strategy" not in usages.USAGES:
    usages.register(usages._u("text.game_strategy", "Game strategist", "Long-term plan of a game-playing run (TASK-33)", "text"))
from shared.src.lib.ai import gateway  # noqa: E402

gateway.use_local_routing()
resolution = router.resolve_profile(a.profile, "text.decision", a.team_id)
print(json.dumps({"ready": True}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    if req.get("op") == "complete":
        out = gateway.complete("text.game_strategy", req["prompt"], system=req.get("system"), max_tokens=500,
                               team_id=a.team_id)
        print(json.dumps({k: out.get(k) for k in ("success", "content", "model", "error", "usage")}), flush=True)
        continue
    # Not logged to ai_decisions: a run makes thousands of moves, and the game keeps its own trace.
    out = decisions.choose(resolution, state=req["state"], options=req["options"], instructions=req["instructions"],
                           log=False)
    print(json.dumps({k: out.get(k) for k in ("success", "choice", "confidence", "probabilities", "error", "usage",
                                               "cost", "ms", "model")}), flush=True)
