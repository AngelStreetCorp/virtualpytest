#!/usr/bin/env python3
"""Subtitle QA: play/sample a film with subtitles and check every sample (see docs/tasks/TASK-50-subtitle-qa.md).

Local, no device:   python3 scripts/subtitle_qa/run.py --mkv tears_of_steel_subs.mkv --lang en,de --out out/
Sources:            --mkv <file>  (subtitle track burnt in by libass, same picture a player draws)
Audio transcript:   faster-whisper on the file's audio (cached), or --no-audio.
"""
import argparse
import os as _os
_os.environ.setdefault('OMP_THREAD_LIMIT', '1')   # tesseract: 1 thread per call, parallelism comes from the pool
import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from shared.src.lib.subtitle_qa import audio as audio_mod  # noqa: E402
from shared.src.lib.subtitle_qa import judge, pipeline  # noqa: E402
from shared.src.lib.subtitle_qa.frames import CaptureFrames, MkvFrames, calibrate_t0, probe  # noqa: E402
from shared.src.lib.subtitle_qa.ocr import read_subtitle  # noqa: E402
from shared.src.lib.subtitle_qa.sampler import plan_samples  # noqa: E402
from shared.src.lib.subtitle_qa.srt import parse_srt  # noqa: E402

ISO3 = {'en': 'eng', 'de': 'deu', 'fr': 'fra'}


def load_cues(mkv, lang, track, out_dir='.'):
    """Ground truth: a sidecar SRT next to the .mkv, else the one shipped in assets/, else the embedded track."""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.dirname(os.path.abspath(mkv)), os.path.join(here, 'assets')):
        side = glob.glob(os.path.join(d, f'*-{lang}.srt')) + glob.glob(os.path.join(d, f'*-{lang}-*.srt'))
        if side:
            return parse_srt(open(side[0], encoding='utf-8-sig').read()), side[0]
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, f'extracted-{lang}.srt')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', mkv, '-map', f'0:s:{track}', tmp], check=True)
    return parse_srt(open(tmp, encoding='utf-8').read()), f'{mkv}#s:{track}'


def process_lang(args, lang, info, segs, audio_lang, en_cues, en_audio):
    t_start = time.time()
    langs = info['subtitle_langs']
    if ISO3[lang] not in langs:
        raise SystemExit(f'{args.mkv} has no {ISO3[lang]} subtitle track (has {langs})')
    track = langs.index(ISO3[lang])
    cues, srt_path = load_cues(args.mkv, lang, track, args.out)
    if args.capture_dir:
        t0 = args.t0 if args.t0 else calibrate_t0(args.capture_dir, cues, lang, read_subtitle, judge.cer)[0]
        print(f'[{lang}] playback start t0={t0:.2f} (epoch), film time now {time.time() - t0:.1f}s', flush=True)
        fr, scene = CaptureFrames(args.capture_dir, t0), []
    else:
        fr = MkvFrames(args.mkv, track)
        scene = fr.scene_times() if args.scene else []
    samples = plan_samples(cues, args.credits_from or info['duration'], scene_times=scene)
    if args.limit:
        samples = samples[::max(1, len(samples) // args.limit)]
    print(f'[{lang}] {len(cues)} cues ({srt_path}), {len(samples)} samples, {len(scene)} scene triggers', flush=True)

    def progress(done, total, issues):
        if done % 100 == 0 or done == total:
            print(f'  {done}/{total} samples, {issues} with an issue', flush=True)

    rows, timings, missed = pipeline.analyze(samples, lambda s: fr.frame(s.t), cues, lang, segs, en_cues,
                                             args.boundary, args.timing_tol, args.workers, progress)
    for t in missed:
        print(f'  no frame at {t:.2f}s', flush=True)
    mode = 'live capture ' + os.path.basename(args.capture_dir) if args.capture_dir else 'local mkv'
    meta = pipeline.base_meta(os.path.basename(args.mkv), os.path.abspath(args.mkv), lang, audio_lang, len(cues), mode,
                              f'faster-whisper {args.whisper_model}' if segs else 'off')
    from shared.src.lib.subtitle_qa.ocr import ocr_info
    meta.update(pipeline.summarize(rows, timings, cues), wall=time.time() - t_start, ocr=ocr_info(lang),
                resolution={'source': f"{info.get('width')}x{info.get('height')}",
                            'capture': 'frames decoded from the file with the subtitle drawn by libass' if not args.capture_dir
                            else 'device capture'})
    if not meta['alignment_ok']:
        print(f'[{lang}] WARNING: only {meta["in_cue_matching"]}/{meta["in_cue_samples"]} in-cue samples match their cue; '
              'time alignment (t0) is suspect', flush=True)
    out_html = pipeline.write_outputs(args.out, lang, meta, rows, timings, cues, info['duration'])
    print(f'[{lang}] report {out_html} ({os.path.getsize(out_html) / 1e6:.1f} MB), wall {meta["wall"]:.0f}s, '
          f'samples {len(rows)}, issues {meta["issues"] or "none"}, mean CER {meta["mean_cer"] * 100:.1f}%', flush=True)
    return meta['issues']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mkv', required=True)
    ap.add_argument('--lang', default='en', help='comma list: en,de')
    ap.add_argument('--out', default='subtitle_qa_out')
    ap.add_argument('--workers', type=int, default=os.cpu_count() or 4)
    ap.add_argument('--whisper-model', default='base')
    ap.add_argument('--no-audio', action='store_true')
    ap.add_argument('--credits-from', type=float, default=0, help='seconds; from here on, on-screen text is picture text (end credits), not judged')
    ap.add_argument('--capture-dir', help='vpt-host capture folder of the device playing the film (live mode, run on the host)')
    ap.add_argument('--t0', type=float, default=0, help='epoch of film second 0; default: calibrated from the first cues')
    ap.add_argument('--audio-json', help='cached transcript (audio_transcript_*_words.json) instead of running whisper')
    ap.add_argument('--boundary', type=float, default=None, help='s around a cue edge where present/absent both pass (default 0.3 local, 1.0 with --capture-dir)')
    ap.add_argument('--timing-tol', type=float, default=None, help='late/early tolerance in s (default 1.0 local, 2.0 with --capture-dir)')
    ap.add_argument('--scene', action='store_true', help='add scene-change samples (one extra ffmpeg pass)')
    ap.add_argument('--limit', type=int, default=0, help='debug: cap the sample count')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    dev = bool(args.capture_dir)
    args.boundary = args.boundary if args.boundary is not None else (1.0 if dev else 0.3)
    args.timing_tol = args.timing_tol if args.timing_tol is not None else (2.0 if dev else 1.0)
    info = probe(args.mkv)
    segs, audio_lang = [], None
    if args.audio_json:
        d = json.load(open(args.audio_json))
        segs, audio_lang = [audio_mod.Segment(**x) for x in d['segments']], d['language']
    elif not args.no_audio:
        t0 = time.time()
        segs, audio_lang = audio_mod.transcribe_mkv(args.mkv, args.out, args.whisper_model)
        print(f'audio transcript: {len(segs)} segments, language {audio_lang}, {time.time() - t0:.0f}s', flush=True)
    langs = [l.strip() for l in args.lang.split(',') if l.strip()]
    en_cues = load_cues(args.mkv, 'en', info['subtitle_langs'].index('eng'), args.out)[0] if 'eng' in info['subtitle_langs'] else []
    for lang in langs:
        process_lang(args, lang, info, segs, audio_lang, en_cues, segs)


if __name__ == '__main__':
    main()
