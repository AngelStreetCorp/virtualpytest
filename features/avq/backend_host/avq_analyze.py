#!/usr/bin/env python3
"""
AVQ analyzer — pure, side-effect-free audio/video quality measurement for one device.

Reads ONLY derived files already on disk (full-res JPEG captures + 10-min MP3 audio
chunks). NEVER touches the USB capture card, so it cannot conflict with the live
run_ffmpeg.sh that owns the device (MacroSilicon MS2109 = single-opener).

Validated on host1 (ffmpeg 5.1.8) 2026-06-09 — see docs/agent/AVQ_IMPLEMENTATION.md §2.

Two callers share this module:
  - avq_monitor.py        → continuous per-minute history
  - verification (later)  → on-demand "what's the MOS for this exact window?"

This file has no DB / network dependencies so it can be run standalone for testing:
    python3 avq_analyze.py capture1            # analyze last 60s of capture1
    python3 avq_analyze.py capture1 --window 30
"""
import os
import re
import sys
import glob
import time
import shutil
import logging
import subprocess
from datetime import datetime, timezone

logger = logging.getLogger('avq')

# Tunables (keep in ONE place; blockiness is scale-sensitive so VIDEO_SCALE is a
# permanent canonical choice, not a free knob — see §2b of the design doc).
VIDEO_SAMPLE_FPS = 1            # frames/sec sampled from the 5fps captures
VIDEO_SCALE = 0                # 0 = full-res (accurate blockiness); e.g. 640 to save CPU
CAPTURE_FPS = 5                # native capture fps (for window→frame math)
AUDIO_SILENCE_DB = -50.0       # silencedetect noise floor
FFMPEG_TIMEOUT = 45            # seconds, per pass

# Quality-event thresholds (over-threshold => "high X" event)
BLUR_EVENT_THRESHOLD = 6.0
BLOCK_EVENT_THRESHOLD = 5.0


# --------------------------------------------------------------------------- #
# Path helpers (reuse the centralized storage utils; fall back for standalone) #
# --------------------------------------------------------------------------- #
def _captures_dir(capture_folder):
    try:
        from shared.src.lib.utils.storage_path_utils import get_captures_path
        return get_captures_path(capture_folder)
    except Exception:
        base = f"/var/www/html/stream/{capture_folder}"
        hot = os.path.join(base, 'hot', 'captures')
        return hot if os.path.isdir(hot) else os.path.join(base, 'captures')


def _audio_dirs(capture_folder):
    """Return candidate audio dirs (hot + cold) holding chunk_10min_*.mp3."""
    dirs = []
    try:
        from shared.src.lib.utils.storage_path_utils import (
            get_audio_path, get_cold_storage_path)
        dirs.append(get_audio_path(capture_folder))
        dirs.append(get_cold_storage_path(capture_folder, 'audio'))
    except Exception:
        base = f"/var/www/html/stream/{capture_folder}"
        dirs.append(os.path.join(base, 'hot', 'audio'))
        dirs.append(os.path.join(base, 'audio'))
    return [d for d in dict.fromkeys(dirs) if d and os.path.isdir(d)]


def _metadata_dir(capture_folder):
    try:
        from shared.src.lib.utils.storage_path_utils import get_metadata_path
        return get_metadata_path(capture_folder)
    except Exception:
        base = f"/var/www/html/stream/{capture_folder}"
        hot = os.path.join(base, 'hot', 'metadata')
        return hot if os.path.isdir(hot) else os.path.join(base, 'metadata')


def _transcript_manifest(capture_folder):
    base = f"/var/www/html/stream/{capture_folder}"
    for p in (os.path.join(base, 'transcript', 'transcript_manifest.json'),
              os.path.join(base, 'hot', 'transcript', 'transcript_manifest.json')):
        if os.path.exists(p):
            return p
    try:
        from shared.src.lib.utils.storage_path_utils import get_transcript_path
        p = os.path.join(get_transcript_path(capture_folder), 'transcript_manifest.json')
        return p if os.path.exists(p) else None
    except Exception:
        return None


