#!/usr/bin/env bash
# Collect a bounded, read-only load-average diagnostic bundle from a VPT host.
# Usage: scripts/collect_host_load.sh <ssh-host> [duration_s] [output_file]
# duration_s (1-900) is the length of the 1 s CPU/disk timeline and per-process write window;
# iostat/pidstat run for at most 30 s after it. Use a few minutes to catch an intermittent stall.

set -euo pipefail

SSH_HOST="${1:?usage: collect_host_load.sh <ssh-host> [duration_s] [output_file]}"
DURATION="${2:-10}"

if ! [[ "$DURATION" =~ ^[1-9][0-9]*$ ]] || (( DURATION > 900 )); then
  echo "duration_s must be an integer from 1 to 900" >&2
  exit 2
fi

SAFE_HOST="${SSH_HOST//[^A-Za-z0-9_.-]/_}"
OUTPUT_FILE="${3:-load-diagnostic_${SAFE_HOST}_$(date +%Y%m%d_%H%M%S).txt}"

echo "Collecting ${DURATION}s load diagnostic from ${SSH_HOST} -> ${OUTPUT_FILE}"

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" \
  "VPT_DIAG_DURATION='$DURATION' bash -s" <<'REMOTE' | tee "$OUTPUT_FILE"
set -u

section() { printf '\n===== %s =====\n' "$1"; }
run() {
  printf '\n$ %s\n' "$*"
  "$@" 2>&1 || printf '[command unavailable or failed: %s]\n' "$*"
}

DURATION="$VPT_DIAG_DURATION"
SHORT=$(( DURATION < 30 ? DURATION : 30 ))
SUDO=""; sudo -n true 2>/dev/null && SUDO="sudo -n"

# Block device behind / (mmcblk0 on a Pi): the persistent writes that stall a host land there.
ROOT_SRC=$(findmnt -no SOURCE / 2>/dev/null)
ROOT_DEV=$(lsblk -no PKNAME "$ROOT_SRC" 2>/dev/null | head -1)
[ -n "$ROOT_DEV" ] || ROOT_DEV=$(basename "$ROOT_SRC")

# write_bytes per pid (bytes this task caused to be sent to storage; tmpfs does not count).
io_snapshot() {
  $SUDO bash -c 'for d in /proc/[0-9]*; do
    w=$(awk "/^write_bytes/{print \$2}" $d/io 2>/dev/null) || continue
    [ -n "$w" ] && printf "%s %s %s\n" "${d#/proc/}" "$w" "$(tr -d "\n" < $d/comm 2>/dev/null)"
  done' 2>/dev/null
}

section "IDENTITY AND UPTIME"
run date -Is
run hostname
run uname -a
run uptime
run nproc

section "LOAD AND PRESSURE"
run cat /proc/loadavg
run awk '/procs_running|procs_blocked/ {print}' /proc/stat
for pressure_file in /proc/pressure/cpu /proc/pressure/io /proc/pressure/memory; do
  printf '\n--- %s ---\n' "$pressure_file"
  if [[ -r "$pressure_file" ]]; then cat "$pressure_file"; else echo unavailable; fi
done

section "CPU / RUN QUEUE / ${ROOT_DEV} TIMELINE (1 s, ${DURATION}s)"
# One row per second, all from /proc, so a short disk stall lines up with the run queue,
# blocked tasks, dirty page cache and the exact tasks stuck in D state at that second.
#   r/b: runnable / blocked in uninterruptible sleep   us/sy/wa/id: % of all CPUs
#   w/s wMB/s w_await(ms) r_await(ms) aqu util%: like iostat -x for ${ROOT_DEV}
#   dirtyMB/wbMB: page cache waiting for / under writeback   D: task(wchan) in D state
TL_RAW=$(mktemp)
IO_START=$(mktemp); IO_END=$(mktemp)
io_snapshot > "$IO_START"
for ((i = 0; i <= DURATION; i++)); do
  {
    date +%s.%N
    awk '/^cpu /{print $2+$3, $4, $5, $6, $7+$8+$9}' /proc/stat
    awk '/procs_running/{r=$2} /procs_blocked/{b=$2} END{print r, b}' /proc/stat
    awk -v d="$ROOT_DEV" '$3==d{print $4, $7, $8, $10, $11, $12, $13, $14}' /proc/diskstats
    awk '/^Dirty:/{d=$2} /^Writeback:/{w=$2} END{print d, w}' /proc/meminfo
    ps -eo stat=,comm=,wchan:24= | awk '$1 ~ /^D/{printf "%s(%s) ", $2, $3}'
    echo
  } | paste -sd'|' >> "$TL_RAW"
  [ "$i" -lt "$DURATION" ] && sleep 1
