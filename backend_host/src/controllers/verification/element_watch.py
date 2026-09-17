"""
backend_host/src/controllers/verification/element_watch.py — watching one UI element's label
over time, shared by every controller that can read a UI tree.

**Why this exists.** A motion check asks "is anything on screen moving?", which is a slow and
indirect way to ask "is this playing?". It samples the captured stream for up to a minute, and
it cannot tell a player that is open but has not started drawing from one that is genuinely
stuck — a phone whose app was just relaunched captures a black player rectangle for a while,
and a motion check reads that as failure.

A player states its own position. The SeekBar carries it as a label ("21 minutes 0 seconds of 1
hour 3 minutes 38 seconds"), so watching that label move answers the actual question directly,
in about a second, and says what it saw. It also keeps working in the cases where the captured
pixels cannot be trusted at all — a surface marked FLAG_SECURE is blanked in screen capture by
design, on MediaProjection and `adb screencap` alike.

Nothing here is video-specific: it watches whichever element a search term selects and asks
whether its label moved, which is also how it answers "has this screen settled?".

Labels are compared raw, never parsed. "21 minutes 0 seconds of…" is English on one phone and
something else on the next, and the only question is whether it moved.

**Callers supply a `read_label(search_term)`** returning `(found, label, match, error)` —
usually `first_labelled_match()` below applied to whatever that controller dumps. Both
ADBVerificationController and the mobile-app feature's PhoneAgentAdbVerificationController use
this, so the two answer identically and a navigation tree runs unchanged on either.
"""
import time
from typing import Any, Callable, Dict, Optional, Tuple

# Attributes a search term is matched against, in the order a human would expect to find it.
# 'class_name' is in here on purpose: it is what lets 'SeekBar' select a player's scrubber by
# type, while 'Comments' selects by text.
SEARCHED_ATTRIBUTES = ('text', 'content_desc', 'resource_id', 'class_name')
# How often a watched label is re-read. Finer than the one-second element poll because the
# thing being watched may not stay: YouTube hides its player controls within a few seconds.
WATCH_POLL_S = 0.7
# How long a label must hold still to count as settled.
DEFAULT_STABLE_S = 3.0
# Labels go in the message and the report; enough to identify what was watched, not a wall.
_LABEL_IN_MESSAGE = 60

# (found, label, match, error)
ReadLabel = Callable[[str], Tuple[bool, str, Dict[str, Any], str]]


def short(label: str) -> str:
    """A label as it appears in a message: quoted, and cut if it runs long."""
    text = (label or '').strip()
    if not text:
        return '(no label)'
    return repr(text if len(text) <= _LABEL_IN_MESSAGE else text[:_LABEL_IN_MESSAGE] + '…')


def matched_attribute(element: Dict[str, Any], term: str) -> Optional[str]:
    """The attribute `term` matched on, or None. Case-insensitive substring."""
    needle = (term or '').strip().lower()
    if not needle:
        return None
    for attr in SEARCHED_ATTRIBUTES:
        # A phone reports `class`/`content_desc` while adb_utils reports `class_name`; accept
        # both spellings so a tree written against either vocabulary behaves the same.
        value = element.get(attr) or element.get(attr.replace('class_name', 'class')) or ''
        if needle in str(value).lower():
            return attr
    return None


def first_labelled_match(elements, term: str) -> Tuple[bool, str, Dict[str, Any], str]:
    """The label of the first element matching `term`: (found, label, match, error)."""
    for index, element in enumerate(elements or []):
        attr = matched_attribute(element, term)
        if not attr:
            continue
        label = (element.get('content_desc') or element.get('text') or '').strip()
        match = {
            'element_id': element.get('id', index),
            'match_reason': f"{attr} contains '{term}'",
            'text': element.get('text', ''),
            'content_desc': element.get('content_desc', ''),
            'resource_id': element.get('resource_id', ''),
            'bounds': element.get('bounds'),
        }
        if not label:
            return False, '', match, (f"element matching '{term}' has no label to watch "
                                      f"(matched on {attr})")
        return True, label, match, ''
    return False, '', {}, f"no element matching '{term}'"


