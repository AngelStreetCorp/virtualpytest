#!/usr/bin/env bash
# time_one_testcase.sh -- run ONE existing testcase through MCP and print where its time went.
#
# Needs the phase timing of feat/testcase-step-timing on the target host: execution.txt lines
# stamped 'HH:MM:SS.mmmZ +SSS.sss' and '⏱ <phase> <ms> ms' lines (see
# shared/src/lib/utils/phase_timing.py). Without it the timeline below is empty: put it on the
# host with scripts/debug/host_deploy.sh (pack / deploy / restore; recipe in its header).
#
# Run it on proxmox node 3 (it has psql to the VPT DB, the QualiAi preprod .env with the MCP
# token and its R2 storage client, and ssh to the host-clones):
#
#   bash time_one_testcase.sh                       # defaults below: host-clone-3, TodoMVC 03
#   HOST_NAME=host-clone-3 HOST_IP=192.168.0.111 TESTCASE=... UI=... bash time_one_testcase.sh
#
# ~2.5-3 minutes for the default testcase. Writes everything to $OUT_DIR:
#   mcp_response.txt  execution.txt  journal.txt  execution_results.csv  script_result.txt
#   timeline.txt (also printed)
#
# It never prints the MCP token. It refuses to start while the host is busy (a script_results
# row still running on it, a live-acceptance run pinned to it, or a Chromium open there) and
# polls every minute for up to WAIT_MAX_S instead; FORCE=1 skips the check.
set -euo pipefail

HOST_NAME="${HOST_NAME:-host-clone-3}"
HOST_IP="${HOST_IP:-192.168.0.111}"
DEVICE_ID="${DEVICE_ID:-host}"
TESTCASE="${TESTCASE:-TC_ACCEPTANCE_TODOMVC_FULL_20260929_03_delete_completed_todo}"
UI="${UI:-acceptance-todomvc-full-20260929-web}"
MCP_URL="${MCP_URL:-https://virtualpytest.qualiai.io/server/mcp}"
QUALIAI_DIR="${QUALIAI_DIR:-/opt/qualiai-preprod}"
PG="${PG:-postgresql://postgres:postgres@192.168.0.102:54322/postgres}"
WAIT_MAX_S="${WAIT_MAX_S:-1800}"
OUT_DIR="${OUT_DIR:-/tmp/vpt-timing/$(date -u +%Y%m%dT%H%M%SZ)_${HOST_NAME}}"
mkdir -p "$OUT_DIR"

psql_q() { psql "$PG" -X -A -t -F '|' -c "$1"; }
log() { echo "[time_one_testcase] $(date -u +%H:%M:%S) $*" >&2; }

host_busy() {
  local running acc chrome
  # record_script_execution_start writes a temporary completed_at = started_at, so a running
  # row is one whose completed_at is NULL or still within 2 s of started_at.
  running=$(psql_q "select count(*) from script_results where host_name='${HOST_NAME}'
                    and started_at > now() - interval '30 minutes'
                    and (completed_at is null or completed_at - started_at < interval '2 seconds');")
  # Real node processes only: a shell whose command line merely mentions them must not count.
  acc=$(pgrep -a -x node | grep 'live-acceptance' | grep -c -- "${HOST_NAME}" || true)
  chrome=$(ssh -o ConnectTimeout=10 "$HOST_IP" "pgrep -c -f 'chrom(e|ium).*remote-debugging' || true" 2>/dev/null || echo "?")
  echo "running_rows=${running} live_acceptance=${acc} chromium=${chrome}"
  [[ "$running" == "0" && "$acc" == "0" && "$chrome" == "0" ]] && return 1 || return 0
}

if [[ "${FORCE:-0}" != "1" ]]; then
  waited=0
  while status=$(host_busy); do
    log "${HOST_NAME} busy (${status}); waiting 60 s (${waited}/${WAIT_MAX_S} s)"
    (( waited >= WAIT_MAX_S )) && { log "still busy after ${WAIT_MAX_S} s, giving up"; exit 2; }
    sleep 60; waited=$((waited + 60))
  done
  log "${HOST_NAME} idle (${status})"
fi

# ---------------------------------------------------------------- 1. MCP execute_testcase
T0=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)
log "MCP execute_testcase ${TESTCASE} on ${HOST_NAME}/${DEVICE_ID}"
MCP_URL="$MCP_URL" ENV_FILE="${QUALIAI_DIR}/.env" TESTCASE="$TESTCASE" UI="$UI" \
HOST_NAME="$HOST_NAME" DEVICE_ID="$DEVICE_ID" OUT="$OUT_DIR/mcp_response.txt" \
node --input-type=module -e '
import fs from "node:fs";
const env = Object.fromEntries(fs.readFileSync(process.env.ENV_FILE, "utf8").split("\n")
  .filter(l => /^VPT_MCP_TOKEN=/.test(l))
  .map(l => { const i = l.indexOf("="); return [l.slice(0, i), l.slice(i + 1).trim().replace(/^["\x27]|["\x27]$/g, "")]; }));
