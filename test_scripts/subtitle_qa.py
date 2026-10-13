#!/usr/bin/env python3
"""
Subtitle QA on a device that plays a film (TASK-50).

The device (a local_video device: VideoFileStreamController) plays the film from second 0 with one of its
subtitle tracks drawn into the picture. The script then works in two phases on the host:

  1. Capture (real time, as long as the film runs, ~0 CPU): at each planned sample time (dense around every
     SRT cue edge, sparse elsewhere) the matching capture frame is copied out of the device's hot capture
     folder, which only keeps ~3 minutes.
  2. Analyse (after playback): tesseract OCR + checks on every saved frame: subtitle present/absent, text vs
     the cue (CER, missing/extra words), truncated / stuck / overlapping / wrong-language / low-contrast,
     cue timing vs the SRT and vs the speech (word-timestamp transcript of the film's audio).

Result: a self-contained HTML report (one row per sample: frame, OCR text, expected cue, audio, verdict)
linked from the run's report as "Subtitle Report". The device's previous source is put back at the end.

Usage:
    python test_scripts/subtitle_qa.py --device device1 \
        --video /var/www/html/videos/tears_of_steel_subs_480p.mkv --lang en --credits_from 600

Docs: docs/user-guide/subtitle-qa.md, docs/tasks/TASK-50-subtitle-qa.md
"""

import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime

os.environ.setdefault('OMP_THREAD_LIMIT', '1')  # tesseract: one thread per call, the pool gives the parallelism

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device

ASSETS = os.path.join(project_root, 'scripts', 'subtitle_qa', 'assets')
ISO3 = {'en': 'eng', 'de': 'deu', 'fr': 'fra'}


# declared up here: the run form reads only the first 300 lines of the file to list the arguments
_script_args = [
    '--video:str:/var/www/html/videos/tears_of_steel_subs_480p.mkv',  # film with embedded subtitle tracks
    '--lang:str:en',                 # subtitle track to check: en, de, fr
    '--audio_json:str:',             # word-timestamp transcript of the film audio; empty = the shipped TOS one
    '--credits_from:float:600',      # stop at this film second (end credits are picture text); 0 = whole film
    '--boundary:float:0',            # s around a cue edge where present/absent both pass; 0 = 1.0 on a device
    '--timing_tol:float:0',          # late/early tolerance in s; 0 = 2.0 on a device
    '--max_issues:int:-1',           # fail the run above this many issues; -1 = report only
    '--workers:int:3',               # OCR threads in the analyse phase
]
_script_description = 'Play a film with subtitles on a video-file device and check every sampled frame (OCR, timing, language).'
_arg_descriptions = {
    'video': 'Path on the host of a film with embedded subtitle tracks (an .mkv); SRT next to it or in scripts/subtitle_qa/assets is the ground truth',
    'lang': 'Subtitle track to check (en, de, fr)',
    'audio_json': "Word-timestamp transcript of the film's audio (scripts/subtitle_qa/run.py writes one); empty = the shipped Tears of Steel one",
    'credits_from': 'Stop sampling at this film second; 0 = the whole film',
    'boundary': 'Seconds around a cue edge where present and absent both pass; 0 = 1.0 (device default)',
    'timing_tol': 'Late/early cue tolerance in seconds; 0 = 2.0 (device default)',
    'max_issues': 'Fail the run when more issues are found; -1 = report only (default)',
    'workers': 'OCR threads for the analyse phase (default 3)',
}


def record(context, message, success, details, screenshot=''):
    now = datetime.now().strftime('%H:%M:%S')
    context.record_step_immediately({
        'screenshot_path': screenshot or None, 'step_end_screenshot_path': screenshot or None,
        'action_screenshots': [screenshot] if screenshot else [],
        'success': success, 'message': message, 'from_node': 'subtitle_qa', 'to_node': 'subtitle_qa',
        'execution_time_ms': 0, 'start_time': now, 'end_time': now, 'actions': [],
        'verifications': [{'verification_type': 'subtitle', 'command': 'subtitle_qa', 'label': message,
                           'success': success, 'details': details}],
        'verification_results': [], 'step_category': 'subtitle_qa',
    })


