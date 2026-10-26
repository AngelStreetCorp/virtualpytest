"""Caption translation (TASK-103 goal 6): machine-translated copies of a transcript chunk, one LLM call per minute.

The source is the chunk JSON (transcript/<hour>/chunk_10min_<n>.json). The translation of a language lives next to it in
`chunk_10min_<n>_<lang>.json` (the file the delayed player already reads for the viewer's language). That file is the
cache: `translated_minutes[<minute>]` is present once a minute has been translated and the minute is never sent again.
A minute that is not translated (yet, or the call failed) keeps its SOURCE segments, flagged `untranslated: true`, so the
file always covers every processed minute: the player never stalls on a translation and never shows nothing.

Segments keep `start` / `end` of the source, so translated cues have the source timing. `words` are dropped (they are
source-language words); a translated segment is split by the player in proportion to the characters of its words.
"""
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

USAGE = 'text.caption_translation'
TARGET_LANGUAGES = ('en', 'fr', 'de')
LANGUAGE_NAMES = {'en': 'English', 'fr': 'French', 'de': 'German'}
MAX_TOKENS = 2000
MAX_ATTEMPTS = 2           # model calls per try of a minute
MAX_MINUTE_TRIES = 3       # tries of a failing minute over time, then it stays in the source language

_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


_NAME_TO_CODE = {v.lower(): k for k, v in LANGUAGE_NAMES.items()}


def lang_code(language: Optional[str]) -> str:
    """The chunk JSON holds Whisper's language as a name ("German") or a code ("de"): always a lower-case code/name here."""
    lang = (language or '').strip().lower()
    return _NAME_TO_CODE.get(lang, lang)


