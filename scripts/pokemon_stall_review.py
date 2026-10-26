#!/usr/bin/env python3
"""Review a Pokémon long-play stall (TASK-33): diagnose it, or diagnose AND fix it (`--fix`).

The stalled run writes a report (shared/src/lib/game/pokemon/stall.py: milestone, map, position, last 30
events, last strategist plan, save names, run id). That file is the whole brief. Without `--fix` a Sonnet agent
(`claude -p`) writes a diagnosis next to the report. With `--fix` the brief also has the agent ship the fix
(worktree, test, merge, push, deploy the host the run used, clear the lock) before the next slot: the codebox
watcher `scripts/agent/pokemon_stall_watch.sh` starts that one by itself within a minute of a stall.

  python3 scripts/pokemon_stall_review.py /var/lib/vpt-private/pokemon/stall_latest_20261014-190000.json
  python3 scripts/pokemon_stall_review.py <report> --print     # only show the prompt
  python3 scripts/pokemon_stall_review.py <report> --fix --print > brief.md   # what the watcher hands to cbsession

Run it where the repo and the claude CLI are (codebox). The report and saves are private: copy the report
(not the saves) off the host if needed; the review reads the saves from `private_dir` only when it runs
on the host that holds them.
"""

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

BRIEF = """You are diagnosing a stall of VirtualPyTest's Pokémon Blue long-play runner (TASK-33). Do not fix code and do not commit:
write a diagnosis only.

Read first: docs/tasks/TASK-33-handover.md, shared/src/lib/game/pokemon/runner.py (the milestone named below) and
shared/src/lib/game/pokemon/milestones.py. The stall report follows as JSON (reason, milestone, map, pos, the last 30 events,
the last strategist plan, the save names, the run id).

Questions to answer:
1. What is the runner trying to do at this milestone, and what does the game do instead? Quote the events that show it.
2. Root cause in the code or in the game's rules (name file:line). Use public Gen 1 knowledge where it helps; say when it is a guess.
3. The smallest fix and a unit test that would have caught it (tests/shared/test_pokemon.py style).
4. How to reproduce locally: the saves are private (never copy them into the repo or print their contents); on codebox copy
   state/memory into ~/vpt-private/pokemon/ and use test_scripts/game/local/pokemon_play_local.py.
5. Whether a memo flag (stuck counters, bad_warps, walls, key_guard_talks...) is poisoning the memory and should be cleared.

Write the diagnosis to: {out}

STALL REPORT
{report}
"""