done
io_snapshot > "$IO_END"
awk -F'|' '
  { split($2,c," "); split($3,q," "); split($4,k," "); split($5,m," ")
    if (NR > 1) {
      dt = $1 - pt; if (dt <= 0) dt = 1
      tot = (c[1]-pc[1]) + (c[2]-pc[2]) + (c[3]-pc[3]) + (c[4]-pc[4]) + (c[5]-pc[5]); if (tot <= 0) tot = 1
      rio = k[1]-pk[1]; rms = k[2]-pk[2]; wio = k[3]-pk[3]; wsec = k[4]-pk[4]; wms = k[5]-pk[5]
      busy = k[7]-pk[7]; wtd = k[8]-pk[8]
      wa = 100*(c[4]-pc[4])/tot; wawait = wio ? wms/wio : 0; util = busy/(10*dt)
      printf "%s r=%-3d b=%-2d us=%3.0f sy=%3.0f wa=%3.0f id=%3.0f | w/s=%6.1f wMB/s=%6.2f w_await=%7.1f r_await=%6.1f aqu=%5.2f util=%3.0f%% | dirtyMB=%6.1f wbMB=%5.1f | D: %s\n",
        strftime("%H:%M:%S", int($1)), q[1], q[2], 100*(c[1]-pc[1])/tot, 100*(c[2]-pc[2])/tot, wa,
        100*(c[3]-pc[3])/tot, wio/dt, wsec*512/1048576/dt, wawait, rio ? rms/rio : 0, wtd/(1000*dt), util,
        m[1]/1024, m[2]/1024, $6
      n++; swa += wa; if (wa > 20) nwa++; if (q[2] > 0) nb++; if (wawait > 100) nslow++
      if (q[2] > 0 && wio == 0 && k[6] > 0) nstall++
      if (wawait > maxw) { maxw = wawait; maxwt = strftime("%H:%M:%S", int($1)) }
      if (q[2] > maxb) { maxb = q[2]; maxbt = strftime("%H:%M:%S", int($1)) }
    }
    pt = $1; for (j in c) pc[j] = c[j]; for (j in k) pk[j] = k[j]
  }
  END { if (n) printf "\nSUMMARY %ds: mean wa=%.1f%%, seconds with wa>20%%: %d, with blocked tasks: %d, with w_await>100ms: %d, write stalls (blocked, writes in flight, none completed): %d, worst w_await %.0f ms at %s, most blocked %d at %s\n",
          n, swa/n, nwa, nb, nslow, nstall, maxw, maxwt, maxb, maxbt }
' "$TL_RAW"

section "STORAGE WRITERS OVER THE ${DURATION}s WINDOW"
# Bytes each task caused to be written to block storage during the timeline (tmpfs excluded).
# A task that started or exited inside the window is missing; kernel flushers (kworker,
# jbd2) write on behalf of others, so attribute through the user-space rows.
[ -n "$SUDO" ] || echo "(no passwordless sudo: only this user's processes are visible)"
awk 'NR==FNR { s[$1] = $2; next }
     ($1 in s) && $2 - s[$1] >= 102400 { d = $2 - s[$1]; printf "%10.1f MB  %7.2f MB/s  pid %-8s %s\n", d/1048576, d/1048576/'"$DURATION"', $1, $3 }' \
  "$IO_START" "$IO_END" | sort -rn | head -20 | tee "$IO_START.top"
