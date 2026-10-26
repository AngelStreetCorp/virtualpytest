"""Transcript of a device over a time window, plus WHY it is empty when it is.

vpt-monitor-audio (backend_host/scripts/transcript_accumulator.py) does two jobs: the always-on
audio check (writes ``hot/metadata/audio_status.json`` every <=30 s, including its mode in
``transcription``) and, only when ENABLE_TRANSCRIPTION=true, Whisper transcription of the
archiver's MP3s into ``<capture>/transcript/<hour>/chunk_10min_<index>.json``. A segment's
``start`` is seconds from the chunk start (hour:index*10, local time). Chunk files are a rolling
24 h buffer: a file whose mtime is before its chunk start holds a previous day's text.

``read_transcript_status`` returns the segments in the window and a classification:

  status        reason                    meaning
  ok            transcribed               segments found
  unavailable   service_inactive          vpt-monitor-audio is not running
  unavailable   transcription_disabled    service runs in AUDIO DETECTION ONLY mode
  empty         no_audio_stream           the device captures no audio (VIDEO_AUDIO=null)
  empty         silent_audio              audio was silent (minutes flagged silent, or silent now)
  empty         no_speech                 MP3s transcribed, VAD/Whisper found no speech
  empty         broadcaster_subtitles     caption_playback: broadcaster subtitles on screen, no machine captions
  empty         no_audio_recorded         no MP3 for that (past) window: capture/archiver was not recording
  empty         processing_pending        MP3s too fresh to be transcribed yet (~1-2 min lag)
  error         audio_status_missing      no audio_status.json: device not captured/monitored
  error         audio_check_stale         audio_status.json older than 60 s: capture or service wedged
  error         transcription_mode_unknown audio_status.json has no ``transcription`` field
  error         mp3_missing               audio present now, yet no MP3 for the last minutes
  error         transcript_missing        MP3s older than the lag, yet no transcript record
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from datetime import datetime, timedelta
from typing import Optional

TRANSCRIPT_UNIT = 'vpt-monitor-audio'
AUDIO_STATUS_MAX_AGE_S = 60      # same staleness rule as capture_monitor.py
PROCESSING_LAG_S = 180           # an MP3 younger than this may not be transcribed yet
MAX_WINDOW_MINUTES = 120
MAX_SEGMENTS = 400


def _service_state() -> Optional[str]:
    """``systemctl is-active vpt-monitor-audio`` ('active', 'inactive', 'failed', ...), or None off Linux."""
    if platform.system() != 'Linux':
        return None
    try:
        proc = subprocess.run(['systemctl', 'is-active', TRANSCRIPT_UNIT],
                              capture_output=True, text=True, timeout=5)
        return proc.stdout.strip() or 'unknown'
    except (OSError, subprocess.SubprocessError):
        return None


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def resolve_window(now: datetime, minutes: Optional[int], hour: Optional[int],
                   chunk_index: Optional[int]) -> tuple[datetime, datetime]:
    """(start, end) of the requested window. hour[/chunk_index] = its most recent occurrence."""
    if hour is not None:
        length = 10 if chunk_index is not None else 60
        start = now.replace(hour=int(hour), minute=10 * int(chunk_index or 0), second=0, microsecond=0)
        if start > now:
            start -= timedelta(days=1)
        return start, min(start + timedelta(minutes=length), now)
    span = max(1, min(int(minutes or 10), MAX_WINDOW_MINUTES))
    return now - timedelta(minutes=span), now


def read_transcript_status(device_id: str, capture_folder: str, start: datetime, end: datetime,
                           now: Optional[datetime] = None) -> dict:
    from shared.src.lib.utils.storage_path_utils import (
        get_cold_storage_path, get_metadata_path, get_transcript_chunk_path,
    )
    now = now or datetime.now()
    now_ts = time.time()

    # --- service + mode + audio, as written by vpt-monitor-audio itself ---
    service_state = _service_state()
    service_active = None if service_state is None else service_state == 'active'
    audio_path = os.path.join(get_metadata_path(capture_folder), 'audio_status.json')
    audio_status = _read_json(audio_path)
    audio_mtime = _mtime(audio_path)
    audio_age = None if audio_mtime is None else round(now_ts - audio_mtime, 1)
    transcription_enabled = audio_status.get('transcription') if audio_status else None
    audio = {
        'present': audio_status.get('audio') if audio_status else None,
        'mean_volume_db': audio_status.get('mean_volume_db') if audio_status else None,
        'age_s': audio_age,
    }

    # --- transcript segments + MP3 evidence per 10-min chunk ---
    audio_cold = get_cold_storage_path(capture_folder, 'audio')
    segments, chunks = [], []
    language = None
    mp3_times: list[float] = []
    minute_reasons: list[str] = []
    chunk_start = start.replace(minute=(start.minute // 10) * 10, second=0, microsecond=0)
    while chunk_start < end:
        h, idx = chunk_start.hour, chunk_start.minute // 10
        cs_ts = chunk_start.timestamp()
        path = get_transcript_chunk_path(capture_folder, h, idx)
        mtime = _mtime(path)
        current = mtime is not None and cs_ts <= mtime < cs_ts + 86400
        info = {'hour': h, 'chunk_index': idx, 'start': chunk_start.isoformat(timespec='seconds'),
                'transcript_file': current, 'segments': 0}
        if current:
            data = _read_json(path) or {}
            day = chunk_start.strftime('%Y-%m-%d')
            for minute, st in (data.get('minute_statuses') or {}).items():
                at = chunk_start + timedelta(minutes=int(minute))
                if st.get('processed_day') == day and start - timedelta(minutes=1) < at <= end:
                    minute_reasons.append(st.get('skip_reason') or ('speech' if st.get('has_audio') else 'no_speech'))
            for seg in data.get('segments') or []:
                text = (seg.get('text') or '').strip()
                try:
                    at = chunk_start + timedelta(seconds=float(seg.get('start') or 0))
                except (TypeError, ValueError):
                    continue
                if text and start <= at <= end + timedelta(seconds=5):
                    segments.append({'time': at.isoformat(timespec='seconds'), 'text': text})
                    info['segments'] += 1
            language = data.get('language') or language
        mp3_10 = _mtime(os.path.join(audio_cold, str(h), f'chunk_10min_{idx}.mp3'))
        if mp3_10 is not None and cs_ts <= mp3_10 <= cs_ts + 1800:
            mp3_times.append(mp3_10)
            info['mp3_10min'] = True
        chunks.append(info)
        chunk_start += timedelta(minutes=10)

    temp_dir = os.path.join(audio_cold, 'temp')
    try:
        for name in os.listdir(temp_dir):
            if name.startswith('1min_') and name.endswith('.mp3'):
                m = _mtime(os.path.join(temp_dir, name))
                if m is not None and start.timestamp() <= m <= end.timestamp() + 90:
                    mp3_times.append(m)
    except OSError:
        pass

    segments.sort(key=lambda s: s['time'])
    truncated = len(segments) > MAX_SEGMENTS
    if truncated:
        segments = segments[-MAX_SEGMENTS:]

    status, reason = _classify(
        segments=segments, service_state=service_state, service_active=service_active,
        audio_status=audio_status, audio_age=audio_age, transcription_enabled=transcription_enabled,
        mp3_times=mp3_times, minute_reasons=minute_reasons, start=start, end=end, now=now, now_ts=now_ts,
    )
    window = {'from': start.isoformat(timespec='seconds'), 'to': end.isoformat(timespec='seconds'),
              'minutes': round((end - start).total_seconds() / 60, 1)}
    result = {
        'success': True,
        'status': status,
        'reason': reason,
        'device_id': device_id,
        'capture_folder': capture_folder,
        'service_active': service_active,
        'service_state': service_state,
        'transcription_enabled': transcription_enabled,
        'audio': audio,
        'window': window,
        'language': language,
        'segment_count': len(segments),
        'segments': segments,
        'text': ' '.join(s['text'] for s in segments),
        'truncated': truncated,
        'mp3_count': len(mp3_times),
        'chunks': chunks,
    }
    result['message'] = _message(result)
    return result


def _classify(*, segments, service_state, service_active, audio_status, audio_age,
              transcription_enabled, mp3_times, minute_reasons, start, end, now, now_ts):
    if segments:
        return 'ok', 'transcribed'
    if service_active is False:
        return 'unavailable', 'service_inactive'
    if audio_status is None:
        return 'error', 'audio_status_missing'
    if transcription_enabled is False:
        return 'unavailable', 'transcription_disabled'
    if audio_age is not None and audio_age > AUDIO_STATUS_MAX_AGE_S:
        return 'error', 'audio_check_stale'
    if transcription_enabled is None:
        return 'error', 'transcription_mode_unknown'
    if audio_status.get('audio') is None:
        return 'empty', 'no_audio_stream'
    recent_window = (now - end).total_seconds() < 120
    if any(r.startswith('silent_audio') for r in minute_reasons):
        return 'empty', 'silent_audio'
    # The archiver writes 1-min MP3s even for silence; Whisper then finds nothing.
    if recent_window and audio_status.get('audio') is False:
        return 'empty', 'silent_audio'
    if 'no_speech' in minute_reasons:
        return 'empty', 'no_speech'
    if 'broadcaster_subtitles' in minute_reasons:
        return 'empty', 'broadcaster_subtitles'
    if not mp3_times:
        if audio_status.get('audio') is False:
            return 'empty', 'silent_audio'
        if recent_window and (end - start).total_seconds() < PROCESSING_LAG_S:
            return 'empty', 'processing_pending'
        if recent_window:
            return 'error', 'mp3_missing'
        return 'empty', 'no_audio_recorded'
    if any(now_ts - m < PROCESSING_LAG_S for m in mp3_times):
        return 'empty', 'processing_pending'
    return 'error', 'transcript_missing'


_MESSAGES = {
    'service_inactive': "vpt-monitor-audio is not running on this host (state: {service_state}). "
                        "No audio check and no transcription. Start it: sudo systemctl start vpt-monitor-audio.",
    'transcription_disabled': "Transcription is disabled on this host: vpt-monitor-audio runs in AUDIO DETECTION ONLY "
                              "mode (ENABLE_TRANSCRIPTION unset/false). Only the audio check runs; no transcript "
                              "is produced. Enable with the systemd drop-in vpt-monitor-audio.service.d/transcription.conf "
                              "(Environment=ENABLE_TRANSCRIPTION=true) and restart vpt-monitor-audio.",
    'no_audio_stream': "Transcription is on, but this device captures no audio (no audio stream; VIDEO_AUDIO=null "
                       "in the host .env), so there is nothing to transcribe.",
    'silent_audio': "Transcription is on, but the audio was silent in this window ({volume}), "
                    "so there was nothing to transcribe.",
    'no_speech': "Transcription is on and the audio was processed, but no speech was found in this window "
                 "(music/noise; the voice-activity filter dropped it).",
    'broadcaster_subtitles': "Transcription is on (caption_playback) but the broadcaster's own subtitles are on screen in this "
                             "window, so no machine captions were made for it.",
    'no_audio_recorded': "Transcription is on, but no audio was recorded for this window (no MP3 from the "
                         "archiver; the capture was probably not recording then).",
    'processing_pending': "Transcription is on; the audio for this window is not transcribed yet "
                          "(the transcript lags ~1-2 min). Retry shortly or ask for a longer window.",
    'audio_status_missing': "No audio_status.json for {capture_folder}: vpt-monitor-audio does not monitor this device "
                            "(capture not running or not in active_captures.conf).",
    'audio_check_stale': "audio_status.json is {age}s old (limit 60 s): the capture or vpt-monitor-audio is wedged "
                         "for this device. Check vpt-stream and journalctl -u vpt-monitor-audio.",
    'transcription_mode_unknown': "vpt-monitor-audio did not report its mode (old build): restart vpt-monitor-audio "
                                  "so it writes 'transcription' into audio_status.json.",
    'mp3_missing': "Audio is present now, but no MP3 exists for the last minutes: the archiver is not producing "
                   "audio (check vpt-archiver).",
    'transcript_missing': "MP3s exist for this window and are old enough, but no transcript was written: "
                          "transcription is failing (check journalctl -u vpt-monitor-audio).",
}


def _message(r: dict) -> str:
    w = r['window']
    if r['reason'] == 'transcribed':
        msg = f"{r['segment_count']} transcript segment(s) for {r['device_id']} from {w['from']} to {w['to']}"
        if r['language']:
            msg += f" (language: {r['language']})"
        msg += '.'
        if r['truncated']:
            msg += f' Only the last {MAX_SEGMENTS} segments are returned; ask for a shorter window.'
        if r['service_active'] is False:
            msg += f" Note: vpt-monitor-audio is not running now (state: {r['service_state']})."
        return msg
    vol = r['audio']['mean_volume_db']
    return f"No transcript for {r['device_id']} from {w['from']} to {w['to']}. " + _MESSAGES[r['reason']].format(
        service_state=r['service_state'], capture_folder=r['capture_folder'], age=r['audio']['age_s'],
        volume=f'{vol:.1f} dB now' if isinstance(vol, (int, float)) else 'no reading')
