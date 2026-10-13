"""Subtitle QA pipeline shared by the CLI (scripts/subtitle_qa/run.py) and the platform script
(test_scripts/subtitle_qa.py): OCR + judge every sample, cue timing, summary, report files."""
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Sequence

from . import audio as audio_mod
from . import judge, report
from .ocr import read_subtitle
from .sampler import Sample
from .srt import Cue


def analyze(samples: Sequence[Sample], frame_of: Callable, cues: Sequence[Cue], lang: str, segs, en_cues,
            edge: float, timing_tol: float, workers: int = 3,
            progress: Optional[Callable[[int, int, int], None]] = None):
    """OCR and judge every sample. `frame_of(sample)` returns a BGR image or None (no frame).
    `progress(done, total, issues_so_far)` is called after each sample. Returns (rows, timings, missed)."""

    def work(s):
        img = frame_of(s)
        return s, img, (read_subtitle(img, lang) if img is not None else None)

    rows, missed, issues = [], [], 0
    with ThreadPoolExecutor(max(1, workers)) as ex:
        for k, (s, img, ocr) in enumerate(ex.map(work, samples), 1):
            if img is None:
                missed.append(s.t)
            else:
                v = judge.judge_sample(s.t, cues, ocr, lang, edge)
                issues += 0 if v.ok else 1
                exp = ' / '.join(c.text.replace('\n', ' ') for c in judge.active_cues(cues, s.t, 0.0))
                rows.append({'t': s.t, 'reason': s.reason, 'thumb': report.thumb_b64(img),
                             'band': report.band_b64(img) if not v.ok else '', 'ocr': ocr.text,
                             'words': ocr.words, 'conf': ocr.mean_conf, 'contrast': ocr.contrast, 'lang': ocr.lang,
                             'expected': exp, 'audio': audio_mod.segment_at(segs, s.t) if segs else '',
                             'verdict': v.__dict__})
            if progress:
                progress(k, len(samples), issues)

    judge.downgrade_transient(rows, cues)

    timings = []
    for c in cues:
        hits = [r['t'] for r in rows if c.start - 1.5 <= r['t'] <= c.end + judge.STUCK_WINDOW and
                r['ocr'] and judge.cer(c.text, r['ocr']) <= judge.CER_OK]
        a_start = None
        if segs:
            ref = c
            if lang != 'en' and en_cues:  # audio is English: anchor on the English cue at the same time
                near = min(en_cues, key=lambda e: abs(e.start - c.start))
                ref = near if abs(near.start - c.start) <= 1.0 else None
            seg = audio_mod.audio_start_for(ref, segs) if ref is not None else None
            a_start = seg.start if seg else None
        timings.append(judge.judge_timing(c, min(hits) if hits else None, max(hits) if hits else None, a_start,
                                          timing_tol, timing_tol * 0.6).__dict__)
    return rows, timings, missed


REF_CHECKED = (judge.MISSING, judge.WRONG_TEXT, judge.TRUNCATED, judge.UNEXPECTED, judge.STUCK, judge.WRONG_LANG,
               judge.OVERLAP)