def _lock_for(path: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(path, threading.Lock())


def translated_path(chunk_path: str, lang: str) -> str:
    base, ext = os.path.splitext(chunk_path)
    return f'{base}_{lang}{ext}'


def target_languages(source: Optional[str], env: Optional[Dict[str, str]] = None) -> List[str]:
    """CAPTION_TRANSLATE_LANGS (default en,fr,de; empty = none) minus the source language."""
    raw = (env if env is not None else os.environ).get('CAPTION_TRANSLATE_LANGS')
    langs = [l.strip().lower() for l in (TARGET_LANGUAGES if raw is None else raw.split(',')) if l.strip()]
    return [l for l in langs if l in LANGUAGE_NAMES and l != lang_code(source)]


def minute_of(segment: Dict[str, Any]) -> int:
    return int(max(float(segment.get('start', 0)), 0) // 60)


def build_prompt(texts: List[str], source: str, target: str) -> str:
    return (
        f'Translate these {len(texts)} television caption lines from {LANGUAGE_NAMES.get(source, source)} to '
        f'{LANGUAGE_NAMES[target]}. Keep each line short and natural for subtitles, keep names, do not merge or split lines. '
        f'Answer with ONLY a JSON array of exactly {len(texts)} strings, in the same order.\n'
        + json.dumps(texts, ensure_ascii=False))


def parse_answer(content: str, expected: int) -> Optional[List[str]]:
    """The JSON array of `expected` strings in the model's answer, else None."""
    m = re.search(r'\[.*\]', content or '', re.S)
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(arr, list) or len(arr) != expected or not all(isinstance(x, str) for x in arr):
        return None
    return [x.strip() for x in arr]


def looks_untranslated(texts: List[str], out: List[str]) -> bool:
    """True when the model handed the source back (seen with a reasoning model: whole minutes returned unchanged)."""
    long_ones = [(a, b) for a, b in zip(texts, out) if len(a) > 12]
    return bool(long_ones) and sum(1 for a, b in long_ones if a.strip().lower() == b.strip().lower()) * 2 >= len(long_ones)


def map_segments(segments: List[Dict[str, Any]], translations: List[str]) -> List[Dict[str, Any]]:
    """Source segments with translated text, same start/end (words dropped)."""
    return [{'start': s['start'], 'end': s['end'], 'text': t, 'source_text': s.get('text', '').strip()}
            for s, t in zip(segments, translations)]


def _complete(prompt: str) -> Dict[str, Any]:
    from shared.src.lib.ai import gateway
    return gateway.complete(USAGE, prompt, max_tokens=MAX_TOKENS, temperature=0.0)


def translate_minute_segments(segments: List[Dict[str, Any]], source: str, target: str,
                              complete: Optional[Callable[[str], Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """One call for the segments of one minute: {'segments', 'tokens_in', 'tokens_out', 'model', 'ms'} or None on failure."""
    texts = [(s.get('text') or '').strip() for s in segments]
    t0 = time.time()
    tokens_in = tokens_out = 0
    res: Dict[str, Any] = {}
    for attempt in range(MAX_ATTEMPTS):   # an unusable answer (not a JSON array, or the source handed back) is asked once more
        res = (complete or _complete)(build_prompt(texts, source, target))
        usage = res.get('usage') or {}
        tokens_in += usage.get('prompt_tokens', 0)
        tokens_out += usage.get('completion_tokens', 0)
        if not res.get('success'):
            logger.warning('caption translate %s->%s failed: %s', source, target, res.get('error'))
            return None
        out = parse_answer(res.get('content', ''), len(texts))
        if out is None:
            logger.warning('caption translate %s->%s: answer is not a JSON array of %d strings', source, target, len(texts))
        elif looks_untranslated(texts, out):
            logger.warning('caption translate %s->%s: the model returned the source text', source, target)
        else:
            return {'segments': map_segments(segments, out), 'tokens_in': tokens_in, 'tokens_out': tokens_out,
                    'model': res.get('model'), 'ms': int((time.time() - t0) * 1000), 'attempts': attempt + 1}
    return None


def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(path: str, data: Dict[str, Any]) -> None:
    with open(path + '.tmp', 'w') as f:
        json.dump(data, f)
    os.replace(path + '.tmp', path)


def translate_chunk(chunk_path: str, lang: str, complete: Optional[Callable[[str], Dict[str, Any]]] = None,
                    deadline_s: Optional[float] = None) -> Dict[str, Any]:
    """Bring `chunk_10min_<n>_<lang>.json` up to date with the source chunk: translate every machine-captioned minute
    that is not cached yet, once. Returns {'translated': [minutes done now], 'failed': [...], 'cached': n, 'skipped': reason|None}.
    `deadline_s` stops starting new minutes after that many seconds (the caller's wait budget)."""
    started = time.time()
    chunk = _read(chunk_path)
    result: Dict[str, Any] = {'translated': [], 'failed': [], 'cached': 0, 'skipped': None}
    if not chunk or not chunk.get('segments'):
        result['skipped'] = 'no source'
        return result
    source = lang_code(chunk.get('language'))
    if not source or source == lang or lang not in LANGUAGE_NAMES:
        result['skipped'] = 'same language' if source == lang else 'unknown language'
        return result
    out_path = translated_path(chunk_path, lang)
    with _lock_for(out_path):
        cache = _read(out_path) or {}
        done: Dict[str, Any] = dict(cache.get('translated_minutes') or {})
        tries: Dict[str, int] = dict(cache.get('failed_tries') or {})
        by_minute: Dict[int, List[Dict[str, Any]]] = {}
        for seg in chunk['segments']:
            by_minute.setdefault(minute_of(seg), []).append(seg)
        translated_segs: Dict[int, List[Dict[str, Any]]] = {}
        for seg in cache.get('segments') or []:
            if not seg.get('untranslated'):
                translated_segs.setdefault(minute_of(seg), []).append(seg)
        def save() -> None:
            """Write the file as it stands: translated minutes, the rest as flagged source text (so a long chunk is
            usable minute by minute, and a failed or slow call never leaves a gap)."""
            segments: List[Dict[str, Any]] = []
            for minute in sorted(by_minute):
                if minute in translated_segs:
                    segments.extend(translated_segs[minute])
                else:   # not translated yet: the source text, flagged, so the file still covers the minute
                    segments.extend({'start': s['start'], 'end': s['end'], 'text': (s.get('text') or '').strip(),
                                     'untranslated': True} for s in by_minute[minute])
            if result['translated'] or result['failed'] or len(segments) != len(cache.get('segments') or []):
                data = {k: v for k, v in chunk.items() if k not in ('segments', 'transcript')}
                data.update(segments=segments, transcript=' '.join(s['text'] for s in segments),
                            source_language=source, translated_to=lang, machine_translated=True,
                            translated_minutes=done, failed_tries=tries, translation_timestamp=datetime.now().isoformat())
                _write(out_path, data)

        save()   # at once: the whole chunk is readable (flagged source text) while the minutes are translated one by one
        for minute in sorted(by_minute):
            if str(minute) in done and minute in translated_segs:
                result['cached'] += 1
                continue
            if tries.get(str(minute), 0) >= MAX_MINUTE_TRIES:
                continue
            if deadline_s is not None and time.time() - started > deadline_s:
                break
            out = translate_minute_segments(by_minute[minute], source, lang, complete)
            if out is None:
                result['failed'].append(minute)
                tries[str(minute)] = tries.get(str(minute), 0) + 1
                continue
            tries.pop(str(minute), None)
            translated_segs[minute] = out['segments']
            done[str(minute)] = {k: out[k] for k in ('tokens_in', 'tokens_out', 'model', 'ms')}
            result['translated'].append(minute)
            save()
        save()
    return result


def translate_chunk_async(chunk_path: str, source: Optional[str], env: Optional[Dict[str, str]] = None,
                          complete: Optional[Callable[[str], Dict[str, Any]]] = None) -> List[threading.Thread]:
    """Background translation of a chunk into every target language (one daemon thread per language)."""
    threads = []
    for lang in target_languages(source, env):
        t = threading.Thread(target=_safe, args=(chunk_path, lang, complete), daemon=True, name=f'caption-translate-{lang}')
        t.start()
        threads.append(t)
    return threads


def _safe(chunk_path: str, lang: str, complete) -> None:
    try:
        from shared.src.lib.ai import caller as ai_caller
        ai_caller.bind(origin='monitoring', job='caption_translate')
        r = translate_chunk(chunk_path, lang, complete)
        if r['translated'] or r['failed']:
            logger.info('caption translate %s -> %s: done %s failed %s', os.path.basename(chunk_path), lang,
                        r['translated'], r['failed'])
    except Exception:   # a translation problem must never touch transcription
        logger.exception('caption translate %s -> %s crashed', chunk_path, lang)