FIX_BRIEF = """You are fixing a stall of VirtualPyTest's Pokémon Blue long-play runner (TASK-33), unattended. The codebox
dispatcher `scripts/agent/pokemon_dispatch.py` plays the save every 15 min on the first free host of {hosts}; this stall
happened on {host}. It starts no run while the save is locked, so every minute you take is lost play. Goal: the fix deployed
and the lock cleared within about 30 minutes.

Owner rules (AGENTS.md): do not ask anyone to start, merge, push, deploy or clear the lock. Do it, then report it. Never edit the
saved memory by hand, never print or copy the saves into the repo. Hold a host lease only while you deploy.

1. Read docs/tasks/TASK-33-handover.md (latest sections first), shared/src/lib/game/pokemon/runner.py at the milestone below,
   milestones.py, and `git log --oneline -15 -- shared/src/lib/game/pokemon` plus `git branch -r | grep -i pokemon`: another
   session may already be shipping a fix for this very stall. If one is merged or mid-merge, build on it instead of a second fix.
   Read those from the tree you start in ({repo}): it is a clone of origin/main, put on the current main when you were started.
   Do not read the code from ~/virtualpytest - that is the shared checkout of every session on this host and it is usually
   behind (on 2026-10-26 it was a day old, and a fixer that read it reproduced a bug main had already fixed).
2. Diagnose: what the runner tries, what the game does instead (quote the events), root cause with file:line. Write it to {out}.
3. Fix it, smallest change, in your own worktree off main (`git worktree add ~/virtualpytest-<slug> -b fix/pokemon-<slug> main`),
   with a guard test in tests/shared/test_pokemon.py. Run `python3 -m pytest -q tests/shared/test_pokemon.py` once.
   The `git worktree add` runs in {repo}, so its `main` is the current one.
   A defer flag (`*_deferred`) is a last resort and never the fix for a goal the game needs later: a story that ends while a
   flag is set is itself a stall (`deferred_end`). On a `deferred_end` stall the job is the real thing the flags skipped
   (e.g. get a Surf or Strength learner into the party), then clear the flag. Check `deferred` in the report.
4. Add a BUG-*.md and a release-note line, merge to main (`git merge --no-ff`), push, delete the branch and worktree.
5. Deploy every Pokémon host (pinned ones must be named): skill `deploy`, `vpt-lease check node1-vpt <host>`, then
   `ssh proxmox "VPT_LEASE_AGENT=codebox:pokemon-stall bash update_core.sh main --host --hosts {hosts}"`.
6. Clear the lock: `{clear_cmd}` (the next dispatcher tick, within a minute, starts a run with `--clear_stall yes` on a free host). Then `pokemon_dispatch.py status` and check that run moves (a new map, square
   or milestone in its events, and more than a few ticks: a run that ends after 1 tick is not fixed).
7. Add a short entry to TASK-33-handover.md. End with `STATUS: done — <fix, commit, deployed version>`.

The stall report follows as JSON (reason, milestone, map, pos, the last 30 events, the last strategist plan, the save names,
the run id). The canonical saves are on codebox in ~/vpt-private/pokemon/canonical (state_latest.json, memory_latest.json):
copy them to ~/vpt-private/pokemon/ to reproduce with test_scripts/game/local/pokemon_play_local.py.

STALL REPORT
{report}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report", help="path of the stall report JSON (stall_<save>_<run>.json)")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--print", action="store_true", help="print the prompt and stop")
    ap.add_argument("--fix", action="store_true", help="the brief has the agent ship the fix and clear the lock, not only diagnose")
    ap.add_argument("--host", default="", help="host the stalled run played on (named in the --fix brief)")
    ap.add_argument("--repo", default="", help="the tree the fixing session starts in (named in the --fix brief)")
    ap.add_argument("--save", default="", help="the save the stall names (the clear command in the --fix brief)")
    a = ap.parse_args()
    report_path = os.path.abspath(a.report)
    report = json.load(open(report_path))
    if report.get("kind") != "pokemon_stall":
        sys.exit(f"{report_path} is not a Pokémon stall report")
    out = os.path.splitext(report_path)[0] + ".diagnosis.md"
    if a.fix:
        hosts = os.environ.get("POKEMON_HOSTS", "host-clone-1,host-clone-2")
        # The clear must name the save the stall is about: the plain command only clears the first lane's
        # save, and the second lane stayed locked for 5 h 30 because of it (2026-10-26).
        clear_cmd = "python3 scripts/agent/pokemon_dispatch.py clear-stall"
        if a.save:
            clear_cmd += f" --save {a.save}"
        prompt = FIX_BRIEF.format(out=out, hosts=hosts, host=a.host or "one of them", repo=a.repo or "the tree you start in",
                                  clear_cmd=clear_cmd, report=json.dumps(report, indent=1))
    else:
        prompt = BRIEF.format(out=out, report=json.dumps(report, indent=1))
    if a.print:
        print(prompt)
        return
    cmd = ["claude", "-p", "--model", a.model, "--permission-mode", "acceptEdits", "--output-format", "json", prompt]
    print(f"{a.model} {'fix' if a.fix else 'review'} of the {report['milestone']} stall (run {report['run_id']}) -> {out}", flush=True)
    run = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, text=True)
    try:
        result = json.loads(run.stdout)
        print(result.get("result", ""))
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from ai_report_claude_cli import report as report_cli  # every model call lands in ai_calls (BUG-0721)
        report_cli(result, "pokemon_stall_review.py")
    except ValueError:
        print(run.stdout)
    sys.exit(run.returncode)


if __name__ == "__main__":
    main()