def _newest_mp3(capture_folder):
    newest, newest_mtime = None, -1
    for d in _audio_dirs(capture_folder):
        for f in glob.glob(os.path.join(d, '*', 'chunk_10min_*.mp3')):
            # skip language-dubbed chunks (chunk_10min_0_es.mp3)
            if re.search(r'chunk_10min_\d+\.mp3$', f):
                m = os.path.getmtime(f)
                if m > newest_mtime:
                    newest, newest_mtime = f, m
    return newest


def _recent_captures(capture_folder, window_seconds):
    """Newest JPEG captures within the window (excludes thumbnails)."""
    cdir = _captures_dir(capture_folder)
    if not os.path.isdir(cdir):
        return cdir, []
    files = [f for f in glob.glob(os.path.join(cdir, 'capture_*.jpg'))
             if 'thumbnail' not in f]
    if not files:
        return cdir, []
    files.sort(key=os.path.getmtime, reverse=True)
    cutoff = time.time() - window_seconds
    recent = [f for f in files if os.path.getmtime(f) >= cutoff]
    # Fallback: if mtimes are odd, just take the newest window*fps frames
    if not recent:
        recent = files[: int(window_seconds * CAPTURE_FPS)]
    recent.sort(key=os.path.getmtime)  # chronological
    return cdir, recent


# --------------------------------------------------------------------------- #
# ffmpeg runners                                                               #
# --------------------------------------------------------------------------- #
def _run_ffmpeg(args):
    cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-nostats'] + args + ['-f', 'null', '-']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
        return r.stderr or ''
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg timeout: %s", ' '.join(cmd[:8]))
        return ''
    except Exception as e:  # noqa: BLE001
        logger.warning("ffmpeg error: %s", e)
        return ''


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Audio                                                                        #
# --------------------------------------------------------------------------- #
def analyze_audio(capture_folder, window_seconds=60):
    """Loudness / silence / saturation from the newest MP3 chunk's last `window`."""
    out = {
        'audio_level_db': None,
        'loudness_lkfs': None, 'loudness_range': None, 'true_peak_dbtp': None,
        'saturation_score': None, 'silence_seconds': 0.0, 'audio_availability': None,
        'audio_mos': None,
    }
    mp3 = _newest_mp3(capture_folder)
    if not mp3:
        logger.info("[%s] no audio chunk found", capture_folder)
        return out

    stderr = _run_ffmpeg([
        '-sseof', f'-{int(window_seconds)}', '-i', mp3,
        '-af', (f'ebur128=peak=true,astats=metadata=1:reset=0,'
                f'silencedetect=n={AUDIO_SILENCE_DB}dB:d=0.5,volumedetect'),
    ])

    # volumedetect mean level → raw "audio level" (same metric as the live overlay's
    # dB; distinct from K-weighted/gated LKFS loudness).
    m = re.findall(r'mean_volume:\s*(-?[\d.]+)\s*dB', stderr)
    if m:
        out['audio_level_db'] = _f(m[-1])

    # ebur128 summary block (last occurrence of each label)
    m = re.findall(r'I:\s*(-?[\d.]+|-?inf)\s*LUFS', stderr)
    if m:
        out['loudness_lkfs'] = _f(m[-1])
    m = re.findall(r'LRA:\s*([\d.]+)\s*LU', stderr)
    if m:
        out['loudness_range'] = _f(m[-1])
    m = re.findall(r'Peak:\s*(-?[\d.]+|-?inf)\s*dBFS', stderr)
    if m:
        out['true_peak_dbtp'] = -120.0 if m[-1] == '-inf' else _f(m[-1])

    # silencedetect → total silence + number of distinct silence spans (events)
    sil = re.findall(r'silence_duration:\s*([\d.]+)', stderr)
    out['silence_seconds'] = round(sum(float(x) for x in sil), 2)
    out['_silence_spans'] = [float(x) for x in sil]

    # astats Overall peak level → clipping/saturation proxy
    peaks = re.findall(r'Peak level dB:\s*(-?[\d.]+|-?inf)', stderr)
    peak_level = None
    for p in peaks:
        if p != '-inf':
            peak_level = _f(p)  # last finite peak (Overall printed last)
    if peak_level is not None:
        # within 0.5 dB of full-scale => clipping
        out['saturation_score'] = round(max(0.0, min(1.0, (peak_level + 0.5) / 0.5)), 3)
    else:
        out['saturation_score'] = 0.0

    out['audio_availability'] = round(
        max(0.0, 1.0 - out['silence_seconds'] / max(1, window_seconds)), 3)
    out['audio_mos'] = _audio_mos(out, window_seconds)
    return out


