"""Audio side: timestamped transcript of the film and the audio language."""
import json
import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .judge import cer
from .srt import Cue, normalize


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list = None  # [{'w': str, 'start': float, 'end': float}]


def transcribe_mkv(mkv: str, work_dir: str, model: str = 'base') -> Tuple[List[Segment], Optional[str]]:
    """faster-whisper over the audio track (reuses audio_transcription_utils.get_whisper_model), with word
    timestamps. Cached next to the report so a re-run is instant."""
    cache = os.path.join(work_dir, f'audio_transcript_{model}_words.json')
    if os.path.exists(cache):
        d = json.load(open(cache))
        return [Segment(**s) for s in d['segments']], d['language']
    wav = os.path.join(work_dir, 'audio_16k.wav')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', mkv, '-vn', '-ac', '1', '-ar', '16000', wav], check=True)
    from shared.src.lib.utils.audio_transcription_utils import get_whisper_model
    wm = get_whisper_model(model)
    segs, info = wm.transcribe(wav, beam_size=1, vad_filter=False, word_timestamps=True)
    out = [Segment(s.start, s.end, s.text.strip(), [{'w': w.word.strip(), 'start': w.start, 'end': w.end} for w in (s.words or [])])
           for s in segs]
    json.dump({'language': info.language, 'segments': [s.__dict__ for s in out]}, open(cache, 'w'), indent=1)
    return out, info.language


def audio_start_for(cue: Cue, segs: Sequence[Segment], window: float = 3.0) -> Optional[Segment]:
    """Where the speech of an (English) cue starts: find the cue's first words, in order, among the
    transcript words within `window` s of the SRT start. Returns a Segment whose .start is that word's start."""
    want = normalize(cue.text).split()
    words = [w for s in segs for w in (s.words or []) if cue.start - window <= w['start'] <= cue.start + window + 2]
    toks = [(normalize(w['w']), w) for w in words]
    toks = [(t, w) for t, w in toks if t]
    for n in (min(3, len(want)), min(2, len(want)), 1):
        if n < 1 or len(want) < n:
            continue
        # a one-word cue is too ambiguous to anchor on
        if n == 1 and len(want) > 1:
            continue
        head = want[:n]
        for i in range(len(toks) - n + 1):
            if [t for t, _ in toks[i:i + n]] == head:
                w = toks[i][1]
                return Segment(w['start'], w['end'], ' '.join(t for t, _ in toks[i:i + n]))
    return None


def segment_at(segs: Sequence[Segment], t: float, pad: float = 1.0) -> str:
    return ' '.join(s.text for s in segs if s.start - pad <= t <= s.end + pad)