def load_cues(video, lang, track, work_dir):
    """Ground truth: a sidecar *-<lang>.srt next to the video, else the shipped assets, else the embedded track."""
    import glob
    import subprocess
    from shared.src.lib.subtitle_qa.srt import parse_srt
    for d in (os.path.dirname(video), ASSETS):
        found = glob.glob(os.path.join(d, f'*-{lang}.srt'))
        if found:
            return parse_srt(open(found[0], encoding='utf-8-sig').read()), found[0]
    out = os.path.join(work_dir, f'track-{lang}.srt')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', video, '-map', f'0:s:{track}', out], check=True)
    return parse_srt(open(out, encoding='utf-8').read()), f'{video}#s:{track}'


def capture_listing(folder):
    out = []
    for e in os.scandir(folder):
        if e.name.startswith('capture_') and e.name.endswith('.jpg'):
            try:
                out.append((e.stat().st_mtime, e.path))
            except FileNotFoundError:
                pass
    out.sort()
    return out


def wait_for_restart(folder, since, timeout=45.0):
    """Epoch of film second 0: the first capture written after `since` that follows a gap (ffmpeg restarted).
    Captures come every 0.2 s; a restart leaves a gap of ~1 s or more."""
    end = time.time() + timeout
    while time.time() < end:
        files = capture_listing(folder)
        for (prev_mt, _), (mt, _) in zip(files, files[1:]):
            if mt > since and mt - prev_mt >= 0.7:
                return mt
        time.sleep(0.2)
    return None