def _audio_mos(a, window_seconds):
    """APPROXIMATE audio MOS. 0 = no audio; otherwise 1..5."""
    lkfs = a.get('loudness_lkfs')
    if lkfs is None or lkfs <= -60:           # no audio at all → MOS 0
        return 0.0
    silence_frac = (a.get('silence_seconds') or 0) / max(1, window_seconds)
    dev = abs(lkfs - (-23.0))                 # deviation from EBU target
    mos = 5.0 - dev * 0.05 - silence_frac * 4.0 - (a.get('saturation_score') or 0) * 1.0
    return round(max(1.0, min(5.0, mos)), 2)


# --------------------------------------------------------------------------- #
# Video                                                                        #
# --------------------------------------------------------------------------- #
def analyze_video(capture_folder, window_seconds=60):
    """Blur / blockiness / jerkiness from sampled full-res JPEG captures."""
    out = {
        'blurriness_score': None, 'blockiness_score': None, 'jerkiness_score': None,
        'clean_video_seconds': None, 'video_availability': None, 'video_mos': None,
        '_frames': 0,
    }
    cdir, frames = _recent_captures(capture_folder, window_seconds)
    expected = max(1, int(window_seconds * CAPTURE_FPS))
    out['video_availability'] = round(min(1.0, len(frames) / expected), 3)
    if not frames:
        logger.info("[%s] no recent captures in %s", capture_folder, cdir)
        return out

    # Sample down to VIDEO_SAMPLE_FPS by taking every Nth frame.
    step = max(1, CAPTURE_FPS // max(1, VIDEO_SAMPLE_FPS))
    sampled = frames[::step]
    out['_frames'] = len(sampled)

    # Symlink sampled frames into a scratch dir with sequential names so ffmpeg's
    # image2 glob is deterministic (avoids gaps in the capture_NNN numbering).
    scratch = os.path.join('/tmp', f'avq_{capture_folder}_{os.getpid()}')
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch, exist_ok=True)
    try:
        for i, src in enumerate(sampled):
            try:
                os.symlink(src, os.path.join(scratch, f'f{i:06d}.jpg'))
            except FileExistsError:
                pass
        vf = []
        if VIDEO_SCALE:
            vf.append(f'scale={VIDEO_SCALE}:-1')
        # NOTE: siti was dropped — its summary doesn't parse on ffmpeg 5.1.8 and it's
        # pure wasted CPU. Jerkiness is sourced from detector.py's freeze pixel-diff
        # series instead (Phase 1.1, see docs/agent/AVQ_IMPLEMENTATION.md §2c).
        vf += ['blurdetect', 'blockdetect']
        stderr = _run_ffmpeg([
            '-f', 'image2', '-framerate', str(VIDEO_SAMPLE_FPS),
            '-pattern_type', 'glob', '-i', os.path.join(scratch, 'f*.jpg'),
            '-vf', ','.join(vf),
        ])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    m = re.findall(r'blur mean:\s*([\d.]+)', stderr)
    if m:
        out['blurriness_score'] = round(sum(float(x) for x in m) / len(m), 3)
    m = re.findall(r'block mean:\s*([\d.]+)', stderr)
    if m:
        out['blockiness_score'] = round(sum(float(x) for x in m) / len(m), 3)

    # jerkiness_score stays None for now — Phase 1.1 wires it from detector.py's
    # per-frame freeze pixel-diff series (real 5fps temporal signal, zero extra cost).

    # MVP placeholder: clean-video == availability * window. Proper version joins the
    # incident timeline (blackscreen/freeze) — tracked as Phase 1.1 in the doc.
    out['clean_video_seconds'] = round(out['video_availability'] * window_seconds, 1)
    out['video_mos'] = _video_mos(out)
    return out


