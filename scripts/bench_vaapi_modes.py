#!/usr/bin/env python3
"""Run the TASK-95 VAAPI scenarios on one host back to back (drives the host config API over ssh, restarts the stream units,
measures each stream's speed and segment rate). Usage: bench_vaapi_modes.py <ssh-host> <scenario ...> | all
Needs: passwordless sudo for the ssh user, bench devices are created as DEVICE19..N (Apple bipbop gear4 720p) and removed at the end.
Writes one JSON line per scenario to stdout; progress to stderr. Hold the platform lease for the whole run."""
import json, subprocess, sys, time

HOST = sys.argv[1]
SCEN = {  # name: (devices, env keys, hd devices (count of first N non-tello, or 'all'), settle seconds)
    'dec29':       (29, {'VAAPI_MODE': 'decode_only'}, 0, 200),
    'enc29':       (29, {'VAAPI_MODE': 'encode_only'}, 0, 200),
    'sw48t1':      (48, {'VAAPI_MODE': 'off', 'SW_THREADS': '1'}, 0, 240),
    'sw60t1':      (60, {'VAAPI_MODE': 'off', 'SW_THREADS': '1'}, 0, 330),
    'sw72t1':      (72, {'VAAPI_MODE': 'off', 'SW_THREADS': '1'}, 0, 360),
    'sw48':        (48, {'VAAPI_MODE': 'off', 'SW_THREADS': '0'}, 0, 240),
    'full18hd':    (18, {'VAAPI_MODE': 'full'}, 'all', 200),
    'full24hd':    (24, {'VAAPI_MODE': 'full'}, 'all', 200),
    'full30hd':    (30, {'VAAPI_MODE': 'full'}, 'all', 200),
    'enc24hd':     (24, {'VAAPI_MODE': 'encode_only'}, 'all', 200),
    'mixed40+4':   (44, {'VAAPI_MODE': 'full', 'VAAPI_MIN_QUALITY': 'hd', 'SW_THREADS': '1'}, 4, 300),
}
ENV_KEYS = ['VAAPI_MODE', 'VAAPI_MIN_QUALITY', 'SW_THREADS']

def ssh(cmd, inp=None, timeout=900):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', HOST, cmd], input=inp, text=True, capture_output=True, timeout=timeout).stdout

CFG = r'''
import json, subprocess, sys, urllib.request
n, keys = int(sys.argv[1]), json.loads(sys.argv[2])
env = subprocess.check_output(['sudo','-n','cat','/opt/virtualpytest/backend_host/src/.env'], text=True)
key = next(l.split('=',1)[1].strip().strip('"\'') for l in env.splitlines() if l.startswith('API_KEY='))
def call(m, d=None):
    r = urllib.request.Request('http://localhost:6109/host/system/config', method=m, headers={'X-API-Key': key, 'Content-Type': 'application/json'}, data=json.dumps(d).encode() if d is not None else None)
    return json.load(urllib.request.urlopen(r, timeout=30))
c = call('GET'); host, devs = c['host'], c['devices']
for k in [k for k, v in devs.items() if v.get('DEVICE_NAME', '').startswith('bench HD')]: devs.pop(k)
for k in ('VAAPI_MODE', 'VAAPI_MIN_QUALITY', 'SW_THREADS'): host.pop(k, None)
host.update(keys)
real = [k for k in devs if k != 'DEVICE25']
extra = n - len(real); i = 19
while extra > 0:
    if i == 25: i += 1
    devs[f'DEVICE{i}'] = {'DEVICE_MODEL':'rtsp_video','DEVICE_NAME':f'bench HD 720p {i}','DEVICE_STREAM_LOOP':'1','DEVICE_STREAM_TYPE':'hls',
      'DEVICE_VIDEO':'https://devstreaming-cdn.apple.com/videos/streaming/examples/bipbop_16x9/gear4/prog_index.m3u8',
      'DEVICE_VIDEO_CAPTURE_PATH':f'/var/www/html/stream/capture{i}','DEVICE_VIDEO_FPS':'10','DEVICE_VIDEO_STREAM_PATH':f'/host/stream/capture{i}'}
    i += 1; extra -= 1
print(len(devs), call('POST', {'host': host, 'devices': devs}))
'''
RESTART = 'sudo -n rm -f /tmp/vpt_vaapi_render_node; sudo -n systemctl restart vpt-stream vpt-monitor-img vpt-monitor-audio vpt-archiver vpt-kpi'
SETQ = r'''F=/var/www/html/stream/active_captures.conf; N=%s
for round in 1 2 3; do
  sed "s/,hd\$/,low/" $F > /tmp/ac.new; cat /tmp/ac.new > $F
  if [ "$N" = all ]; then sed "/capture25,/! s/,low\$/,hd/" $F > /tmp/ac.new; else
    awk -F, -v n=$N '$1 !~ /capture25$/ && c<n {$3="hd"; c++} {print}' OFS=, $F > /tmp/ac.new; fi
  cat /tmp/ac.new > $F; rm -f /tmp/ac.new; sleep 20
done'''
MEASURE = r'''ok=0; slow=0; n=0; segs=0; min=9
while IFS=, read -r dir _ q; do c=${dir##*/capture}; [ "$c" = 25 ] && continue
  s=$(tail -c 600 /tmp/ffmpeg_output_device$c.log 2>/dev/null | tr '\r' '\n' | grep -o 'speed=[ 0-9.]*x' | tail -1 | tr -dc '0-9.'); [ -z "$s" ] && s=0
  sg=$(find $dir/hot/segments -name '*.ts' -newermt '-10 seconds' 2>/dev/null | wc -l)
  n=$((n+1)); segs=$((segs+sg)); awk -v s=$s 'BEGIN{exit !(s>=0.95)}' && ok=$((ok+1)) || slow=$((slow+1))
  awk -v s=$s -v m=$min 'BEGIN{exit !(s<m)}' && min=$s
done < /var/www/html/stream/active_captures.conf
idle=$(vmstat 1 6 | tail -1 | awk '{print $15}'); avail=$(free -m | awk '/^Mem/{print $7}'); swap=$(free -m | awk '/^Swap/{print $3}')
echo "{\"streams\":$n,\"at_1x\":$ok,\"slow\":$slow,\"min_speed\":$min,\"avg_seg_per_10s\":$((segs*100/(n>0?n:1)))e-2,\"cpu_idle\":$idle,\"mem_avail_mb\":$avail,\"swap_mb\":$swap}"'''

names = list(SCEN) if sys.argv[2:] == ['all'] else sys.argv[2:]
for name in names:
    n, keys, hd, settle = SCEN[name]
    t0 = time.time()
    print(f'[{name}] config {n} devices {keys}', file=sys.stderr)
    ssh('python3 - %d %s' % (n, json.dumps(json.dumps(keys))), inp=CFG)
    ssh(RESTART)
    time.sleep(70)
    if hd:
        ssh(SETQ % hd)
    time.sleep(max(0, settle - 70))
    res = ssh(MEASURE).strip()
    out = {'scenario': name, 'devices': n, 'keys': keys, 'hd': hd, 'settle_s': settle, 'result': res}
    print(json.dumps(out), flush=True)
    print(f'[{name}] done in {time.time()-t0:.0f}s: {res}', file=sys.stderr)
# cleanup: back to the 18 real devices, no VAAPI keys
ssh('python3 - 18 "{}"', inp=CFG)
ssh(RESTART)