@script('subtitle_qa', 'Subtitle QA: OCR + timing checks of a film played by the device', default_device='device1')
def main():
    args, context, device = get_args(), get_context(), get_device()
    from shared.src.lib.subtitle_qa import audio as audio_mod
    from shared.src.lib.subtitle_qa import pipeline
    from shared.src.lib.subtitle_qa.frames import MkvFrames, probe
    from shared.src.lib.subtitle_qa.ocr import ocr_info, roi_crop
    from shared.src.lib.subtitle_qa.sampler import plan_samples

    av = device._get_controller('av')
    if av is None or not hasattr(av, 'load_or_download'):
        context.error_message = f'{device.device_name} is not a video-file device (needs a local_video device)'
        context.overall_success = False
        return False
    video, lang = args.video, args.lang.strip().lower()
    if not os.path.exists(video):
        context.error_message = f'video not found on this host: {video}'
        context.overall_success = False
        return False
    info = probe(video)
    if ISO3.get(lang) not in info['subtitle_langs']:
        context.error_message = f'{video} has no {lang} subtitle track (has {info["subtitle_langs"]})'
        context.overall_success = False
        return False
    track = info['subtitle_langs'].index(ISO3[lang])
    work = tempfile.mkdtemp(prefix='subtitle_qa_')
    frames_dir = os.path.join(work, 'frames')
    os.makedirs(frames_dir)
    cues, srt_path = load_cues(video, lang, track, work)
    stop_at = args.credits_from if args.credits_from > 0 else info['duration']
    samples = plan_samples(cues, min(stop_at, info['duration']))
    capture_dir = os.path.join(av.video_capture_path, 'hot', 'captures')
    if not os.path.isdir(capture_dir):
        capture_dir = os.path.join(av.video_capture_path, 'captures')
    previous_source = av.video_file_path
    print(f'🔤 [subtitle_qa] {device.device_name}: {video} track {track} ({lang}), {len(cues)} cues, '
          f'{len(samples)} samples over {stop_at:.0f}s; captures {capture_dir}')

    segs, audio_lang = [], None
    audio_json = args.audio_json or os.path.join(ASSETS, 'TOS-audio-en-words.json')
    if os.path.exists(audio_json):
        d = json.load(open(audio_json))
        segs, audio_lang = [audio_mod.Segment(**x) for x in d['segments']], d['language']
    en_cues = cues if lang == 'en' else (load_cues(video, 'en', info['subtitle_langs'].index('eng'), work)[0]
                                         if 'eng' in info['subtitle_langs'] else [])

    try:
        # ---- play from 0 with the track burnt in (run_ffmpeg.sh reads <video>.subtrack) ----
        with open(video + '.subtrack', 'w') as f:
            f.write(str(track))
        since = time.time()
        if not av.load_or_download(video, restart=True):
            raise RuntimeError('could not switch the device source')
        t0 = wait_for_restart(capture_dir, since)
        record(context, f'Play {os.path.basename(video)} from 0 with the {lang} subtitle track', t0 is not None,
               {'video': video, 'track': track, 't0': t0, 'wait_s': round((t0 or time.time()) - since, 2)})
        if t0 is None:
            raise RuntimeError('the device did not restart playback within 45 s')
        print(f'🔤 [subtitle_qa] film second 0 at {t0:.2f} ({t0 - since:.1f}s after the switch)')

        # ---- phase 1: copy the frame of each sample as playback reaches it ----
        saved, missed, last_emit = {}, [], 0.0
        for k, s in enumerate(samples, 1):
            wait = t0 + s.t + 0.5 - time.time()  # the frame is on disk ~0.2-0.5 s after its time
            if wait > 0:
                time.sleep(wait)
            files = capture_listing(capture_dir)
            mt, path = min(files, key=lambda x: abs(x[0] - (t0 + s.t))) if files else (None, None)
            if path is None or abs(mt - (t0 + s.t)) > 0.3:
                # no capture within 0.3 s of this moment: the capture had a gap here
                gap = None if path is None else round(mt - (t0 + s.t), 2)
                missed.append(s.t)
                print(f'🔤 [subtitle_qa] missed film {s.t:.2f}s: nearest capture {gap}s away')
            else:
                dst = os.path.join(frames_dir, f'{k:04d}.jpg')
                try:
                    shutil.copyfile(path, dst)
                    saved[s.t] = dst
                except FileNotFoundError:  # rotated away between listing and copy
                    missed.append(s.t)
            if time.time() - last_emit >= 10 or k == len(samples):
                last_emit = time.time()
                msg = (f'Capturing: film {int(s.t // 60)}:{int(s.t % 60):02d} / {int(stop_at // 60)}:{int(stop_at % 60):02d}, '
                       f'{len(saved)}/{len(samples)} frames, {len(missed)} missed')
                print(f'🔤 [subtitle_qa] {msg}')
                context.emit_progress(message=msg)
        capture_ok = len(missed) <= 0.05 * len(samples)
        record(context, f'Captured {len(saved)} of {len(samples)} sample frames', capture_ok,
               {'saved': len(saved), 'missed': len(missed), 'missed_at': missed[:50]})

        # ---- phase 2: analyse the saved frames ----
        import cv2
        t_an = time.time()
        state = {'last': 0.0}

        def progress(done, total, issues):
            if time.time() - state['last'] >= 10 or done == total:
                state['last'] = time.time()
                msg = f'Analysing: {done}/{total} samples, {issues} with an issue so far'
                print(f'🔤 [subtitle_qa] {msg}')
                context.emit_progress(message=msg)

        kept = [s for s in samples if s.t in saved]
        edge = args.boundary if args.boundary > 0 else 1.0       # device capture paths add ~1 s jitter
        tol = args.timing_tol if args.timing_tol > 0 else 2.0
        rows, timings, _ = pipeline.analyze(kept, lambda s: cv2.imread(saved[s.t]), cues, lang, segs, en_cues,
                                            edge, tol, args.workers, progress)
        # is it the device or our OCR? re-read every flagged sample from the source file at the same moment
        src = MkvFrames(video, track)
        state['last'] = 0.0

        def ref_progress(done, total):
            if time.time() - state['last'] >= 10 or done == total:
                state['last'] = time.time()
                msg = f'Checking flagged samples against the source file: {done}/{total}'
                print(f'🔤 [subtitle_qa] {msg}')
                context.emit_progress(message=msg)

        source_check = pipeline.check_against_source(rows, src.frame, cues, lang, ref_progress)
        print(f'🔤 [subtitle_qa] source check: {source_check}')
        cap_img = cv2.imread(next(iter(saved.values()))) if saved else None
        band_h, band_w = roi_crop(cap_img)[0].shape[:2] if cap_img is not None else (0, 0)
        stretched = (cap_img is not None and info.get('width') and info.get('height') and
                     abs(cap_img.shape[1] / cap_img.shape[0] - info['width'] / info['height']) > 0.05)
        from shared.src.lib.utils.cloudflare_utils import _build_script_artifact_folder_name, get_cloudflare_utils
        rid = getattr(context, 'script_result_id', None)
        run_report_url = get_cloudflare_utils().get_url_for_report_asset(
            f"script-reports/{device.device_model}/{_build_script_artifact_folder_name('subtitle_qa', '', rid)}/report.html") if rid else ''
        meta = pipeline.base_meta(os.path.basename(video), f'{context.host.host_name if context.host else ""} '
                                  f'{device.device_name} · {video}', lang, audio_lang, len(cues),
                                  f'device {device.device_id} (capture, then analyse)',
                                  'faster-whisper base (film transcript)' if segs else 'off')
        meta.update(pipeline.summarize(rows, timings, cues), wall=time.time() - t_an, source_check=source_check,
                    ocr=ocr_info(lang), run_report_url=run_report_url,
                    resolution={'source': f"{info.get('width')}x{info.get('height')} ({os.path.basename(video)})",
                                'capture': (f'{cap_img.shape[1]}x{cap_img.shape[0]} device capture (5 fps)'
                                            + (', aspect stretched from the source' if stretched else '')) if cap_img is not None else '',
                                'band': f'{band_w}x{band_h} px, read at 2x' if band_w else ''})
        out_html = pipeline.write_outputs(work, lang, meta, rows, timings, cues, info['duration'])
        analyse_s = time.time() - t_an

        # ---- report: upload next to the script reports ----
        run_id = getattr(context, 'script_result_id', None) or datetime.now().strftime('%Y%m%d-%H%M%S')
        res = get_cloudflare_utils().upload_files(
            [{'local_path': out_html, 'remote_path': f'script-reports/subtitle_qa/{run_id}/subtitle_qa_{lang}.html'}],
            for_report_assets=True)
        report_url = res['uploaded_files'][0]['url'] if res.get('uploaded_files') else ''
        context.custom_data['subtitle_report_url'] = report_url
        issues = meta['issues']
        n_issues = sum(issues.values())
        within = args.max_issues < 0 or n_issues <= args.max_issues
        # the error mosaic is this step's screenshot, so the run's own report and step mosaic show it; kept
        # outside `work` (deleted below) until the executor has uploaded the report
        mosaic_src = os.path.join(work, f'error_mosaic_{lang}.jpg')
        mosaic = ''
        if os.path.exists(mosaic_src):
            mosaic = os.path.join(tempfile.gettempdir(), f'subtitle_qa_mosaic_{run_id}.jpg')
            shutil.copyfile(mosaic_src, mosaic)
        record(context, f'Subtitle check: {len(rows)} samples, {meta["samples_with_issue"]} with an issue, '
                        f'mean CER {meta["mean_cer"] * 100:.1f}%', meta['alignment_ok'] and within,
               {'issues': issues, 'mean_cer': round(meta['mean_cer'], 4), 'median_lag_s': meta['median_lag'],
                'alignment_ok': meta['alignment_ok'], 'analyse_s': round(analyse_s, 1), 'report_url': report_url}, mosaic)
        context.metadata = {'subtitle_qa': {'video': video, 'lang': lang, 'samples': len(samples), 'judged': len(rows),
                                            'missed': len(missed), 'issues': issues, 'mean_cer': meta['mean_cer'],
                                            'median_lag_s': meta['median_lag'], 'alignment_ok': meta['alignment_ok'],
                                            'analyse_s': round(analyse_s, 1), 'report_url': report_url,
                                            'source_check': source_check}}
        print(f'🔤 [subtitle_qa] analysed {len(rows)} samples in {analyse_s:.0f}s; issues {issues or "none"}; '
              f'report {report_url or "(upload failed)"}')
        context.overall_success = bool(capture_ok and meta['alignment_ok'] and within and report_url)
        if not meta['alignment_ok']:
            context.error_message = 'time alignment suspect: most in-cue samples do not match their cue'
        elif not within:
            context.error_message = f'{n_issues} subtitle issues (max {args.max_issues})'
        return context.overall_success
    except Exception as e:
        context.error_message = str(e)
        context.overall_success = False
        return False
    finally:
        try:
            os.remove(video + '.subtrack')
        except OSError:
            pass
        if previous_source and previous_source != video:
            av.load_or_download(previous_source)
        else:  # same file before: restart it without the burnt-in track
            av.load_or_download(video, restart=True)
        shutil.rmtree(work, ignore_errors=True)
        md = (context.metadata or {}).get('subtitle_qa', {})
        context.execution_summary = (
            f"Track {lang} · {md.get('judged', 0)} of {md.get('samples', 0)} samples analysed · "
            f"issues: {', '.join(f'{k} {v}' for k, v in (md.get('issues') or {}).items()) or 'none'}"
            + (f"\nError: {context.error_message}" if context.error_message else ''))


main._script_args = _script_args
main._script_description = _script_description
main._arg_descriptions = _arg_descriptions
main._target_rules = {
    'target_type': 'device',
    'host_os': 'linux',
    'device_model': 'local_video',
}


if __name__ == "__main__":
    main()