# Soft-threshold breakpoints calibrated to the observed fleet distribution
# (quality_metrics, 2026-06-09): blur p50≈5.6/max≈8.6, block p50≈8.8/p95≈40.
# (lo, hi): value <= lo -> 0 badness; >= hi -> 1 badness; linear between.
# IMPORTANT: captures are JPEGs, whose own 8x8 DCT blocking + scene detail inflate
# blockdetect — so blockiness is treated as a weak, saturating, RELATIVE signal,
# not an absolute codec-quality measure. True defects come from the blackscreen/
# freeze/macroblock incident detector, not this score. MOS stays APPROXIMATE.
_BLUR_BAD = (4.0, 9.0)
_BLOCK_BAD = (10.0, 40.0)


def _badness(value, lo, hi):
    if value is None:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _video_mos(v):
    """APPROXIMATE, relative video MOS. 0 = no video; otherwise 1..5."""
    if v.get('video_availability') is not None and v['video_availability'] < 0.2:
        return 0.0  # no video → MOS 0
    b_blur = _badness(v.get('blurriness_score'), *_BLUR_BAD)
    b_block = _badness(v.get('blockiness_score'), *_BLOCK_BAD)
    # blur weighted more than the JPEG-confounded blockiness; cap total drop at 3
    # points so normal-but-detailed content lands ~4.5 and only clear degradation ~2.
    badness = 0.55 * b_blur + 0.45 * b_block
    return round(max(1.0, min(5.0, 5.0 - 3.0 * badness)), 2)


# --------------------------------------------------------------------------- #
# Subtitles + transcription + translation (only populated when those features  #
# are enabled; everything stays None otherwise so columns are simply NULL).    #
# --------------------------------------------------------------------------- #
def analyze_text(capture_folder, window_seconds=60):
    """Transcript & translation availability from the transcript manifest.
    (Subtitle OCR is aggregated in analyze_incidents over the full frame set.)"""
    import json
    out = {
        'transcript_available': None, 'transcript_language': None,
        'transcript_text': None,
        'translation_languages': None, 'dubbed_languages': None,
    }
    man = _transcript_manifest(capture_folder)
    if man:
        try:
            chunks = (json.load(open(man)) or {}).get('chunks') or []
        except Exception:
            chunks = []
        if chunks:
            # Select the MOST RECENT chunk by its `created` unix timestamp — NOT by
            # max(hour): hour numbers wrap 0..23, so max(hour) would pick yesterday's
            # 23:00 chunk when the current hour is < 23.
            latest = max(chunks, key=lambda c: c.get('created') or 0)
            # The manifest entry carries the language + segment_count but NOT the text.
            # Read the chunk file itself for the recognised transcript text.
            text = ''
            lang = latest.get('language')
            chunk = os.path.join(os.path.dirname(man), str(latest.get('hour', '')), latest.get('name', ''))
            try:
                cdata = json.load(open(chunk))
                text = (cdata.get('transcript') or '').strip()
                lang = cdata.get('language') or lang
            except Exception:
                pass
            out['transcript_available'] = 1.0 if (text or latest.get('segment_count')) else 0.0
            out['transcript_language'] = lang or None
            # Bound the per-minute row: a 10-min transcript is normally well under this.
            out['transcript_text'] = (text[:4000] or None)
            langs = [l for l in (latest.get('available_languages') or []) if l != 'original']
            out['translation_languages'] = ','.join(langs) if langs else ''
            dub = latest.get('available_dubbed_languages') or []
            out['dubbed_languages'] = ','.join(dub) if dub else ''
    return out


