#!/usr/bin/env bash
# Memory/CPU soak log of a VPT host: samples every vpt-* service's memory, the board's RAM, zram,
# load, temperature and throttling at a fixed interval, ON the host (a transient systemd unit, so
# it survives SSH drops), then reports per-service growth. Read-only on the host apart from its CSV.
#
#   scripts/host_soak.sh start  <ssh-host> [hours=24] [interval_s=600]
#   scripts/host_soak.sh status <ssh-host>
#   scripts/host_soak.sh report <ssh-host> [output_csv]
#   scripts/host_soak.sh stop   <ssh-host>
#
# CSV on the host: /var/tmp/vpt-soak.csv (one row per service per sample + one "board" row).
# Report: per service first/last/max private MB (RssAnon) and the growth in MB/hour from a
# least-squares fit over the samples after the first hour (warm-up excluded); board rows give
# MemAvailable min, zram used max, load max, temperature max, throttled flags seen. MB/h needs at
# least 2 h of samples after the first hour (n/a before). A service
# growing > 5 MB/h over a 24 h run is a leak to investigate (TASK-83).
set -euo pipefail

CMD="${1:?usage: host_soak.sh start|status|report|stop <ssh-host> ...}"
HOST="${2:?ssh host required}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST")
CSV=/var/tmp/vpt-soak.csv
UNIT=vpt-soak

sampler() {
cat <<'REMOTE'
#!/bin/bash
HOURS="$1"; INTERVAL="$2"
CSV=/var/tmp/vpt-soak.csv
end=$(( $(date +%s) + $(awk -v h="$HOURS" 'BEGIN{printf "%d", h * 3600}') ))
[ -s "$CSV" ] || echo "ts,kind,name,rss_mb,private_mb,threads,extra" > "$CSV"
while [ "$(date +%s)" -le "$end" ]; do
  ts=$(date +%s)
  for u in $(systemctl list-units 'vpt-*' --state=active --no-legend --plain | awk '{print $1}'); do
    [ "$u" = "vpt-soak.service" ] && continue
    main=$(systemctl show -p MainPID --value "$u"); [ "${main:-0}" -gt 0 ] || continue
    rss=0; priv=0; thr=0
    # the unit's whole process tree (ffmpeg under vpt-stream, workers under host)
    for p in $(cat "/sys/fs/cgroup/system.slice/$u/cgroup.procs" 2>/dev/null || echo "$main"); do
      read -r r a t < <(awk '/^VmRSS/{r=$2} /^RssAnon/{a=$2} /^Threads/{t=$2} END{print r+0, a+0, t+0}' "/proc/$p/status" 2>/dev/null) || continue
      rss=$((rss + r)); priv=$((priv + a)); thr=$((thr + t))
    done
    echo "$ts,service,${u%.service},$((rss / 1024)),$((priv / 1024)),$thr," >> "$CSV"
  done
  avail=$(awk '/^MemAvailable/{print int($2/1024)}' /proc/meminfo)
  total=$(awk '/^MemTotal/{print int($2/1024)}' /proc/meminfo)
  zram=$(awk 'NR>1 && $1 ~ /zram/ {u+=$4} END{print int(u/1024)}' /proc/swaps)
  load=$(cut -d' ' -f1 /proc/loadavg)
  temp=$(awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo "")
  thr=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
  oom=$(journalctl -k --since "-$(( INTERVAL + 5 )) s" --no-pager 2>/dev/null | grep -ci "out of memory\|oom-kill" || true)
  echo "$ts,board,mem,$total,$((total - avail)),0,avail=$avail zram_used=$zram load=$load temp=$temp throttled=$thr oom=$oom" >> "$CSV"
  sleep "$INTERVAL"
done
REMOTE
}

