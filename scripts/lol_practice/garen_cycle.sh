#!/bin/bash
# One bot cycle from the Mac: deploy the current worktree code to vpt-windows, play a Practice Tool game, fetch the report.
# usage: garen_cycle.sh <label> [seconds] [blue|red] [calib]   (run from the repo/worktree root; needs `ssh vpt-windows` and `ssh proxmox`)
# Prints one JSON summary line. Claims and releases the vpt-windows lease around the run.
set -u
LABEL=${1:?label}; SECS=${2:-480}; TEAM=${3:-blue}; EXTRA=${4:-}
L=shared/src/lib/game/leagueoflegends; B=vpt-windows:C:/virtualpytest
OUTDIR=$HOME/vpt-deliverables/lol-garen-bot/$LABEL; mkdir -p "$OUTDIR"

if ssh vpt-windows 'tasklist /FI "IMAGENAME eq League of Legends.exe"' | grep -q "League of"; then
  echo '{"ok": false, "error": "a game is already running on vpt-windows: not starting"}'; exit 2; fi
LEASE=$(ssh proxmox "~/bin/vpt-lease claim vpt-windows game --agent codebox:lol-aggro --purpose 'Garen bot run $LABEL' --ttl 60" 2>&1 | grep -oE '[0-9a-f]{8}' | head -1)
trap 'ssh proxmox "~/bin/vpt-lease release $LEASE" >/dev/null 2>&1' EXIT

for f in danger_zones turn_log spells outcomes game_input perception lane_map vision_nav garen_bot practice_runner live_recorder scorecard score_run minimap process_utils minion_events minion_track recorder_proc hud_settings cs_reader target_hp; do
  scp -q $L/$f.py $B/virtualpytest/$L/$f.py; done
scp -q $L/nav_templates/*.png $B/virtualpytest/$L/nav_templates/
scp -q $L/cs_digits.npz $L/target_digits.npz $B/virtualpytest/$L/
scp -q docs/agent/game/lol/champions/garen.yaml $B/virtualpytest/docs/agent/game/lol/champions/garen.yaml
scp -q scripts/lol_practice/run_garen_bot.py $B/run_garen_bot.py
ssh vpt-windows 'del C:\virtualpytest\garen-last.txt 2>nul'
ssh vpt-windows "schtasks /Create /TN BotRun /TR \"C:\\virtualpytest\\virtualpytest\\venv\\Scripts\\pythonw.exe C:\\virtualpytest\\run_garen_bot.py $SECS $TEAM $EXTRA\" /SC ONCE /ST 00:00 /RU joach /IT /RL HIGHEST /F >nul & schtasks /Run /TN BotRun" >/dev/null 2>&1
for i in $(seq 1 $(( (SECS + 300) / 10 ))); do
  ssh vpt-windows 'if exist C:\virtualpytest\garen-last.txt (echo DONE)' | grep -q DONE && break; sleep 10; done
D=$(ssh vpt-windows 'type C:\virtualpytest\garen-last.txt' 2>/dev/null | tr -d '\r' | sed 's#^C:irtualpytest#C:\\virtualpytest#')
NAME=$(basename "$(echo "$D" | tr '\\' '/')")
scp -q -r "vpt-windows:C:/virtualpytest/$NAME" "$OUTDIR/" 2>/dev/null
python3 - "$OUTDIR/$NAME" <<'PY'
import json, sys, os
d = sys.argv[1]
try:
    r = json.load(open(os.path.join(d, "result.json")))
    tl = json.load(open(os.path.join(d, "timeline.json")))
    last = tl["samples"][-1] if tl.get("samples") else {}
    print(json.dumps({"ok": r.get("ok"), "folder": d, "overall": r.get("overall"), "areas": r.get("areas"),
                      "scores": last.get("scores"), "items": last.get("items"), "bot": r.get("bot"),
                      "actions": r.get("actions_by_kind"), "fights": len(tl.get("fights", [])),
                      "video": r.get("video"), "exit": r.get("exit"), "error": r.get("exception", "")[-300:]}))
except Exception as e:
    print(json.dumps({"ok": False, "folder": d, "error": str(e)}))
PY