# --------------------------------------------------------------------------- #
# Incidents — blackscreen / freeze / macroblocks from detector.py metadata     #
# (the realtime detector already writes these per frame; AVQ just aggregates). #
# --------------------------------------------------------------------------- #
def analyze_incidents(capture_folder, window_seconds=60):
    """Coverage of blackscreen/freeze/macroblocks over the window, from the
    per-frame metadata JSONs. clean_fraction = frames that are real video
    (not blackscreen, not freeze)."""
    import json
    out = {'blackscreen_seconds': None, 'freeze_seconds': None,
           'macroblocks_seconds': None, 'clean_fraction': None, '_events': {}}
    mdir = _metadata_dir(capture_folder)
    if not os.path.isdir(mdir):
        return out
    files = glob.glob(os.path.join(mdir, 'capture_*.json'))
    if not files:
        return out
    cutoff = time.time() - window_seconds
    # CHRONOLOGICAL order so we can run-length the per-frame booleans into events.
    recent = sorted((f for f in files if os.path.getmtime(f) >= cutoff),
                    key=os.path.getmtime)
    bs_flags, fr_flags, mb_flags = [], [], []
    au = au_total = 0
    sub_checked = sub_with = 0
    sub_langs = {}
    sub_text = None   # most recent non-empty OCR'd subtitle line (frames are chronological)
    for f in recent:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        # Subtitle OCR (written by subtitle_monitor) — count BEFORE the blackscreen
        # gate, since it can land on frames the detector hasn't tagged yet.
        sa = d.get('subtitle_analysis')
        if sa and not sa.get('skipped'):
            sub_checked += 1
            if sa.get('has_subtitles'):
                sub_with += 1
                lang = sa.get('detected_language')
                if lang and lang != 'unknown':
                    sub_langs[lang] = sub_langs.get(lang, 0) + 1
                txt = (sa.get('extracted_text') or '').strip()
                if txt:
                    sub_text = txt[:500]   # subtitle lines are short; keep latest
        if 'blackscreen' not in d:   # error / not-yet-analyzed frame
            continue
        bs_flags.append(bool(d.get('blackscreen')))
        fr_flags.append(bool(d.get('freeze')))
        mb_flags.append(bool(d.get('macroblocks')))
        # Detector's own audio decision (same source as the overlay / transcript
        # pipeline). Authoritative for "is there audio" — see _audio_present_fraction.
        if 'audio' in d:
            au_total += 1
            if d.get('audio'):
                au += 1
    out['_subtitle_availability'] = round(sub_with / sub_checked, 3) if sub_checked else None
    out['_subtitle_language'] = max(sub_langs, key=sub_langs.get) if sub_langs else None
    out['_subtitle_text'] = sub_text
    total = len(bs_flags)
    if total == 0:
        return out
    frame_dur = window_seconds / total   # seconds represented by one frame
    out['blackscreen_seconds'] = round(sum(bs_flags) * frame_dur, 1)
    out['freeze_seconds'] = round(sum(fr_flags) * frame_dur, 1)
    out['macroblocks_seconds'] = round(sum(mb_flags) * frame_dur, 1)
    out['clean_fraction'] = round(max(0.0, 1.0 - (sum(bs_flags) + sum(fr_flags)) / total), 3)
    out['_audio_present_fraction'] = round(au / au_total, 3) if au_total else None
    ev = {}
    for name, flags in (('blackscreen', bs_flags), ('freeze', fr_flags),
                        ('macroblocks', mb_flags)):
        r = _event_runs(flags, frame_dur, window_seconds)
        if r:
            ev[name] = r
    out['_events'] = ev
    return out


def _event_runs(flags, frame_dur, window_seconds):
    """Run-length stats for a chronological boolean series → {count, totalMs,
    avgMs, longestMs, perMinute}. Distinguishes one long incident from many blips."""
    count = longest = cur = total = 0
    for f in flags:
        if f:
            cur += 1
            total += 1
            longest = max(longest, cur)
        elif cur:
            count += 1
            cur = 0
    if cur:
        count += 1
    if count == 0:
        return None
    return {
        'count': count,
        'totalMs': int(total * frame_dur * 1000),
        'avgMs': int(total / count * frame_dur * 1000),
        'longestMs': int(longest * frame_dur * 1000),
        'perMinute': round(count * 60.0 / max(1, window_seconds), 3),
    }