case "$CMD" in
  start)
    HOURS="${3:-24}"; INTERVAL="${4:-600}"
    sampler | "${SSH[@]}" "cat > /tmp/vpt-soak.sh && sudo -n install -m 755 /tmp/vpt-soak.sh /var/tmp/vpt-soak.sh && rm -f /tmp/vpt-soak.sh"
    "${SSH[@]}" "sudo -n systemctl reset-failed $UNIT 2>/dev/null; sudo -n rm -f $CSV; \
      sudo -n systemd-run --unit=$UNIT --description='VPT soak log' /var/tmp/vpt-soak.sh $HOURS $INTERVAL >/dev/null && \
      echo \"soak started on \$(hostname): ${HOURS} h, every ${INTERVAL} s -> $CSV\""
    ;;
  status)
    "${SSH[@]}" "systemctl is-active $UNIT; [ -f $CSV ] && echo \"\$(grep -c ',board,' $CSV) samples, last: \$(tail -1 $CSV)\""
    ;;
  stop)
    "${SSH[@]}" "sudo -n systemctl stop $UNIT && echo stopped"
    ;;
  report)
    OUT="${3:-soak_${HOST//[^A-Za-z0-9_.-]/_}_$(date +%Y%m%d_%H%M).csv}"
    "${SSH[@]}" "cat $CSV" > "$OUT"
    echo "CSV saved: $OUT"
    python3 - "$OUT" <<'PY'
import csv, sys, collections
rows = list(csv.DictReader(open(sys.argv[1])))
if not rows: sys.exit("no samples yet")
t0 = int(rows[0]["ts"]); t1 = int(rows[-1]["ts"])
print(f"span {(t1 - t0) / 3600:.1f} h, {sum(r['kind'] == 'board' for r in rows)} samples")
svc = collections.defaultdict(list)
for r in rows:
    if r["kind"] == "service":
        svc[r["name"]].append((int(r["ts"]), int(r["private_mb"]), int(r["rss_mb"]), int(r["threads"])))
def slope(pts):
    pts = [(t, v) for t, v in pts if t - t0 >= 3600]             # skip the first hour (warm-up)
    if len(pts) < 3 or pts[-1][0] - pts[0][0] < 2 * 3600: return None   # too short to call a trend
    n = len(pts); mt = sum(t for t, _ in pts) / n; mv = sum(v for _, v in pts) / n
    d = sum((t - mt) ** 2 for t, _ in pts)
    return 0.0 if d == 0 else sum((t - mt) * (v - mv) for t, v in pts) / d * 3600
print(f"\n{'service':22s} {'private MB first':>16s} {'last':>6s} {'max':>6s} {'RSS last':>9s} {'threads':>8s} {'MB/h':>7s}")
total_last = 0
for name, s in sorted(svc.items()):
    g = slope([(t, p) for t, p, _, _ in s]); total_last += s[-1][1]
    flag = "  <-- growing" if g is not None and g > 5 else ""
    gs = "n/a" if g is None else f"{g:.1f}"
    print(f"{name:22s} {s[0][1]:16d} {s[-1][1]:6d} {max(p for _, p, _, _ in s):6d} {s[-1][2]:9d} {s[-1][3]:8d} {gs:>7s}{flag}")
print(f"{'sum of private':22s} {'':16s} {total_last:6d}")
b = [r for r in rows if r["kind"] == "board"]
ex = [dict(kv.split("=", 1) for kv in r["extra"].split()) for r in b]
num = lambda k: [float(e[k]) for e in ex if e.get(k) not in (None, "")]
print(f"\nboard: RAM {b[-1]['rss_mb']} MB total | used last {b[-1]['private_mb']} MB, max {max(int(r['private_mb']) for r in b)} MB"
      f" | MemAvailable min {min(num('avail')):.0f} MB | zram used max {max(num('zram_used') or [0]):.0f} MB"
      f" | load max {max(num('load')):.2f} | temp max {max(num('temp') or [0]):.1f} C"
      f" | throttled seen {sorted({e.get('throttled') for e in ex} - {None, ''}) or ['n/a']}"
      f" | OOM kills {int(sum(num('oom')))}")
PY
    ;;
  *) echo "unknown command: $CMD" >&2; exit 2 ;;
esac
