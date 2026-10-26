#!/usr/bin/env python3
"""TASK-103: time faster-whisper on 1-minute audio files, with the parameters of
`shared/src/lib/utils/audio_transcription_utils.transcribe_audio` (int8, 1 thread, beam 1, vad_filter,
language auto-detected). Optionally dumps the segments (with word timestamps) as JSON for goal 3.

  task103_whisper_bench.py --model tiny --files a.mp3 b.mp3 [--words] [--dump-dir DIR] [--model-dir DIR]

Prints one JSON line per file: {file, model, audio_s, wall_s, xrt (= wall/audio, lower is faster), cpu_s,
n_segments, language} and a final summary line. Model load time is reported once, not in xrt.
"""
import argparse, json, os, resource, time

p = argparse.ArgumentParser()
p.add_argument('--model', default='tiny')
p.add_argument('--files', nargs='+', required=True)
p.add_argument('--words', action='store_true', help='word_timestamps=True')
p.add_argument('--threads', type=int, default=1)
p.add_argument('--dump-dir')
p.add_argument('--model-dir', help='download_root for the model cache')
p.add_argument('--language', default=None)
a = p.parse_args()

from faster_whisper import WhisperModel
t = time.time()
model = WhisperModel(a.model, device='cpu', compute_type='int8', cpu_threads=a.threads, num_workers=1,
                     download_root=a.model_dir)
print(json.dumps({'model_load_s': round(time.time() - t, 2), 'model': a.model}), flush=True)
rows = []
for f in a.files:
    r0, w0 = resource.getrusage(resource.RUSAGE_SELF), time.time()
    segs, info = model.transcribe(f, beam_size=1, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
                                  language=a.language, word_timestamps=a.words, condition_on_previous_text=False,
                                  temperature=0)
    segs = list(segs)
    wall = time.time() - w0
    r1 = resource.getrusage(resource.RUSAGE_SELF)
    cpu = (r1.ru_utime + r1.ru_stime) - (r0.ru_utime + r0.ru_stime)
    row = {'file': os.path.basename(f), 'model': a.model, 'words': a.words, 'audio_s': round(info.duration, 2),
           'wall_s': round(wall, 2), 'xrt': round(wall / info.duration, 3), 'cpu_s': round(cpu, 2),
           'n_segments': len(segs), 'language': info.language}
    rows.append(row)
    print(json.dumps(row), flush=True)
    if a.dump_dir:
        os.makedirs(a.dump_dir, exist_ok=True)
        out = [{'start': s.start, 'end': s.end, 'text': s.text.strip(),
                'words': [{'start': w.start, 'end': w.end, 'word': w.word} for w in (s.words or [])]} for s in segs]
        json.dump({'language': info.language, 'segments': out, 'wall_s': wall, 'cpu_s': cpu},
                  open(os.path.join(a.dump_dir, f'{a.model}{"_w" if a.words else ""}_{os.path.basename(f)}.json'), 'w'))
if rows:
    xs = sorted(r['xrt'] for r in rows)
    print(json.dumps({'summary': True, 'model': a.model, 'words': a.words, 'n': len(rows),
                      'xrt_median': xs[len(xs) // 2], 'xrt_max': xs[-1]}))