if (!env.VPT_MCP_TOKEN) { console.error("VPT_MCP_TOKEN not found in " + process.env.ENV_FILE); process.exit(3); }
const body = { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "execute_testcase", arguments: {
  testcase_name: process.env.TESTCASE, userinterface_name: process.env.UI,
  host_name: process.env.HOST_NAME, device_id: process.env.DEVICE_ID } } };
const started = new Date();
let status = "error", text = "";
try {
  const r = await fetch(process.env.MCP_URL, { method: "POST", signal: AbortSignal.timeout(600000),
    headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream",
               Authorization: `Bearer ${env.VPT_MCP_TOKEN}` }, body: JSON.stringify(body) });
  status = String(r.status); text = await r.text();
} catch (e) { text = `fetch failed: ${e}`; }
const ended = new Date();
fs.writeFileSync(process.env.OUT, `mcp_call_start=${started.toISOString()}\nmcp_call_end=${ended.toISOString()}\n` +
  `mcp_http_status=${status}\nmcp_wall_ms=${ended - started}\n---\n${text.slice(0, 4000)}\n`);
console.error(`MCP ${status} in ${((ended - started) / 1000).toFixed(1)} s`);
' || log "MCP call failed (see mcp_response.txt); continuing with the DB row"
T1_EPOCH=$(date -u +%s)