# --------------------------------------------------------------------------- #
# Events — run-length encoded incidents (count / duration per type)           #
# --------------------------------------------------------------------------- #
def _build_events(audio, video, window_seconds):
    ev = {}
    sil = audio.get('silence_seconds') or 0
    spans = audio.get('_silence_spans') or []
    if sil > 0:
        n = len(spans) or 1
        ev['noSound'] = {
            'count': n,
            'totalMs': int(sil * 1000),
            'avgMs': int(sil / n * 1000),
            'longestMs': int((max(spans) if spans else sil) * 1000),
            'perMinute': round(n * 60.0 / max(1, window_seconds), 3),
        }
    blur = video.get('blurriness_score')
    if blur is not None and blur >= BLUR_EVENT_THRESHOLD:
        ev['highBlurriness'] = {'count': 1, 'totalMs': int(window_seconds * 1000),
                                'perMinute': round(60.0 / max(1, window_seconds), 3)}
    block = video.get('blockiness_score')
    if block is not None and block >= BLOCK_EVENT_THRESHOLD:
        ev['highBlockiness'] = {'count': 1, 'totalMs': int(window_seconds * 1000),
                                'perMinute': round(60.0 / max(1, window_seconds), 3)}
    return ev


# --------------------------------------------------------------------------- #
# Position — closest-known navigation node over time (Localize), RLE'd         #
# --------------------------------------------------------------------------- #
# capture_monitor already runs Localize ~1/sec (opt-in per device via
# DEVICE{N}_USERINTERFACE) and writes a `localize` field into each per-frame
# JSON: {node, confidence, excluded, total[, state]}. We just READ those (no
# recompute — keeps this analyzer pure + cheap), classify each sample, and
# run-length-encode runs of the same node into compact epoch-ms spans so the
# timeline can show where the device was. Empty when localize is disabled.
#
# kind per sample (drives the lane colour):
#   confident  (green)  — one node, decent confidence
#   ambiguous  (yellow) — a node, but low confidence / >1 candidate left (the
#                         look-alike-menu case the title-OCR layer would break,
#                         which the per-second loop deliberately skips)
#   no_signal / blackscreen — a named capture-side state (from classify)
#   unknown    (grey)   — nothing recognised (live video / dark / no match)
POS_CONF_GREEN = 0.55   # >= this AND a single candidate left ⇒ confident (green)


def analyze_positions(capture_folder, window_seconds=60):
    """RLE'd screen position over the window, from the per-frame `localize` field.

    Returns {'positions': [{s,e,node,kind,conf}, ...]} (epoch-ms spans, ascending)
    or {'positions': None} when localize is disabled/absent for this device."""
    import json
    mdir = _metadata_dir(capture_folder)
    if not os.path.isdir(mdir):
        return {'positions': None}
    files = glob.glob(os.path.join(mdir, 'capture_*.json'))
    if not files:
        return {'positions': None}
    cutoff = time.time() - window_seconds
    recent = sorted(((f, os.path.getmtime(f)) for f in files
                     if os.path.getmtime(f) >= cutoff), key=lambda x: x[1])

    samples = []   # (epoch_s, node|None, conf, kind)
    for f, mt in recent:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        loc = d.get('localize')
        if not isinstance(loc, dict):
            continue
        node = loc.get('node')
        conf = float(loc.get('confidence') or 0.0)
        total = loc.get('total') or 0
        remaining = (total - (loc.get('excluded') or 0)) if total else 0
        state = loc.get('state')
        if state:                                   # named capture-side state
            kind, node = state, None
        elif not node:
            kind = 'unknown'
        elif conf >= POS_CONF_GREEN and remaining <= 1:
            kind = 'confident'
        else:
            kind = 'ambiguous'                      # low confidence / >1 candidate
        samples.append((mt, node, round(conf, 3), kind))

    if not samples:
        return {'positions': None}

    # Run-length encode consecutive same (node, kind). Each sample represents ~1s;
    # a run's end extends to the NEXT sample (last → +1s) so the lane fills with no
    # fake gaps between adjacent seconds; real gaps (localize off) stay uncovered.
    segs = []
    for i, (t, node, conf, kind) in enumerate(samples):
        end = samples[i + 1][0] if i + 1 < len(samples) else t + 1.0
        last = segs[-1] if segs else None
        if last and last['node'] == node and last['kind'] == kind \
                and (t * 1000 - last['e']) <= 2000:        # contiguous (≤2s gap)
            last['e'] = int(end * 1000)
            last['_n'] += 1
            last['_csum'] += conf
        else:
            segs.append({'s': int(t * 1000), 'e': int(end * 1000), 'node': node,
                         'kind': kind, '_n': 1, '_csum': conf})
    for seg in segs:
        seg['conf'] = round(seg.pop('_csum') / seg.pop('_n'), 3)
    return {'positions': segs}