def check_against_source(rows: List[Dict], ref_frame_of: Callable[[float], object], cues: Sequence[Cue], lang: str,
                         progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
    """Is it the device or our OCR? For every sample with an issue, OCR the SAME moment of the source file (the
    subtitle drawn by libass at the file's own resolution, no capture path) and compare:
      - the source frame reads correctly -> the device/capture showed something else: the issue stands (source_ok)
      - the source frame fails the same way -> OCR cannot read this subtitle: not a device defect (ocr_limit)
      - text where no cue is defined, also in the source -> picture text of the film itself (in_source)
    The issue is cleared in the last two cases and the reason is kept on the row. Returns the counts."""
    todo = [r for r in rows if r['verdict']['issue'] in REF_CHECKED]
    out = {'checked': len(todo), 'source_ok': 0, 'ocr_limit': 0, 'in_source': 0, 'no_frame': 0}
    for k, r in enumerate(todo, 1):
        v = r['verdict']
        img = ref_frame_of(r['t'])
        if img is None:
            out['no_frame'] += 1
            continue
        ref = read_subtitle(img, lang)
        ref_v = judge.judge_sample(r['t'], cues, ref, lang)
        r['ref_ocr'], r['ref_band'] = ref.text, report.band_b64(img)
        r['ref_cer'] = ref_v.cer
        if v['issue'] == judge.UNEXPECTED and judge.has_text(ref):
            kind = 'in_source'
        elif ref_v.issue == v['issue'] or (ref_v.issue is not None and v['issue'] in (judge.MISSING, judge.WRONG_TEXT, judge.TRUNCATED)
                                            and ref_v.issue in (judge.MISSING, judge.WRONG_TEXT, judge.TRUNCATED)):
            kind = 'ocr_limit'
        else:
            kind = 'source_ok'
        r['ref_kind'] = kind
        out[kind] += 1
        if kind != 'source_ok':
            reason = ('OCR limit: the source file frame fails the same way' if kind == 'ocr_limit'
                      else 'picture text of the film (also in the source file), not a subtitle')
            v['note'] = f"{reason} (was {v['issue']}; source OCR: {ref.text or 'nothing'})"
            v['cleared'] = v['issue']
            v['issue'], v['ok'] = None, not v['flags']
        if progress:
            progress(k, len(todo))
    return out


def issue_counts(rows: List[Dict], timings: List[Dict]) -> Dict[str, int]:
    by: Dict[str, int] = {}
    for r in rows:
        for it in ([r['verdict']['issue']] if r['verdict']['issue'] else []) + r['verdict']['flags']:
            by[it] = by.get(it, 0) + 1
    for t in timings:
        if t['issue']:
            by[t['issue']] = by.get(t['issue'], 0) + 1
    return by


def summarize(rows: List[Dict], timings: List[Dict], cues: Sequence[Cue]) -> Dict:
    """Mean CER, median lag, and the alignment sanity check. It asks whether the film-time mapping is right, not
    whether OCR is good: a sample with text inside a cue counts as aligned when its text is closer to that cue
    than to any other cue (a noisy read of the right cue is aligned; the right text at the wrong time is not).
    Alignment is suspect when fewer than half of those samples are aligned."""
    cers = [r['verdict']['cer'] for r in rows if r['verdict']['state'] == 'present' and r['verdict']['cer'] is not None]
    lags = [t['lag_srt'] for t in timings if t['lag_srt'] is not None]
    present = [r for r in rows if r['verdict']['state'] == 'present' and r['ocr']]
    good = 0
    for r in present:
        expected = judge.active_cues(cues, r['t'], 0.0)
        best, _ = judge.best_cue(cues, r['ocr'])
        good += 1 if best is not None and best.index in {c.index for c in expected} else 0
    return {'mean_cer': statistics.mean(cers) if cers else 0.0, 'median_lag': statistics.median(lags) if lags else 0.0,
            'alignment_ok': (not present) or good / len(present) >= 0.5, 'in_cue_samples': len(present),
            'in_cue_matching': good, 'issues': issue_counts(rows, timings),
            'samples_with_issue': sum(1 for r in rows if r['verdict']['issue'] or r['verdict']['flags'])}


def build_issue_mosaic(rows: List[Dict], timings: List[Dict], cues, out_path: str) -> Optional[Dict]:
    """Error mosaic: one tile per problem cue (its first bad frame; for a timing-only issue, the frame closest to
    the cue start), drawn by the platform's step-mosaic builder so it looks like the run's own mosaic.
    Returns the build_step_mosaic dict ({'path', 'tiles', ...}) or None when there is nothing to show."""
    import base64
    import tempfile
    from shared.src.lib.utils.report_mosaic import build_step_mosaic
    groups = report.issue_groups(rows, timings, cues)
    if not groups:
        return None
    tmp = tempfile.mkdtemp(prefix='subqa_mosaic_')
    steps = []
    for key, g in groups.items():
        r = g['rows'][0] if g['rows'] else (min(rows, key=lambda x: abs(x['t'] - g['start'])) if rows else None)
        if r is None or not r.get('thumb'):
            continue
        path = os.path.join(tmp, f'{len(steps):03d}.jpg')
        with open(path, 'wb') as f:
            f.write(base64.b64decode(r['thumb']))
        label = f"{report._t(r['t'])} " + (f"cue {g['cue'].index} " if g['cue'] is not None else '') + \
            ', '.join(k for k, _ in g['issues'].most_common(2))
        steps.append({'step_end_screenshot_path': path, 'success': False, 'message': label, 'step_number': len(steps) + 1})
    info = build_step_mosaic(steps, out_path) if steps else None
    for f in os.listdir(tmp):
        os.unlink(os.path.join(tmp, f))
    os.rmdir(tmp)
    return info


def write_outputs(out_dir: str, lang: str, meta: Dict, rows: List[Dict], timings: List[Dict], cues, duration: float) -> str:
    """subtitle_qa_<lang>.html (self-contained), error_mosaic_<lang>.jpg and results_<lang>.json. Returns the HTML path."""
    import base64
    os.makedirs(out_dir, exist_ok=True)
    mosaic_path = os.path.join(out_dir, f'error_mosaic_{lang}.jpg')
    mosaic = build_issue_mosaic(rows, timings, cues, mosaic_path)
    mosaic_b64 = base64.b64encode(open(mosaic_path, 'rb').read()).decode() if mosaic else None
    out_html = os.path.join(out_dir, f'subtitle_qa_{lang}.html')
    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(report.render(meta, rows, timings, cues, duration, mosaic_b64))
    slim = [{k: v for k, v in r.items() if k != 'thumb'} for r in rows]
    with open(os.path.join(out_dir, f'results_{lang}.json'), 'w', encoding='utf-8') as f:
        json.dump({'meta': meta, 'rows': slim, 'timings': timings}, f, indent=1)
    return out_html


def base_meta(title: str, source: str, lang: str, audio_lang, n_cues: int, mode: str, audio_engine: str) -> Dict:
    return {'title': title, 'source': source, 'lang': lang, 'audio_lang': audio_lang, 'n_cues': n_cues,
            'when': time.strftime('%Y-%m-%d %H:%M'), 'mode': mode, 'audio_engine': audio_engine}
