"""Jev as a SHADOW second opinion on localize ties and borderline text checks (TASK-47 G13), and as the
CONFIRMER of low-confidence localize answers (``confirm_low_confidence``, the one place Jev decides).

The shadow changes nothing. The rule (identify_screen / text_match_score >= threshold) answers
exactly as before; when its answer is shaky, a background thread asks Jev the same question and the
answer is logged to ``ai_decisions`` (``log: true``) for the agreement report (``jev_agreement.py``).

Guarantees (tests/backend_host/test_jev_second_opinion.py):
  * no thread, no work at all when ``decisions.enabled(usage)`` is false;
  * the caller returns at once: the work runs on a small bounded pool, dropped when busy, and a
    per-process rate cap (``MAX_PER_MINUTE``) drops the rest;
  * nothing raises into the caller.

The state builders and question texts are the ones of the offline benchmark
(features/avq/backend_host/localize/jev_second_opinion_bench.py imports them from here).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

LOC_USAGE = 'text.decision.localize'
VER_USAGE = 'text.decision.verification'

BORDER = 0.10          # text check is "borderline" when |score - threshold| <= BORDER
LOW_CONF = 0.80        # a single rule candidate below this confidence is borderline
TOPK = 5               # options offered to Jev: rule candidates, topped up with the nearest stored screens
TIMEOUT_S = 20
MAX_WORKERS = 2        # concurrent shadow calls per process; more are dropped
MAX_PER_MINUTE = 60    # shadow calls per process per minute; more are dropped
CONFIRM_P = 0.9        # Jev must pick the rule's node with at least this probability to keep a low-confidence answer
CONFIRM_TIMEOUT_S = 3  # the confirmation is synchronous (the monitor / localize wait for it)
CONFIRM_TTL_S = 120    # a verdict is reused this long for the same (ui, node, near-identical frame)
CONFIRM_ERR_TTL_S = 15  # a failed call (timeout / error) is remembered briefly so an outage is not a call per frame
CONFIRM_HASH_BITS = 6  # "near-identical frame": full-frame dHash within this many bits
CONFIRM_MAX_PER_MINUTE = 120

LOC_INSTRUCTIONS = ("Which stored screen is the live frame? Answer 'none' when the frame is not any of them. "
                    "A best region distance of about 14 bits or less is the same screen; a tab underline at the "
                    "same x and width identifies the tab; a matching title confirms it; a near tie with a "
                    "different screen is not enough to choose.")

VER_Q = {'type': 'noul', 'instructions': 'Is the expected element really on screen in the checked area?',
         'criteria': {'true': 'the expected image / text is visibly present at the checked area (small shift, colour '
                              'or scale drift and OCR noise are fine)',
                      'false': 'the expected image / text is not there: another element, other text, or nothing'}}
VER_QUESTION = 'q'


# ---- state builders (shared with the benchmark) ------------------------------------------------

def node_facts(h, live: Dict[str, Any], nf: Dict[str, Any], best_d: int) -> str:
    """One fact line about one stored node, from the fingerprint layers."""
    fp = nf['fingerprint']
    d = h._region_dists(live['regions'], fp.get('regions') or {'full': fp['dhash']})
    parts = []
    if d:
        parts.append(f"best region distance {d[0]} of 256 bits" + (f", 2nd region {d[1]}" if len(d) > 1 else ''))
        parts.append(f"{d[0] - best_d} bits behind the closest screen" if d[0] > best_d else 'the closest screen')
    else:
        parts.append('no usable region (black / empty)')
    parts.append(f"full-frame distance {h._dhash_hamming(live['full'], fp['dhash'])} of 256")
    lf, sf = live['focus'], fp.get('focus') or {}
    agree = h._focus_agreement(lf, sf)
    if sf.get('kind') == 'nav' or lf.get('kind') == 'nav':
        parts.append(f"tab underline live x={lf.get('x')} width={lf.get('width')} vs stored x={sf.get('x')} "
                     f"width={sf.get('width')} ({'agree' if agree >= 0.99 else 'differ'})")
    elif sf.get('kind') == 'box' or lf.get('kind') == 'box':
        parts.append(f"focused box live ({lf.get('x')},{lf.get('y')}) vs stored ({sf.get('x')},{sf.get('y')}), "
                     f"focus agreement {agree:.2f}")
    else:
        parts.append(f"no focus element, agreement {agree:.2f}")
    if live['title'] or fp.get('title'):
        parts.append(f"title live '{live['title']}' vs stored '{h._normalize_text(fp.get('title') or '')}' "
                     f"similarity {h.title_score(live['title'], h._normalize_text(fp.get('title') or '')):.2f}")
    if live['crop'] and fp.get('crop'):
        parts.append(f"focused-tile crop distance {h._dhash_hamming(live['crop'], fp['crop'])} of 256")
    return f"{nf['label']}: " + '; '.join(parts)


def live_signature(h, img) -> Dict[str, Any]:
    """The live frame's fingerprint layers (what identify_screen computes), for the fact lines."""
    import cv2
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return {'regions': h._region_dhashes(gray), 'full': h._dhash_hex(gray), 'focus': h._focus_signature(img),
            'crop': h._focus_crop_hex(img), 'title': h._normalize_text(h._title_text(img))}