printf '\n--- files open for writing on / by the top writers ---\n'
for pid in $(awk '{print $6}' "$IO_START.top" | head -10); do
  $SUDO bash -c 'for f in /proc/'"$pid"'/fd/*; do
    t=$(readlink "$f") || continue
    case "$t" in /*) ;; *) continue ;; esac
    fl=$(awk "/^flags/{print \$2}" /proc/'"$pid"'/fdinfo/${f##*/} 2>/dev/null)
    [ $(( 8#${fl:-0} & 3 )) -ne 0 ] || continue
    [ "$(findmnt -no TARGET -T "$t" 2>/dev/null)" = / ] || continue
    printf "pid %-8s %s (%s)\n" '"$pid"' "$t" "$(stat -c %s "$t" 2>/dev/null) bytes"
  done' 2>/dev/null
done | sort -u
rm -f "$TL_RAW" "$IO_START" "$IO_END" "$IO_START.top"

section "LARGEST FILES IN /tmp AND /var/log (only a problem when not tmpfs)"
run findmnt -no TARGET,FSTYPE -T /tmp
ls -laS /tmp 2>/dev/null | head -15
$SUDO du -xsh /var/log/* 2>/dev/null | sort -h | tail -10

section "PROCESS SNAPSHOT"
run ps -eo pid,ppid,user,stat,ni,psr,pcpu,pmem,etimes,wchan:28,comm,args --sort=-pcpu

section "UNINTERRUPTIBLE AND ZOMBIE TASKS"
ps -eo pid,ppid,user,stat,etimes,wchan:32,comm,args | awk 'NR == 1 || $4 ~ /^D|^Z/' || true

section "THREAD HOTSPOTS"
run ps -eLo pid,tid,ppid,user,stat,ni,psr,pcpu,pmem,comm --sort=-pcpu

section "FFMPEG AND VPT WORKERS"
run pgrep -a ffmpeg
ps -eo pid,ppid,stat,ni,pcpu,pmem,etimes,comm,args \
  | awk 'NR == 1 || /capture_monitor|hot_cold_archiver|avq_monitor|tesseract|transcript_accumulator|kpi_executor/' || true
run cat /var/www/html/stream/active_captures.conf

section "FILESYSTEMS, MOUNTS, AND BLOCK DEVICES"
run findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS
run lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,ROTA,TRAN,MODEL
run df -hT
run df -i

section "BLOCK DEVICE LATENCY (${SHORT}s)"
if command -v iostat >/dev/null 2>&1; then
  run iostat -xz 1 "$((SHORT + 1))"
else
  echo "iostat unavailable (install package sysstat during maintenance if this host needs diagnosis)"
fi

section "PER-PROCESS DISK I/O (${SHORT}s, rows with reads or writes only)"
if command -v pidstat >/dev/null 2>&1; then
  # Every process (any writer can stall the card), idle rows dropped.
  # Columns: Time UID PID kB_rd/s kB_wr/s kB_ccwr/s iodelay (clock ticks blocked on I/O) Command.
  $SUDO pidstat -d -h 1 "$SHORT" 2>&1 | awk '/^#/ { if (!h++) print; next } NF < 8 { print; next }
    $4+0 > 0 || $5+0 > 0 || $6+0 > 0 || $7+0 > 0'
elif command -v iotop >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  run sudo -n iotop -b -o -P -d 1 -n "$SHORT"
else
  echo "pidstat/iotop unavailable; block-device latency above is still collected"
fi

section "MEMORY"
run free -h
run cat /proc/meminfo
run swapon --show

section "RASPBERRY PI THERMAL AND POWER STATE"
if command -v vcgencmd >/dev/null 2>&1; then
  run vcgencmd measure_temp
  run vcgencmd get_throttled
  run vcgencmd measure_clock arm
else
  echo "vcgencmd unavailable (non-Pi host)"
fi

section "RECENT STORAGE, MMC, USB, AND THROTTLE KERNEL EVENTS"
if sudo -n true 2>/dev/null; then
  sudo -n dmesg -T 2>/dev/null \
    | grep -Ei 'mmc|ext4|i/o error|timeout|reset|usb.*disconnect|under-voltage|voltage|throttl|hung task' \
    | tail -200 || true
else
  dmesg -T 2>/dev/null \
    | grep -Ei 'mmc|ext4|i/o error|timeout|reset|usb.*disconnect|under-voltage|voltage|throttl|hung task' \
    | tail -200 || true
fi

section "VPT SERVICES"
systemctl --no-pager --full --type=service --state=running 2>/dev/null \
  | grep -E 'vpt-(stream|monitor|archiver|host|mediamtx)' || true

section "RECENT ARCHIVER ACTIVITY"
if sudo -n true 2>/dev/null; then
  sudo -n journalctl -u vpt-archiver --since '-5 min' --no-pager 2>/dev/null | tail -200 || true
else
  journalctl -u vpt-archiver --since '-5 min' --no-pager 2>/dev/null | tail -200 || true
fi

section "SUMMARY SNAPSHOT"
run uptime
run ps -eo pid,ppid,stat,ni,pcpu,pmem,etimes,comm,args --sort=-pcpu
REMOTE

echo "Saved diagnostic bundle: ${OUTPUT_FILE}"
