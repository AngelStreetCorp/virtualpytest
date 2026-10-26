#!/usr/bin/env python3
"""TASK-103 re-measure: several devices' 1-minute files arriving together, N worker processes (the accumulator
runs --workers 2, one in-flight file per device). Reports per-file latency = queue wait + transcription.

  task103_queue_sim.py --model tiny --workers 2 --rounds 8 --interval 60 --dev A=a1.mp3,a2.mp3,... --dev B=...
Round r submits file r of every device at the same moment (worst case: all devices' minutes land together).
Prints one JSON line per file {device, round, wait_s, run_s, latency_s} and a summary.
"""
import argparse, json, multiprocessing as mp, time

def worker(q, out, model, model_dir):
    from faster_whisper import WhisperModel
    m = WhisperModel(model, device='cpu', compute_type='int8', cpu_threads=1, num_workers=1, download_root=model_dir)
    out.put(('ready', None))
    while True:
        job = q.get()
        if job is None:
            return
        dev, rnd, path, t_sub = job
        t0 = time.time()
        segs, _ = m.transcribe(path, beam_size=1, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
                               condition_on_previous_text=False, temperature=0)
        list(segs)
        t1 = time.time()
        out.put(('done', {'device': dev, 'round': rnd, 'wait_s': round(t0 - t_sub, 2), 'run_s': round(t1 - t0, 2),
                          'latency_s': round(t1 - t_sub, 2)}))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='tiny'); ap.add_argument('--model-dir')
    ap.add_argument('--workers', type=int, default=2); ap.add_argument('--rounds', type=int, default=8)
    ap.add_argument('--interval', type=float, default=60); ap.add_argument('--dev', action='append', required=True)
    a = ap.parse_args()
    devs = {d.split('=')[0]: d.split('=')[1].split(',') for d in a.dev}
    q, out = mp.Queue(), mp.Queue()
    ps = [mp.Process(target=worker, args=(q, out, a.model, a.model_dir)) for _ in range(a.workers)]
    [p.start() for p in ps]
    [out.get() for _ in ps]
    res, n = [], 0
    t_start = time.time()
    for r in range(a.rounds):
        t_sub = time.time()
        for d, files in devs.items():
            if r < len(files):
                q.put((d, r, files[r], t_sub)); n += 1
        time.sleep(max(0, t_start + (r + 1) * a.interval - time.time()))
    while len(res) < n:
        k, v = out.get()
        if k == 'done':
            res.append(v); print(json.dumps(v), flush=True)
    [q.put(None) for _ in ps]
    L = sorted(x['latency_s'] for x in res)
    print(json.dumps({'summary': True, 'model': a.model, 'workers': a.workers, 'devices': len(devs), 'n': len(L),
                      'latency_median': L[len(L) // 2], 'latency_p95': L[int(len(L) * 0.95) - 1], 'latency_max': L[-1]}))