def loc_band(cands: List[dict]) -> str:
    """tie (>= 2 candidates) / low-confidence (one, below LOW_CONF) / single (confident) / abstain (none)."""
    if len(cands) == 1:
        return 'single' if (cands[0].get('confidence') or 0) >= LOW_CONF else 'low-confidence'
    return 'tie' if cands else 'abstain'


# ---- low-confidence confirmation (decides) -----------------------------------------------------

_confirm_lock = threading.Lock()
_confirm_stamps: deque = deque()
_confirm_cache: Dict[Any, List[tuple]] = {}      # (ui, node_id) -> [(dhash, expires_at, p_or_None, why)]


def _unknown(result: dict, why: str) -> dict:
    """Turn the rule's single low-confidence candidate into "unknown" (no candidate)."""
    result['unconfirmed_candidate'] = (result.get('candidates') or [None])[0]
    result['candidates'] = []
    result['excluded_count'] = result.get('excluded_count', 0) + 1
    result['reason'] = why
    return result


def _hamming_hex(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count('1')
    except Exception:  # noqa: BLE001
        return 999


def _verdict(result: dict, p: Optional[float], why: str) -> dict:
    if p is not None and p >= CONFIRM_P:
        result['jev_confirmed'] = p
        return result
    return _unknown(result, why)


NOT_CONFIRMED = 'low-confidence answer not confirmed by Jev'
JEV_OFF = 'low-confidence answer not confirmed by Jev (Jev off)'


def confirm_low_confidence(helpers, img, node_fps: List[dict], result: dict, *, team_id: Optional[str],
                           cache_key: Optional[str] = None) -> dict:
    """Keep a LOW-CONFIDENCE single localize answer only when Jev confirms it; else "unknown".

    Applies only to band 'low-confidence' (exactly one candidate, confidence < LOW_CONF) and never to a
    capture state. Jev is asked the same closed choice as the shadow (the rule's node topped up to TOPK
    nearest + 'none'); the answer is kept when it picks THE SAME node with probability >= CONFIRM_P.
    Safe default: another node, 'none', a low probability, a timeout, an error, Jev off, no team or the
    rate cap all give "unknown" (candidates = []). ``cache_key`` is the userinterface name; verdicts are
    cached per (ui, node, near-identical frame) for CONFIRM_TTL_S. Synchronous; never raises.
    Both NavigationExecutor.localize and the monitor call this, so they give the same verdict."""
    try:
        if result.get('state') or loc_band(list(result.get('candidates') or [])) != 'low-confidence':
            return result
        cand = result['candidates'][0]
        node_id = cand.get('node_id')
        from shared.src.lib.ai import decisions
        if not team_id or not node_fps or not decisions.enabled(LOC_USAGE):
            return _unknown(result, JEV_OFF if team_id else NOT_CONFIRMED)
        import cv2
        full = helpers._dhash_hex(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        key = (cache_key, node_id)
        now = time.time()
        with _confirm_lock:
            entries = [e for e in _confirm_cache.get(key, []) if e[1] > now]
            _confirm_cache[key] = entries
            for h, _exp, p, why in entries:
                if _hamming_hex(h, full) <= CONFIRM_HASH_BITS:
                    return _verdict(result, p, why)
            while _confirm_stamps and now - _confirm_stamps[0] > 60:
                _confirm_stamps.popleft()
            if len(_confirm_stamps) >= CONFIRM_MAX_PER_MINUTE:
                return _unknown(result, NOT_CONFIRMED)         # over the cap: unknown, not a call (not cached)
            _confirm_stamps.append(now)

        from shared.src.lib.ai import router
        slim = [{'node_id': cand.get('node_id'), 'label': cand.get('label'), 'confidence': cand.get('confidence'),
                 'dist': cand.get('dist')}]
        live = live_signature(helpers, img)
        state, options = loc_question(helpers, live, node_fps, slim)
        refs = {'source': 'localize-confirm', 'ui': cache_key, 'rule_result': cand.get('label'),
                'candidates': slim}
        out = decisions.choose(router.resolve(LOC_USAGE, team_id), state, options, instructions=LOC_INSTRUCTIONS,
                               timeout_s=CONFIRM_TIMEOUT_S, refs=refs, log=True)
        p, ttl = None, CONFIRM_ERR_TTL_S
        if out.get('success') and out.get('choice') is not None:
            ttl = CONFIRM_TTL_S
            if out['choice'] == node_id:
                probs = out.get('probabilities') or {}
                p = probs.get(node_id, out.get('confidence'))
                p = float(p) if p is not None else None
        if out.get('decision_id'):
            try:                               # add the verdict to the logged decision
                decisions.set_refs(out['decision_id'], team_id, {**refs, 'kept': bool(p is not None and p >= CONFIRM_P)})
            except Exception as e:  # noqa: BLE001
                print(f"[jev-confirm] refs not updated: {e}")
        with _confirm_lock:
            _confirm_cache.setdefault(key, []).append((full, time.time() + ttl, p, NOT_CONFIRMED))
        return _verdict(result, p, NOT_CONFIRMED)
    except Exception as e:  # noqa: BLE001
        print(f"[jev-confirm] failed, answer dropped: {e}")
        if loc_band(list(result.get('candidates') or [])) == 'low-confidence':
            return _unknown(result, NOT_CONFIRMED)
        return result


def loc_question(h, live: Dict[str, Any], cands_nodes: List[dict], cands: List[dict]):
    """(state, options) for one localize decision: the rule's candidates, topped up to TOPK with the
    nearest stored screens, plus 'none'."""
    def best(n):
        d = h._region_dists(live['regions'], n['fingerprint'].get('regions') or {'full': n['fingerprint']['dhash']})
        return d[0] if d else 999
    order = sorted(cands_nodes, key=best)
    ids = [c['node_id'] for c in cands][:TOPK]
    for n in order:
        if len(ids) >= TOPK:
            break
        if n['node_id'] not in ids:
            ids.append(n['node_id'])
    by = {n['node_id']: n for n in cands_nodes}
    best_d = best(order[0]) if order else 999
    options = [{'id': i, 'facts': node_facts(h, live, by[i], best_d)} for i in ids if i in by]
    options.append({'id': 'none', 'facts': 'the frame is not any of the stored screens (unknown screen, video, '
                                           'transition)'})
    state = {'userinterface_kind': 'app screen identification', 'live_focus_kind': live['focus'].get('kind'),
             'live_title_text': live['title'], 'rule_candidates': len(cands),
             'rule_note': 'the fingerprint rule ' + ('found no screen' if not cands else
                          f"left {len(cands)} screen(s): " + ', '.join(str(c.get('label')) for c in cands[:5]))}
    return state, options


def text_state(expected: str, score: float, threshold: float, ocr_text: str, area: Optional[dict]) -> Dict[str, Any]:
    """The compact state of one text check: score vs threshold, the OCR text, the checked area."""
    area = area or {}
    return {'check_type': 'text (OCR) check', 'expected': expected,
            'score': round(float(score), 3), 'threshold': round(float(threshold), 3),
            'score_minus_threshold': round(float(score) - float(threshold), 3),
            'ocr_text': (ocr_text or '')[:200] or '(nothing read)',
            'area': 'whole frame' if not area else
                    f"x={area.get('x')} y={area.get('y')} {area.get('width')}x{area.get('height')}"}


def noul_p(res: dict) -> Optional[float]:
    """Jev's probability that the expected element is there, from a decide() result."""
    a = (res.get('answers') or {}).get(VER_QUESTION) or {}
    return a.get('noul') if res.get('success') else None


# ---- background runner -------------------------------------------------------------------------

_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='jev-shadow')
_slots = threading.BoundedSemaphore(MAX_WORKERS)
_stamps: deque = deque()
_lock = threading.Lock()


def _admit() -> bool:
    """Take a rate token and a worker slot, or refuse (drop). Never blocks."""
    now = time.time()
    with _lock:
        while _stamps and now - _stamps[0] > 60:
            _stamps.popleft()
        if len(_stamps) >= MAX_PER_MINUTE:
            return False
        if not _slots.acquire(blocking=False):
            return False
        _stamps.append(now)
    return True


def _submit(job: Callable[[], None]) -> bool:
    """Run ``job`` in the background when there is room; returns whether it was started."""
    if not _admit():
        return False

    def run():
        try:
            job()
        except Exception as e:  # noqa: BLE001 - a shadow never raises
            print(f"[jev-shadow] skipped: {e}")
        finally:
            _slots.release()
    try:
        _pool.submit(run)
    except Exception:  # noqa: BLE001
        _slots.release()
        return False
    return True


# ---- localize shadow ---------------------------------------------------------------------------

def localize_shadow(helpers, img, node_fps: List[dict], result: dict, *, team_id: Optional[str],
                    userinterface_name: Optional[str], tree_id: Optional[str]) -> bool:
    """After identify_screen: ask Jev in the background when the rule was not a confident single.
    Returns whether a call was started. Never raises, never waits."""
    try:
        from shared.src.lib.ai import decisions
        if not team_id or not decisions.enabled(LOC_USAGE) or result.get('state'):
            return False                      # (state = no usable signal: black / empty capture; nothing to ask)
        cands = list(result.get('candidates') or [])
        band = loc_band(cands)
        if band in ('single', 'low-confidence') or not node_fps or result.get('unconfirmed_candidate'):
            return False                      # (low-confidence is decided by confirm_low_confidence, which logs it)
        frame = img.copy()
        slim = [{'node_id': c.get('node_id'), 'label': c.get('label'), 'confidence': c.get('confidence'),
                 'dist': c.get('dist')} for c in cands]

        def job():
            from shared.src.lib.ai import router
            live = live_signature(helpers, frame)
            state, options = loc_question(helpers, live, node_fps, slim)
            refs = {'source': 'localize-shadow', 'ui': userinterface_name, 'tree_id': tree_id, 'band': band,
                    'rule_result': slim[0]['label'] if slim else 'abstain', 'candidates': slim[:6]}
            decisions.choose(router.resolve(LOC_USAGE, team_id), state, options, instructions=LOC_INSTRUCTIONS,
                             timeout_s=TIMEOUT_S, refs=refs, log=True)
        return _submit(job)
    except Exception as e:  # noqa: BLE001
        print(f"[jev-shadow] localize skipped: {e}")
        return False


# ---- text verification shadow ------------------------------------------------------------------

def text_shadow(*, team_id: Optional[str], expected: str, score: Optional[float], threshold: float,
                ocr_text: str, area: Optional[dict], rule_verdict: bool, userinterface_name: Optional[str] = None,
                reference_name: Optional[str] = None) -> bool:
    """After a text check: ask Jev in the background when the best score is within BORDER of the
    threshold. Returns whether a call was started. Never raises, never waits."""
    try:
        from shared.src.lib.ai import decisions
        if not team_id or score is None or not decisions.enabled(VER_USAGE):
            return False
        if abs(float(score) - float(threshold)) > BORDER:
            return False
        state = text_state(expected, score, threshold, ocr_text, area)
        refs = {'source': 'verification-shadow', 'verification_type': 'text', 'ui': userinterface_name,
                'reference_name': reference_name, 'rule_verdict': 'pass' if rule_verdict else 'fail',
                'score': state['score'], 'threshold': state['threshold']}

        def job():
            from shared.src.lib.ai import router
            decisions.decide(router.resolve(VER_USAGE, team_id), state, {VER_QUESTION: VER_Q},
                             timeout_s=TIMEOUT_S, refs=refs, log=True)
        return _submit(job)
    except Exception as e:  # noqa: BLE001
        print(f"[jev-shadow] text skipped: {e}")
        return False
