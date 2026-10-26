#!/usr/bin/env python3
"""TASK-103 measurement collector (READ-ONLY on the host).

Polls a host over ssh every few seconds and copies, into a local folder, what the host rotates away:
  * hot/captures/*.jpg   frames (ring of ~200 s, ~4.5 fps) -> <out>/frames/   (subtitle reference for goal 3)
  * audio/temp/1min_N.mp3  1-minute audio slots (ring of 10)   -> <out>/audio/<mtime-epoch>_1min_N.mp3
  * /dev/shm/vpt-archiver/<capture>/1min_N.mp4 the matching 1-minute video+audio (same timebase) -> <out>/video/
  * stat log (jsonl, ns mtimes) of audio slots, /dev/shm archiver minute files and the growing archive
    chunk -> <out>/stat.jsonl   (merge-lag evidence for goal 2)
Never writes on the host. Usage:
  task103_collect.py --host vpt-pi1 --capture capture3 --out ~/task103-data/run1 --minutes 45
"""
import argparse, json, os, subprocess, time

p = argparse.ArgumentParser()
p.add_argument('--host', default='vpt-pi1')
p.add_argument('--capture', default='capture3')
p.add_argument('--out', required=True)
p.add_argument('--minutes', type=float, default=45)
p.add_argument('--every', type=float, default=15)
a = p.parse_args()
base = f'/var/www/html/stream/{a.capture}'
os.makedirs(f'{a.out}/frames', exist_ok=True)
os.makedirs(f'{a.out}/audio', exist_ok=True)
STAT = (f"date +%s.%N; stat -L -c '%n %s %.9Y' {base}/audio/temp/1min_*.mp3 /dev/shm/vpt-archiver/{a.capture}/*.mp4 "
        f"{base}/segments/temp/1min_*.mp4 {base}/segments/$(date +%-H)/chunk_10min_*.mp4 2>/dev/null; "
        f"ls -t {base}/captures | head -1")
end = time.time() + a.minutes * 60
seen_audio = set()
log = open(f'{a.out}/stat.jsonl', 'a')
while time.time() < end:
    t0 = time.time()
    r = subprocess.run(['ssh', a.host, STAT], capture_output=True, text=True, timeout=60)
    lines = r.stdout.strip().splitlines()
    if lines:
        rec = {'host_now': float(lines[0]), 'local_now': t0, 'files': {}}
        for ln in lines[1:-1]:
            n, s, m = ln.split()
            rec['files'][n] = [int(s), float(m)]
        log.write(json.dumps(rec) + '\n'); log.flush()
        for n, (s, m) in rec['files'].items():
            if ('/audio/temp/1min_' in n or ('/dev/shm/' in n and '/1min_' in n)) and (n, m) not in seen_audio:
                seen_audio.add((n, m))
                sub = 'audio' if n.endswith('.mp3') else 'video'
                os.makedirs(f'{a.out}/{sub}', exist_ok=True)
                dst = f"{a.out}/{sub}/{int(m)}_{os.path.basename(n)}"
                if not os.path.exists(dst):
                    subprocess.run(['scp', '-q', f'{a.host}:{n}', dst], timeout=60)
    subprocess.run(['rsync', '-a', '--ignore-existing', '-e', 'ssh', f'{a.host}:{base}/hot/captures/', f'{a.out}/frames/'],
                   stdout=subprocess.DEVNULL, timeout=120)
    time.sleep(max(0, a.every - (time.time() - t0)))
