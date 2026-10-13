"""LLM spelling/grammar pass over live transcript segments.

Whisper tiny on a Pi mishears and misspells; this pass fixes orthography only.
The raw segment is written first (the rail shows it at once), then a background
thread asks the ``text.transcript_correction`` usage to correct the chunk's
uncorrected segments and rewrites their ``text`` in place, keeping the original in
``raw_text``. The segment ``start`` (its displayed time) never changes.

Opt-in per host with TRANSCRIPT_AUTOCORRECT=true in the host .env (needs transcription
on). The model is chosen in Settings > AI routing, usage "Transcript correction".
"""

import difflib
import json
import logging
import os
import queue
import re
import threading
from typing import List, Optional

from shared.src.lib.utils.ai_utils import call_text_ai
from shared.src.lib.utils.file_lock_utils import lock_file, unlock_file
from shared.src.lib.utils.storage_path_utils import get_transcript_path

logger = logging.getLogger(__name__)

USAGE = 'text.transcript_correction'
# A corrected line must stay this close to the raw one (character similarity),
# otherwise the model rewrote the sentence and the raw line is kept.
MIN_SIMILARITY = 0.6
# Local models on CPU emit ~5 tokens/s, so a call handles only the newest lines;
# older still-pending lines are marked done raw (they were shown long ago).
MAX_LINES_PER_CALL = 15

PROMPT = """You fix speech-to-text output in {language}. The lines were transcribed automatically and contain spelling, grammar and orthography mistakes.

Rules:
- Fix ONLY spelling, grammar, accents, punctuation and obviously misheard words (a word that sounds the same or almost the same).
- Keep the speaker's words and word order as close to the original as possible.
- NEVER change the meaning, add information, summarise, translate or merge/split lines.
- If a line is already correct or you are unsure, leave it out.

Lines:
{lines}

Respond with ONLY this JSON (no markdown), listing ONLY the lines you changed, by number:
{{"fixes": [{{"n": 2, "text": "corrected line 2"}}]}}
If nothing needs fixing: {{"fixes": []}}"""


def correct_lines(texts: List[str], language: Optional[str]) -> Optional[List[str]]:
    """Corrected lines (same length as ``texts``), or None when the call failed."""
    numbered = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(texts))
    prompt = PROMPT.format(language=language or 'the spoken language', lines=numbered)
    result = call_text_ai(prompt, USAGE, max_tokens=max(300, len(numbered)), temperature=0.0)
    if not result.get('success'):
        logger.warning(f"[TRANSCRIPT-CORRECTION] AI call failed: {result.get('error')}")
        return None

    content = result.get('content', '').strip().replace('```json', '').replace('```', '').strip()
    try:
        fixes = json.loads(re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', content)).get('fixes')
        fixes = {int(f['n']): str(f['text']).strip() for f in fixes}
    except (json.JSONDecodeError, AttributeError, KeyError, TypeError, ValueError) as e:
        logger.warning(f"[TRANSCRIPT-CORRECTION] Unparseable answer ({e}): {content[:200]}")
        return None

    corrected = list(texts)
    for n, new in fixes.items():
        if not 1 <= n <= len(texts) or not new:
            continue
        # Guard the "never change the sense" rule: a rewrite drifts far from the raw text.
        if difflib.SequenceMatcher(None, texts[n - 1].lower(), new.lower()).ratio() >= MIN_SIMILARITY:
            corrected[n - 1] = new
    return corrected


def _chunk_path(device_folder: str, hour: int, chunk_index: int) -> str:
    return os.path.join(get_transcript_path(device_folder), str(hour), f'chunk_10min_{chunk_index}.json')


def _read_chunk(chunk_path: str) -> Optional[dict]:
    with open(chunk_path + '.lock', 'w') as lock_fh:
        lock_file(lock_fh, exclusive=True)
        try:
            if not os.path.exists(chunk_path):
                return None
            with open(chunk_path, 'r') as f:
                return json.load(f)
        finally:
            unlock_file(lock_fh)


def correct_chunk(device_folder: str, hour: int, chunk_index: int) -> None:
    """Correct every not-yet-corrected segment of one chunk, in place."""
    chunk_path = _chunk_path(device_folder, hour, chunk_index)
    chunk = _read_chunk(chunk_path)
    if not chunk:
        return
    pending = [s for s in chunk.get('segments', []) if not s.get('corrected') and s.get('text', '').strip()]
    if not pending:
        return
    skipped = {s.get('start') for s in pending[:-MAX_LINES_PER_CALL]}
    pending = pending[-MAX_LINES_PER_CALL:]

    raw_by_start = {s.get('start'): s['text'] for s in pending}
    corrected = correct_lines(list(raw_by_start.values()), chunk.get('language'))
    if corrected is None:
        return
    fixed_by_start = dict(zip(raw_by_start.keys(), corrected))

    # The LLM call ran unlocked; re-read under the lock and only touch segments
    # that are still the raw text we sent (the chunk may have rolled over meanwhile).
    changed = 0
    with open(chunk_path + '.lock', 'w') as lock_fh:
        lock_file(lock_fh, exclusive=True)
        try:
            if not os.path.exists(chunk_path):
                return
            with open(chunk_path, 'r') as f:
                chunk = json.load(f)
            for seg in chunk.get('segments', []):
                start = seg.get('start')
                if start in skipped:
                    seg['corrected'] = True
                    continue
                if seg.get('corrected') or start not in fixed_by_start or seg.get('text') != raw_by_start[start]:
                    continue
                seg['corrected'] = True
                if fixed_by_start[start] != seg['text']:
                    seg['raw_text'] = seg['text']
                    seg['text'] = fixed_by_start[start]
                    changed += 1
            chunk['transcript'] = ' '.join(s.get('text', '').strip() for s in chunk.get('segments', []))
            with open(chunk_path + '.tmp', 'w') as f:
                json.dump(chunk, f, indent=2)
            os.replace(chunk_path + '.tmp', chunk_path)
        finally:
            unlock_file(lock_fh)

    logger.info(f"[{device_folder}] ✏️  Corrected {hour}h/chunk_{chunk_index}: {changed}/{len(pending)} lines changed"
                + (f", {len(skipped)} older lines left raw" if skipped else ''))


class TranscriptCorrector:
    """One background thread; a chunk is queued at most once at a time."""

    def __init__(self, workers: int = 1):
        self._queue: queue.Queue = queue.Queue(maxsize=100)
        self._pending: set = set()
        self._lock = threading.Lock()
        for i in range(max(1, workers)):
            threading.Thread(target=self._run, name=f'transcript-correction-{i}', daemon=True).start()
        logger.info(f"✏️  Transcript LLM correction enabled ({workers} worker(s), usage={USAGE})")

    def submit(self, device_folder: str, hour: int, chunk_index: int) -> None:
        key = (device_folder, hour, chunk_index)
        with self._lock:
            if key in self._pending:
                return
            self._pending.add(key)
        try:
            self._queue.put_nowait(key)
        except queue.Full:
            with self._lock:
                self._pending.discard(key)
            logger.warning(f"[{device_folder}] Correction queue full, skipping {hour}h/chunk_{chunk_index}")

    def _run(self) -> None:
        while True:
            key = self._queue.get()
            # Release before working: segments merged during the call re-queue the chunk.
            with self._lock:
                self._pending.discard(key)
            try:
                correct_chunk(*key)
            except Exception as e:
                logger.error(f"[{key[0]}] Transcript correction error: {e}")
            finally:
                self._queue.task_done()