def wait_for_change(read_label: ReadLabel, search_term: str, timeout: float,
                    log: str = '[@element_watch]'):
    """Pass as soon as the element's label differs from the first reading.

    Polled rather than sampled twice at a fixed gap, because the element worth watching is
    often the one that does not stay: YouTube hides its player controls after a few seconds,
    taking the SeekBar out of the tree with it, so a second sample three seconds later can find
    nothing at all. Polling answers on the first position tick — comfortably inside that window
    — and the baseline is kept if the element vanishes, so a later reading that comes back
    different still passes.
    """
    started = time.time()
    baseline = None
    last_seen = ''
    last_error = None
    match: Dict[str, Any] = {}

    while True:
        ok, label, found, error = read_label(search_term)
        if ok:
            match = found or match
            last_seen = label
            if baseline is None:
                baseline = label
            elif label != baseline:
                elapsed = time.time() - started
                message = (f"'{search_term}' went from {short(baseline)} to {short(label)} "
                           f"after {elapsed:.1f}s")
                print(f"{log} SUCCESS: {message}")
                return True, message, build_result(search_term, elapsed, baseline, label, match)
        else:
            last_error = error

        if timeout <= 0 or (time.time() - started) >= timeout:
            break
        time.sleep(WATCH_POLL_S)

    elapsed = time.time() - started
    message = f"'{search_term}' did not change within {elapsed:.1f}s"
    if baseline is None:
        # Never read it at all — a different failure from "read it and it stood still", and the
        # one that usually means the selector or the screen is wrong.
        message += f" ({last_error or 'never found'})"
    else:
        message += f" (held at {short(last_seen or baseline)})"
    print(f"{log} FAILED: {message}")
    result = build_result(search_term, elapsed, baseline or '', last_seen, match)
    result['timeout_reached'] = True
    result['last_error'] = last_error
    return False, message, result


def wait_for_stable(read_label: ReadLabel, search_term: str, duration: float, timeout: float,
                    log: str = '[@element_watch]'):
    """Pass once the element's label has held the same value for `duration` seconds."""
    started = time.time()
    baseline = None
    stable_since = 0.0
    last_error = None
    match: Dict[str, Any] = {}

    while True:
        ok, label, found, error = read_label(search_term)
        if ok:
            match = found or match
            if label != baseline:
                baseline, stable_since = label, time.time()
            elif time.time() - stable_since >= duration:
                elapsed = time.time() - started
                message = f"'{search_term}' held at {short(label)} for {duration:.0f}s"
                print(f"{log} SUCCESS: {message}")
                return True, message, build_result(search_term, elapsed, baseline, label, match)
        else:
            # A label that is gone is not a label that settled — say so rather than counting an
            # absent element as stable.
            last_error = error
            baseline, stable_since = None, 0.0

        if timeout <= 0 or (time.time() - started) >= timeout:
            break
        time.sleep(WATCH_POLL_S)

    elapsed = time.time() - started
    message = f"'{search_term}' did not stop changing within {elapsed:.1f}s"
    if last_error:
        message += f" ({last_error})"
    elif baseline is not None:
        message += f" (still moving, last {short(baseline)})"
    print(f"{log} FAILED: {message}")
    result = build_result(search_term, elapsed, baseline or '', baseline or '', match)
    result['timeout_reached'] = True
    result['last_error'] = last_error
    return False, message, result


def build_result(search_term, elapsed, first, last, match) -> Dict[str, Any]:
    return {
        'search_term': search_term,
        'successful_term': search_term,
        'attempted_terms': [search_term],
        'wait_time': elapsed,
        # The two readings are the evidence: a report that says only "failed" cannot tell a
        # player that never started from one this never found.
        'first_label': first,
        'last_label': last,
        'changed': bool(last and last != first),
        'total_matches': 1 if match else 0,
        'matches': [match] if match else [],
        'search_details': {
            'case_sensitive': False,
            'search_method': 'label_watched_over_time',
            'searched_attributes': list(SEARCHED_ATTRIBUTES),
            'fallback_strategy': False,
        },
    }


def declare_verifications(create_param, ParamType, source: str):
    """The two commands as `get_available_verifications` entries.

    Declared here so both controllers offer exactly the same thing. `search_term` is required
    because VerificationExecutor._filter_valid_verifications drops an 'adb' verification
    without one before it ever reaches a controller; defaulting it to SeekBar makes the common
    case (is this player playing?) a one-click pick.
    """
    def _base():
        return {
            'search_term': create_param(
                ParamType.STRING, required=True, default='SeekBar',
                description='Element whose label to watch (class, text or content description)',
                placeholder='SeekBar',
            ),
            'timeout': create_param(
                ParamType.NUMBER, required=False, default=0.0,
                description='Maximum time to wait (seconds)',
            ),
        }

    stable_params = _base()
    stable_params['duration'] = create_param(
        ParamType.NUMBER, required=False, default=DEFAULT_STABLE_S,
        description='Seconds the label must hold still', min=0.1, max=30.0,
    )

    return [
        {
            'command': 'waitForElementToChange',
            'label': 'Wait for Element to Change (playback)',
            'description': (f"Watch one element's label in the {source} and pass when it moves. "
                            "With the default SeekBar this proves a video is playing in about "
                            "a second, where a motion check samples the captured stream for up "
                            "to a minute and cannot tell 'not drawing yet' from 'stuck'."),
            'params': _base(),
            'verification_type': 'adb',
        },
        {
            'command': 'waitForElementToStopChanging',
            'label': 'Wait for Element to Stop Changing',
            'description': (f"Watch one element's label in the {source} and pass when it holds "
                            "steady — playback paused or ended, or a screen that has settled."),
            'params': stable_params,
            'verification_type': 'adb',
        },
    ]
