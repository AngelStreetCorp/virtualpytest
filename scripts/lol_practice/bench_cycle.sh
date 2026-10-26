#!/bin/bash
# TASK-134: one benchmark game from the Mac. usage: bench_cycle.sh <rule|claude-haiku-5-5|claude-sonnet-5-5> <label> [blue|red]
# (run from the repo/worktree root). Needs `ssh vpt-windows`, `ssh proxmox`, and the relay (scripts/lol_practice/llm_relay.py) on :8787.
# Waits for a free vpt-windows/game lease, deploys this tree's lol code, runs the game (5:00 game time), fetches the run folder,
# releases the lease. Prints one JSON line. Never starts when a League game is already running.
set -u
MODEL=${1:?model}; LABEL=${2:?label}; TEAM=${3:-blue}; EXTRA=${4:-}   # EXTRA=enemytop: an enemy bot lanes top
L=shared/src/lib/game/leagueoflegends; B=vpt-windows:C:/virtualpytest
OUTDIR=${BENCH_OUT:-$HOME/vpt-deliverables/lol-model-benchmark}/$LABEL; mkdir -p "$OUTDIR"

LEASE=""
for i in $(seq 1 360); do   # wait up to 3 h for the lease, 30 s apart
  if ! ssh vpt-windows 'tasklist /FI "IMAGENAME eq League of Legends.exe"' | grep -q "League of"; then
    LEASE=$(ssh proxmox "~/bin/vpt-lease claim vpt-windows game --agent mac:task-134 --purpose 'model benchmark $LABEL' --ttl 60" 2>&1 | grep -oE '[0-9a-f]{8}' | head -1)
    # a refusal message also contains 8-hex ids (the holder's): the claim only counts when the list shows it as ours
    ssh proxmox "~/bin/vpt-lease list" | grep -q "^$LEASE .*agent=mac:task-134" && break
    LEASE=""
  fi
  sleep 30
done
[ -z "$LEASE" ] && { echo '{"ok": false, "error": "no free lease in 3 h"}'; exit 3; }
TUN=""
cleanup() { [ -n "$TUN" ] && kill $TUN 2>/dev/null; ssh proxmox "~/bin/vpt-lease release $LEASE" >/dev/null 2>&1; }
trap cleanup EXIT

ssh -N -R 8787:127.0.0.1:8787 -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 vpt-windows & TUN=$!
# Own folder on the box (C:\virtualpytest\bench): the bot session deploys run_garen_bot.py / garen_bot.py to C:\virtualpytest and
# the two must never overwrite each other. The bench copy of the lib starts from the box's shared copy, then this tree's files go over it.
R=C:/virtualpytest/bench/vpt
ssh vpt-windows 'if not exist C:\virtualpytest\bench\vpt mkdir C:\virtualpytest\bench\vpt & xcopy /E /I /Y /Q C:\virtualpytest\virtualpytest\shared C:\virtualpytest\bench\vpt\shared >nul & if not exist C:\virtualpytest\bench\vpt\docs\agent\game\lol\champions mkdir C:\virtualpytest\bench\vpt\docs\agent\game\lol\champions' >/dev/null 2>&1
for f in $L/*.py; do scp -q "$f" vpt-windows:$R/$L/$(basename "$f"); done
for f in $L/nav_templates/*.png; do scp -q "$f" vpt-windows:$R/$L/nav_templates/$(basename "$f"); done
scp -q docs/agent/game/lol/basics.md vpt-windows:$R/docs/agent/game/lol/basics.md
scp -q docs/agent/game/lol/champions/garen.yaml vpt-windows:$R/docs/agent/game/lol/champions/garen.yaml
# the bench copy of run_garen_bot.py writes bench-run-* / bench-last.txt and imports the bench lib, never the other session's
sed -e 's#C:\\virtualpytest\\virtualpytest#C:\\virtualpytest\\bench\\vpt#; s#garen-run-#bench-run-#; s#garen-last.txt#bench-last.txt#' scripts/lol_practice/run_garen_bot.py > $TMPDIR/bench_run_garen_bot.py
scp -q $TMPDIR/bench_run_garen_bot.py vpt-windows:C:/virtualpytest/bench/run_garen_bot.py
scp -q scripts/lol_practice/run_llm_bench.py vpt-windows:C:/virtualpytest/bench/run_llm_bench.py
ssh vpt-windows 'del C:\virtualpytest\bench-last.txt 2>nul'
ssh vpt-windows 'tasklist /FI "IMAGENAME eq League of Legends.exe"' | grep -q "League of" && { echo '{"ok": false, "error": "a game started meanwhile: not launching"}'; exit 2; }
ssh vpt-windows "schtasks /Create /TN BenchRun /TR \"C:\\virtualpytest\\virtualpytest\\venv\\Scripts\\pythonw.exe C:\\virtualpytest\\bench\\run_llm_bench.py $MODEL 420 $TEAM $EXTRA\" /SC ONCE /ST 00:00 /RU joach /IT /RL HIGHEST /F >nul & schtasks /Run /TN BenchRun" >/dev/null 2>&1
# the game must be up within 3 minutes
sleep 180
ssh vpt-windows 'tasklist /FI "IMAGENAME eq League of Legends.exe"' | grep -q "League of" || echo "WARN: no League of Legends.exe 3 min after launch" >&2
for i in $(seq 1 90); do
  ssh vpt-windows 'if exist C:\virtualpytest\bench-last.txt (echo DONE)' | grep -q DONE && break; sleep 10; done
D=$(ssh vpt-windows 'type C:\virtualpytest\bench-last.txt' 2>/dev/null | tr -d '\r')
NAME=$(basename "$(echo "$D" | tr '\\' '/')")
scp -q -r "vpt-windows:C:/virtualpytest/$NAME" "$OUTDIR/" 2>/dev/null
python3 -c "import json,sys;r=json.load(open('$OUTDIR/$NAME/result.json'));sys.exit(0 if r.get('ok') else 1)" 2>/dev/null || { echo "{\"ok\": false, \"error\": \"invalid game (start or run failed, see result.json)\", \"label\": \"$LABEL\", \"folder\": \"$OUTDIR/$NAME\"}"; exit 5; }
# the folder must be this run's: contestant "rule" or the model named in llm_summary.json
grep -q "\"model\": \"$MODEL\"" "$OUTDIR/$NAME/llm_summary.json" 2>/dev/null || { echo "{\"ok\": false, \"error\": \"fetched run is not this contestant's\", \"label\": \"$LABEL\"}"; exit 4; }
echo "{\"label\": \"$LABEL\", \"model\": \"$MODEL\", \"folder\": \"$OUTDIR/$NAME\"}"
