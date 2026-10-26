#!/usr/bin/env python3
"""TASK-103 goal 3: CTC forced alignment of a Whisper transcript to its 1-minute audio (torchaudio MMS_FA).

Takes the sentence-level transcript of a task103_whisper_bench.py dump (<model>_<mp3>.json), aligns its words
to the audio with the multilingual CTC model (300 M parameters, 1 thread) and writes
<out>/<model>_<mp3>.json = {words: [{word,start,end}], wall_s, cpu_s}.  Needs torch + torchaudio (CPU).

  task103_forced_align.py --audio-dir <run>/audio --dump <bench dump> --out <fa dump> [--model tiny base]
"""
import argparse, glob, json, os, re, resource, subprocess, time
import numpy as np, torch, torchaudio

p = argparse.ArgumentParser()
p.add_argument('--audio-dir', required=True)
p.add_argument('--dump', required=True)
p.add_argument('--out', required=True)
p.add_argument('--model', nargs='+', default=['tiny', 'base'])
p.add_argument('--threads', type=int, default=1)
p.add_argument('--shard', default='0/1', help='i/n: take every n-th file starting at i (run n processes)')
p.add_argument('--min-mtime', type=float, default=0, help='only slots whose mp3 name mtime >= this')
p.add_argument('--max-mtime', type=float, default=1e18)
a = p.parse_args()
torch.set_num_threads(a.threads)
os.makedirs(a.out, exist_ok=True)
bundle = torchaudio.pipelines.MMS_FA
t0 = time.time()
net = bundle.get_model(with_star=False).eval()
tok, aligner = bundle.get_tokenizer(), bundle.get_aligner()
print(json.dumps({'model_load_s': round(time.time() - t0, 2)}), flush=True)


def roman(w):
    w = w.lower().replace('ä', 'a').replace('ö', 'o').replace('ü', 'u').replace('ß', 'ss')
    return re.sub(r"[^a-z']", '', w)


for m in a.model:
    i0, n0 = map(int, a.shard.split('/'))
    files = [f for f in sorted(glob.glob(f'{a.dump}/{m}_[0-9]*_1min_*.mp3.json')) if float(os.path.basename(f)[len(m) + 1:].split('_')[0]) >= a.min_mtime and float(os.path.basename(f)[len(m) + 1:].split('_')[0]) <= a.max_mtime]
    for f in files[i0::n0]:
        mp3 = os.path.basename(f)[len(m) + 1:-5]
        if os.path.exists(f'{a.out}/{m}_{mp3}.json'):
            continue  # already aligned
        d = json.load(open(f))
        words = [w for s in d['segments'] for w in s['text'].split()]
        rom = [(w, roman(w)) for w in words]
        rom = [(w, r) for w, r in rom if r]
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', f'{a.audio_dir}/{mp3}', '-ac', '1', '-ar', str(bundle.sample_rate),
                              '-f', 'f32le', '-'], capture_output=True, check=True).stdout
        wav = torch.from_numpy(np.frombuffer(raw, dtype=np.float32).copy())[None]
        r0, w0 = resource.getrusage(resource.RUSAGE_SELF), time.time()
        with torch.inference_mode():
            emission, _ = net(wav)
            spans = aligner(emission[0], tok([r for _, r in rom]))
        wall = time.time() - w0
        r1 = resource.getrusage(resource.RUSAGE_SELF)
        ratio = wav.shape[1] / emission.shape[1] / bundle.sample_rate
        out = [{'word': w, 'start': s[0].start * ratio, 'end': s[-1].end * ratio} for (w, _), s in zip(rom, spans)]
        json.dump({'words': out, 'wall_s': wall, 'cpu_s': (r1.ru_utime + r1.ru_stime) - (r0.ru_utime + r0.ru_stime),
                   'audio_s': wav.shape[1] / bundle.sample_rate}, open(f'{a.out}/{m}_{mp3}.json', 'w'))
        print(json.dumps({'file': mp3, 'model': m, 'n_words': len(out), 'wall_s': round(wall, 2),
                          'xrt': round(wall / (wav.shape[1] / bundle.sample_rate), 3)}), flush=True)