# ---------------------------------------------------------------- 2. the script_results row
SR=""
for _ in $(seq 1 60); do
  SR=$(psql_q "select id, started_at, completed_at, execution_time_ms, coalesce(logs_r2_path,''), success,
                      floor(extract(epoch from started_at))::bigint
               from script_results where script_name='${TESTCASE}' and host_name='${HOST_NAME}'
               and started_at >= timestamptz '${T0}' - interval '10 seconds'
               and completed_at - started_at >= interval '2 seconds'
               order by started_at desc limit 1;")
  [[ -n "$SR" ]] && break
  sleep 5
done
[[ -n "$SR" ]] || { log "no finished script_results row for ${TESTCASE} on ${HOST_NAME} since ${T0}"; exit 4; }
echo "$SR" > "$OUT_DIR/script_result.txt"
IFS='|' read -r SR_ID SR_START SR_END SR_MS LOGS_PATH SR_OK SR_START_EPOCH <<< "$SR"
log "script_result ${SR_ID} success=${SR_OK} ${SR_START} -> ${SR_END} (${SR_MS} ms)"

# With the report tail in the background (VPT_TESTCASE_BACKGROUND_REPORT), the row reads as
# finished before its report and log paths are written: wait for them, then re-read
# completed_at, which the final write moves to the end of the tail.
REPORT_WAIT_S="${REPORT_WAIT_S:-180}"
waited=0
while [[ -z "$LOGS_PATH" ]] && (( waited < REPORT_WAIT_S )); do
  sleep 2; waited=$((waited + 2))
  LOGS_PATH=$(psql_q "select coalesce(logs_r2_path,'') from script_results where id='${SR_ID}';")
done
SR_FINAL_END=$(psql_q "select completed_at from script_results where id='${SR_ID}';")
T1_EPOCH=$(( $(date -u +%s) > T1_EPOCH ? $(date -u +%s) : T1_EPOCH ))
log "report paths after +${waited} s (final completed_at ${SR_FINAL_END}); logs_r2_path=${LOGS_PATH:-none}"
echo "final_completed_at=${SR_FINAL_END} report_wait_s=${waited}" >> "$OUT_DIR/script_result.txt"

psql "$PG" -X -A -F ',' -c "select executed_at, execution_time_ms, case when edge_id is not null then 'edge' else 'node' end as kind,
      coalesce(edge_id, node_id) as id, success from execution_results
      where script_result_id='${SR_ID}' order by executed_at;" > "$OUT_DIR/execution_results.csv"

# ---------------------------------------------------------------- 3. execution.txt from R2
if [[ -n "$LOGS_PATH" ]]; then
  ( cd "${QUALIAI_DIR}/app/backend" && LOGS_PATH="$LOGS_PATH" OUT="$OUT_DIR/execution.txt" ENV_FILE="${QUALIAI_DIR}/.env" \
    node --input-type=module -e '
const dotenv = await import(process.cwd() + "/node_modules/dotenv/lib/main.js").catch(() => null);
if (dotenv) dotenv.config({ path: process.env.ENV_FILE });
const { getObject } = await import(process.cwd() + "/dist/services/vpt-storage.js");
const o = await getObject(process.env.LOGS_PATH); let s = "";
for await (const c of o.body) s += c.toString();
(await import("node:fs")).writeFileSync(process.env.OUT, s);
console.error(`execution.txt ${s.length} bytes`); process.exit(0);
' ) || log "execution.txt download failed"
else
  log "row has no logs_r2_path"; : > "$OUT_DIR/execution.txt"
fi

# ---------------------------------------------------------------- 4. host journal (finalize tail)
ssh -o ConnectTimeout=10 "$HOST_IP" "sudo -n journalctl -u vpt-host --no-pager -o short-iso-precise \
  --since @$((SR_START_EPOCH - 5)) --until @$((T1_EPOCH + 10))" > "$OUT_DIR/journal.txt" 2>/dev/null \
  || log "journal fetch failed"

# ---------------------------------------------------------------- 5. timeline
SR_START="$SR_START" SR_END="$SR_END" SR_FINAL_END="$SR_FINAL_END" OUT_DIR="$OUT_DIR" python3 - <<'PY' | tee "$OUT_DIR/timeline.txt"
import csv, os, re
from datetime import datetime, timedelta, timezone

out = os.environ['OUT_DIR']
def ts(s):  # psql timestamptz -> aware datetime
    s = s.strip().replace(' ', 'T', 1)
    if re.search(r'[+-]\d\d$', s):
        s += ':00'
    return datetime.fromisoformat(s)
start, end = ts(os.environ['SR_START']), ts(os.environ['SR_END'])
day = start.astimezone(timezone.utc).date()
MARK = '⏱'
phase_re = re.compile(MARK + r' (\S+) (\d+) ms ?(.*)$')
rows = []  # (end_dt, ms, phase, detail, source)

for line in open(f'{out}/execution.txt', encoding='utf-8', errors='replace'):
    m = re.match(r'^(\d\d):(\d\d):(\d\d)\.(\d{3})Z \+\s*[\d.]+ (.*)$', line.rstrip('\n'))
    if not m:
        continue
    p = phase_re.search(m.group(5))
    if not p:
        continue
    t = datetime(day.year, day.month, day.day, int(m.group(1)), int(m.group(2)), int(m.group(3)),
                 int(m.group(4)) * 1000, tzinfo=timezone.utc)
    if t < start - timedelta(hours=12):
        t += timedelta(days=1)
    rows.append((t, int(p.group(2)), p.group(1), p.group(3), 'log'))

have = {}
for r in rows:
    have.setdefault((r[2], r[1]), []).append(r[0])
for line in open(f'{out}/journal.txt', encoding='utf-8', errors='replace'):
    m = re.match(r'^(\S+) \S+ [^:]+: (.*)$', line.rstrip('\n'))
    if not m:
        continue
    p = phase_re.search(m.group(2))
    if not p:
        continue
    try:
        t = datetime.fromisoformat(m.group(1))
    except ValueError:
        continue
    key = (p.group(1), int(p.group(2)))
    # The journal receives the same ⏱ lines as execution.txt; keep only the ones the log lacks
    # (the finalize tail after the capture stops, and anything a first run after a restart
    # routed around the capture).
    if any(abs((t - seen).total_seconds()) < 1.5 for seen in have.get(key, [])):
        continue
    rows.append((t, int(p.group(2)), p.group(1), p.group(3), 'journal'))

rows.sort(key=lambda r: (r[0] - timedelta(milliseconds=r[1]), -r[1]))
rel = lambda t: (t - start).total_seconds()
print(f"testcase started_at {start.astimezone(timezone.utc):%H:%M:%S.%f}Z  completed_at "
      f"{end.astimezone(timezone.utc):%H:%M:%S.%f}Z  = {rel(end):.1f} s")
for line in open(f'{out}/mcp_response.txt', encoding='utf-8', errors='replace'):
    if line.startswith('mcp_'):
        k, v = line.strip().split('=', 1)
        if k in ('mcp_call_start', 'mcp_call_end'):
            v = f"{v}  (+{rel(datetime.fromisoformat(v.replace('Z', '+00:00'))):.1f} s)"
        print(f"  {k} = {v}")
    if line.startswith('---'):
        break
print()
print(f"{'start':>8} {'end':>8} {'ms':>7}  src      phase  detail")
for t, ms, phase, detail, src in rows:
    s = rel(t) - ms / 1000
    print(f"{s:8.2f} {rel(t):8.2f} {ms:7d}  {src:7}  {phase}  {detail[:150]}")

print("\nexecution_results rows (executed_at = start of the insert, after that hop's verification):")
with open(f'{out}/execution_results.csv', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        if not r.get('executed_at') or r['executed_at'].startswith('('):
            continue
        print(f"  +{rel(ts(r['executed_at'])):7.2f}  {r['kind']:4} {int(r['execution_time_ms'] or 0):6d} ms  {r['id'][:40]}  success={r['success']}")

totals = {}
for t, ms, phase, detail, src in rows:
    n, tot = totals.get(phase, (0, 0))
    totals[phase] = (n + 1, tot + ms)
print("\nper-phase totals (nested phases overlap their parents; compare like with like):")
for phase, (n, tot) in sorted(totals.items(), key=lambda kv: -kv[1][1]):
    print(f"  {tot:8d} ms  x{n:<3d} {phase}")
PY
log "done: $OUT_DIR"