# --------------------------------------------------------------------------- #
# Public entrypoint                                                            #
# --------------------------------------------------------------------------- #
def analyze_device(capture_folder, window_seconds=60):
    """Full AVQ measurement for one device. Returns a flat dict matching the
    quality_metrics columns (+ 'events', '_frames'). Never raises."""
    t0 = time.perf_counter()
    audio = analyze_audio(capture_folder, window_seconds)
    video = analyze_video(capture_folder, window_seconds)
    text = analyze_text(capture_folder, window_seconds)
    incidents = analyze_incidents(capture_folder, window_seconds)
    positions = analyze_positions(capture_folder, window_seconds)

    # Blackscreen/freeze are "no real video" → override availability and recompute
    # MOS so a frozen/black channel reads MOS 0, not a high score from black frames.
    if incidents.get('clean_fraction') is not None:
        video['video_availability'] = incidents['clean_fraction']
        video['clean_video_seconds'] = round(incidents['clean_fraction'] * window_seconds, 1)
        video['video_mos'] = _video_mos(video)

    # Audio "available" follows the DETECTOR's per-frame audio flag (same source as
    # the overlay + transcript pipeline) — silencedetect/ebur128 alone treat a
    # constant low-level hum (e.g. a sleeping-STB test pattern at ~-50 dB) as audio.
    apf = incidents.get('_audio_present_fraction')
    if apf is not None:
        audio['audio_availability'] = apf
        if apf < 0.2:                       # detector: effectively no audio
            audio['audio_mos'] = 0.0

    events = _build_events(audio, video, window_seconds)
    events.update(incidents.get('_events') or {})   # blackscreen/freeze/macroblocks runs

    result = {
        'window_seconds': window_seconds,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **{k: v for k, v in video.items() if not k.startswith('_')},
        **{k: v for k, v in audio.items() if not k.startswith('_')},
        **text,
        # subtitle OCR aggregated over the full frame set (analyze_incidents)
        'subtitle_availability': incidents.get('_subtitle_availability'),
        'subtitle_language': incidents.get('_subtitle_language'),
        'subtitle_text': incidents.get('_subtitle_text'),
        **{k: v for k, v in incidents.items() if k != 'clean_fraction' and not k.startswith('_')},
        'events': events,
        'positions': positions.get('positions'),   # RLE'd screen position (Localize)
        '_frames': video.get('_frames', 0),
        '_elapsed_ms': round((time.perf_counter() - t0) * 1000, 1),
    }
    return result


if __name__ == '__main__':
    import json
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    folder = sys.argv[1] if len(sys.argv) > 1 else 'capture1'
    window = 60
    if '--window' in sys.argv:
        window = int(sys.argv[sys.argv.index('--window') + 1])
    print(json.dumps(analyze_device(folder, window), indent=2))
