#!/usr/bin/env python3
"""screen_label_worker.py — name the recurring screens that are still unknown (TASK-162).

The scheduled arm of the owner's SCREEN-label process: *"every screen that was seen more than 10
times and is NOT live must be labelled and have a fingerprint"*.

WHAT IT DOES, IN ORDER, FOR ONE ROW
    0. Is it a screen at all?     closed question: moving video, or a settled screen?
                                   LIVE -> left unnamed, marked ``label_state='live'``, never given a name.
    1. Is it a known kind?         the TASK-159 G5 closed states, in order (Splash screen, Full-screen
                                   poster). The first one that answers names the row AND links it to
                                   that state's node. A poster is one kind of screen whatever artwork it
                                   shows; open-set naming would call every artwork its own title and never
                                   converge (the failure TASK-159 §3.5 measured).
    2. Link or propose.           The row's own hashes are matched against every fingerprinted
                                   navigation node (screen_memory.match_screen). A hit inside tolerance is a
                                   LINK: the node's v6 fingerprint is stored on the row. No hit is a
                                   PROPOSE: a pending entry in userinterface_unknown_screens, the
                                   operator's existing "Needs a name" queue. This worker never writes
                                   navigation_nodes and never writes a fingerprint onto a tree.
    3. Name it, once.              name_screen_row(), the single writer, which only updates a row whose
                                   label is NULL or unknown_N (TASK-159 G4). The worker never issues a
                                   DELETE and never writes ``label`` directly.

CLOSED QUESTION FIRST, ALWAYS
    Nothing is named open-set until the two closed questions have been asked and both answered "no".
    A closed question is a yes/no the model can only answer from the picture, so a wrong answer is
    visible; an open-set slug is always fluent, which is exactly why it cannot be trusted first.

LOW CONFIDENCE IS NOT A GUESS
    The open-set step asks for a slug AND a confidence word. Only HIGH writes a name. MED and LOW
    leave the row ``unknown_N``, mark it ``label_state='review'``, and put it in the human review list.
    The same goes for a row whose state check errors or goes unparsed: it is counted, not named.

NO PAID MODEL
    ``DEFAULT_PROFILE`` is MiniMax M3.1-Flash (preset ``minimax``, a flat plan, so every call costs 0 per
    docs/agent/ai/AI_USAGE.md). It is resolved with ``router.resolve_profile``, which pins ONE hop with no
    fallback: if MiniMax is down the run fails loudly instead of silently spending on a paid endpoint.
    (Worth knowing: the existing auto_classify_unknowns.py default ``qwen3-vl-8b`` sits on openrouter,
    which is paid.)

    WHEN THE PLAN IS USED UP
    The MiniMax coding plan answers HTTP 429 ``Token Plan usage limit reached (2056)`` on every model it
    serves once the allowance is spent, and the plan is shared by every endpoint on the same key. The
    worker then reads every row as "unreadable" and leaves it for a human -- the safe direction -- but it
    names nothing until the allowance is back. The AI call log says so, because the provider's own error
    is surfaced (see the no_credit fix in shared/src/lib/ai/provider_client.py).

VERIFICATION (--verify)
    A second, independent pass with a DIFFERENT prompt — not "name this screen" but "someone called
    this screen X; is that the same screen?" — re-checks a sample of the rows this process named, and
    reports the agreement rate. Disagreements are LISTED, never applied: the label stays as written,
    the row is marked ``label_state='disagree'`` with the model's words in ``label_note``. A name is
    never replaced (TASK-159 G4), so the only honest thing to do with a disagreement is show it.

TWO DIFFERENT NUMBERS, ON PURPOSE
    This worker names screens seen more than ``MIN_SEEN`` = 3 times. The owner's metric — *"screens >10 seen,
    not live, still unlabelled"* — is measured by ``scripts/screen_label_coverage.py`` and stays at >10. They
    answer different questions: the metric asks whether the screens we see constantly are all named, and it is
    the number that must reach 0; this floor asks whether a screen can be named at all. A splash boots once a
    day, may never reach 10 sightings, and is exactly the kind of screen that should not sit at ``unknown_N``
    for ever. The floor is 3 because that is ``prune_unnamed_screen_noise``'s own ``p_min_hits`` (migration
    20261022f): the platform deletes a row seen fewer than 3 times, so the worker only names rows the registry
    already considers worth keeping.

    Lowering this floor does NOT move the metric, and it does not loosen the two rules that matter: a name is
    still written once and never replaced (name_screen_row), and the worker still issues no DELETE of any kind.

WRITES ARE OFF BY DEFAULT
    Without ``--apply`` this script reads and prints its plan and writes nothing at all. The systemd
    unit passes ``--apply``; that switch is the only thing that turns this from a report into a job.

Run on the vpt-server host:
    sudo -u vpt_user /opt/virtualpytest/venv/bin/python3 \
        /opt/virtualpytest/backend_server/scripts/screen_label_worker.py --dry-run
    sudo -u vpt_user /opt/virtualpytest/venv/bin/python3 \
        /opt/virtualpytest/backend_server/scripts/screen_label_worker.py --apply --limit 20
    sudo -u vpt_user /opt/virtualpytest/venv/bin/python3 \
        /opt/virtualpytest/backend_server/scripts/screen_label_worker.py --verify --limit 20
"""
import argparse
import base64
import os
import re
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

_REPO = os.environ.get('VIRTUALPYTEST_REPO') or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from dotenv import load_dotenv  # noqa: E402

# ---- knobs (all overrideable by --flag) ----
# The WORKER's floor, deliberately LOWER than the owner's metric (which stays at >10 in
# screen_label_coverage.py). These are two different questions:
#   the metric  "is every screen we see often enough named?" — the owner's goal, >10, not moved.
#   the worker  "can this screen be named at all?"          — anything the registry still keeps.
# A splash is transient by nature: it may boot once a day and never reach 10 sightings, yet it is
# exactly the screen the owner means by "all recurring screens should be recognised". Refusing to name
# it would leave it unknown_N for ever for the sake of a number that is about a different question.
#
# WHY 3 AND NOT 2 OR 5
#   prune_unnamed_screen_noise (migration 20261022f) has p_min_hits DEFAULT 3: the platform's own
#   retention policy deletes a row seen fewer than 3 times and older than 14 days. So at 3 the worker
#   only ever names rows the system already considers worth keeping — the threshold is read off the
#   retention rule instead of being invented. One occurrence is a glitch and is left alone; a screen at
#   3 sightings has been seen across three separate transitions, which is recurrence.
#   The label itself stays gated exactly as before: never-rename (name_screen_row) and never-delete (the
#   worker issues no DELETE, and the prune functions skip a row whose label is not unknown_N).
MIN_SEEN = 3               # the worker's own floor; the owner's >10 metric is NOT this constant
MAX_ATTEMPTS = 6           # this worker's own budget per row (its own column, not classification_attempts)
DEFAULT_LIMIT = 20         # rows per run: the AI bill stays bounded and a human can read the log
VERIFY_SAMPLE = 10         # rows re-checked by --verify per run
LIVENESS_VOTES = 3        # unanimity required on 'moving or still' (see ask_live: the model is not deterministic)
# The token FLOOR for every AI call. MEASURED 2026-10-23 on MiniMax M3.1-Flash: this is a thinking model
# and the reasoning comes out of the same max_tokens budget, so a budget that is too small leaves no room
# for the answer at all. At the old floor of 24 every call came back EMPTY (stop_reason=max_tokens) and
# the worker named nothing. Same frame, same prompt: 24 -> empty; 64 -> 'PHOTO' 4 of 5 and 'PH' on the
# 5th (cut mid-word); 128 -> 'PHOTO' 5 of 5; 256 -> 'PHOTO' 5 of 5. So 64 truncates and 128 is complete.
MIN_ANSWER_TOKENS = 128
# The open-set naming gets more room: it has to write a slug AND a confidence word on one line.
OPEN_ANSWER_TOKENS = 256
BATCH = 200                # PostgREST row cap per select

USAGE_KEY = 'vision.screen_label'
# THE FREE MODEL (owner, 2026-10-23: "we have free minimax m3.1-flash unlimited so use that").
# `minimax-m3-1-flash` = model MiniMax-M3.1-Flash-Preview on the `minimax` endpoint: preset `minimax`
# (flat plan -> cost 0), capabilities ['vision'], and the profile the platform already uses for
# vision.game_coc_flash and agent.forge. It talks the Anthropic-compatible API.
# NOT `minimax-vlm-minimax-vlm` (the separate coding_plan/vlm endpoint): that endpoint has its own
# smaller token allowance and ran out on 2026-10-23, which is what stopped this worker cold
# (TASK-162 s6b). Both endpoints use the SAME key and therefore the SAME plan, so the bigger one is
# the one worth depending on.
# resolve_profile pins one hop and never falls back, so a MiniMax outage fails the run instead of
# quietly billing a paid fallback (the exact lesson of BUG-0831).
DEFAULT_PROFILE = 'minimax-m3-1-flash'
# The SECOND free profile, tried only when the first is refused by the provider.
# Both are the same flat plan on the same provider, but they are SEPARATE endpoints with SEPARATE token
# allowances, which the AI call log shows plainly: on 2026-10-23 the `minimax` endpoint (M3.1-Flash) had
# 523 calls and 0 successes -- 287 rate-limited with "Token Plan usage limit reached" and 236 broken by
# an SDK signature change -- while the `minimax-vlm` endpoint answered 27 of its 35 calls the same
# morning. Two quotas, one provider, both free.
#
# This is NOT a paid fallback (the lesson of BUG-0831): every hop here is a flat-plan endpoint, so a
# refusal costs nothing but a lost call. The chain stops at the first profile that answers, and the
# profile that answered is recorded on the row, so the log says which one did the work.
FALLBACK_PROFILES = ('minimax-vlm-minimax-vlm',)
# TASK-159 G5's closed states: [(node label, stored label, question, answer)], asked in order on the image.
# Imported rather than copied so there is one definition of "the states a screen can be".
STATE_HINTS = None         # set in main(); kept module-level so tests can see the real list
state_hints_for = None     # set in main(): row -> the STATE_HINTS that apply to its device

# CLOSED QUESTION 0a. The state hints below assume the picture is a device UI: "no menu" is only evidence of
# a poster when there could have been a menu. On a frame that is not a screen at all the question is vacuous —
# a phone camera pointed at a wall answers NOMENU and would be named "Full-screen poster" with full
# confidence. Measured 2026-10-23: two vpt-pi4/device1 freeze rows are exactly that, and the namer got both
# wrong until this gate existed (the verifier caught it).
#
# THE QUESTION ASKS ABOUT THE MEDIUM, NOT THE CONTENT — measured 2026-10-23, 3 votes each:
#   the first wording said "a photo of the real world (a room, a wall, a person, an object...)", which asks
#   what the picture DEPICTS. A full-screen poster of a film depicts a person in a forest, so that wording
#   answered PHOTO for the poster, for a TV broadcast AND for the wall photo: 3/3 PHOTO on all three. The
#   gate would have refused every real screen and named nothing at all.
#   The wording below asks where the PIXELS come from, and says explicitly that a picture that shows a
#   person or a landscape is still SCREEN when the pixels come from a display:
#     wall photo (must be PHOTO)         old: PHOTO 3/3   new: PHOTO 3/3
#     Minecraft poster (must be SCREEN)  old: PHOTO 3/3   new: SCREEN 3/3
#     TV broadcast (must be SCREEN)      old: PHOTO 3/3   new: SCREEN 3/3
# A TV broadcast is a screen, not a photograph of a room; the LIVENESS gate is what catches that one.
UI_QUESTION = ('Look at the picture itself, not at what it shows. Are these the PIXELS of a display you are '
               'looking straight at (a TV, monitor, phone or tablet screen filling the whole frame)? '
               'Or is this a photograph taken with a camera of whatever was in front of the camera '
               '(a room, a wall, a floor, furniture, a blurry close-up)? '
               'If the picture SHOWS a person, a landscape or an object but the pixels come from a display, '
               'answer SCREEN. Answer SCREEN or PHOTO.')
# CLOSED QUESTION 0b. Everything else depends on the answer, so this one comes before all of them.
LIVE_QUESTION = ('Is this a moving picture (a TV channel playing, a video or a stream, with anything changing '
                 'between frames) or a still screen (a menu, a splash, a poster, a dialog)? '
                 'Answer MOVING or STILL.')
# OPEN-SET, asked only when every closed question answered no. The confidence word is part of the answer:
# a fluent slug with no confidence is not evidence.
OPEN_QUESTION = ('This is a still device screen. Name what kind of screen it is as a short lowercase slug of '
                 '2-5 words, for example "settings_profiles" or "apps_grid". Name the KIND of screen, not the '
                 'content in it. Then state how sure you are. Answer on one line as: SLUG | HIGH, MED or LOW')
# VERIFICATION: a different question, not a re-run of the naming prompt.
VERIFY_QUESTION = ('Someone labelled this screen "{label}". Looking at the picture, is that label correct for it? '
                   'Answer YES or NO.')

UNNAMED_RE = '^unknown_[0-9]+$'
_SLUG_RE = re.compile(r'[^a-z0-9]+')
_NAME_RPC = 'name_screen_row'
_SELECT = ('id, scope, label, dhash, region_center, fingerprint, userinterface, incident_type, verdict, source, '
           'seen_count, sample_image_path, classification_attempts, label_attempts, label_state, label_note, '
           'last_seen')


def slug(text: str, words: int = 6) -> str:
    """'Full Screen  Poster!' -> 'full_screen_poster'.

    The limit applies to the WORDS, not to the joined string: slicing the string would cut
    'full_screen_poster' down to 'full_s' and every long name would lose its tail.
    """
    parts = [w for w in _SLUG_RE.split((text or '').lower()) if w]
    return '_'.join(parts[:words])


def _team_id_arg() -> str:
    from shared.src.lib.config.constants import get_team_id
    return os.environ.get('VIRTUALPYTEST_TEAM_ID') or get_team_id()


# ---------------------------------------------------------------- picker

def pick_rows(db, team_id: str, min_seen: int, max_attempts: int, limit: int,
              states: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Unnamed recurring screens, most-seen first, still inside this worker's own attempt budget.

    Only NULL / ``unknown_N`` labels are offered (TASK-159 G4), so a real name is never re-decided.
    ``merged_into IS NULL`` skips soft-merged duplicates (they are not a screen of their own).
    """
    query = (db.table('screen_fingerprints')
             .select(_SELECT)
             .eq('team_id', team_id)
             .is_('merged_into', 'null')
             .or_(f'label.is.null,label.match.{UNNAMED_RE}')
             .gt('seen_count', min_seen)
             .not_.is_('sample_image_path', 'null')
             .lt('label_attempts', max_attempts)
             .order('seen_count', desc=True)
             .limit(limit))
    if states:
        query = query.in_('label_state', states)
    return (query.execute().data or []) if query else []


def pick_named_rows(db, team_id: str, limit: int, only_profile: Optional[str] = None
                    ) -> List[Dict[str, Any]]:
    """Named rows for the verification pass. A name is not re-decided here; only re-checked.

    ``only_profile`` scopes the sample to the labels THIS process wrote (the ones the owner asked to be
    re-checked), so the agreement rate is about this worker's judgement and not a blend with the legacy
    names written by auto_classify_unknowns.py months ago.
    """
    query = (db.table('screen_fingerprints')
             .select(_SELECT)
             .eq('team_id', team_id)
             .is_('merged_into', 'null')
             .or_(f'label.not.is.null,label.not.match.{UNNAMED_RE}')   # same idiom as auto_classify_unknowns
             .order('labeled_at', desc=True, nullsfirst=False)
             .limit(limit))
    if only_profile:
        query = query.eq('label_profile', only_profile)
    return query.execute().data or []


# ---------------------------------------------------------------- the AI

# The provider's own words when it refuses. These are the strings the gateway actually builds, and they
# are NOT the error_type names: gateway._format_error renders a refusal as
#   "<endpoint> (<preset>) HTTP 429 for model '<model>': <body>"      (burst / quota wall)
#   "<endpoint> (<preset>) HTTP 402 for model '<model>': <body>"      (the token plan is spent)
#   "<endpoint> (<preset>) HTTP 401 for model '<model>': <body>"      (the key is wrong for this endpoint)
# and the body of a 402 carries "Token Plan usage limit reached (2056)". Matching on "rate_limit" or
# "no_credit" instead would never fire, so the worker would keep hammering an endpoint the provider has
# already refused. An empty answer is NOT in this list: that one is worth a second look.
#
# 401/403 are here because a wrong key cannot fix itself on a retry: the endpoint will refuse the next
# call exactly the same way, so the second one is a wasted round-trip (and the profile that CAN answer
# waits behind it).
_REFUSAL_MARKERS = ('http 429', 'http 402', 'http 401', 'http 403', 'rate_limit', 'no_credit', 'no credit',
                    'usage limit', 'token plan', 'quota', 'insufficient', 'authentication', 'invalid x-api-key')


def _is_refusal(error: Any) -> bool:
    """Did the provider refuse the call (so a retry on the SAME profile is pointless)?"""
    text = str(error or '').lower()
    return any(marker in text for marker in _REFUSAL_MARKERS)


def _ask(profile: str, question: str, path: str, team_id: str, max_tokens: int = 48) -> Dict[str, Any]:
    """One vision call on this worker's own usage key; never raises.

    Not screen_classifier._call: that one hard-codes ``USAGE_KEY = 'vision.classify'``, so its calls would be
    billed and charted as the other namer's work. The AI bill of this process has to be separable from
    auto_classify_unknowns.py's, or the "is the labelling free" question cannot be answered from the log.

    ``max_tokens`` is a FLOOR of ``MIN_ANSWER_TOKENS`` for every call, even the one-word questions: this
    model likes to write "Based on the visual information in the video, it is a MOVING picture" before the
    answer, and at 8 tokens it was cut off mid-word ("...it is a **MOVI"), which reads as an unreadable answer
    and leaves the row alone.

    MEASURED 2026-10-23 on MiniMax M3.1-Flash, the floor has to be much higher than that, because this
    model is a THINKING one: the reasoning comes out of the same ``max_tokens`` budget, so a budget that is
    too small leaves no room for the answer at all. With the old floor of 24 every single call came back
    EMPTY (``stop_reason=max_tokens``, out=24 of 24) and the worker read that as "this frame is unreadable",
    which is the safe direction but names nothing. Same frame, same prompt, measured:
        max_tokens=24   -> '' (empty, stop=max_tokens)
        max_tokens=64   -> 'PHOTO' on 4 of 5 calls, 'PH' on the 5th (cut mid-word)
        max_tokens=128  -> 'PHOTO' on 5 of 5
        max_tokens=256  -> 'PHOTO' on 5 of 5
    So 64 truncates the answer and 128 is both complete and stable. The floor is 128; the open-set naming
    gets 256 because it has to write a slug AND a confidence word.
    """
    from pathlib import Path
    from shared.src.lib.ai import gateway, router
    media_type = 'image/png' if Path(path).suffix.lower() == '.png' else 'image/jpeg'
    try:
        image_b64 = base64.b64encode(Path(path).read_bytes()).decode('ascii')
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': f'image: {exc}'}
    last: Dict[str, Any] = {}
    for name in (profile,) + tuple(FALLBACK_PROFILES):
        try:
            resolution = router.resolve_profile(name, USAGE_KEY, team_id=team_id)
        except Exception as exc:  # noqa: BLE001
            last = {'ok': False, 'error': f'router {name}: {exc}'}
            continue
        # One retry here is what keeps a single flaky frame from costing the row its name for a whole
        # cycle. The gateway retries empty answers on its own for most presets; this is the worker's own
        # second look, and it is deliberately small so a dead endpoint fails fast instead of stalling.
        for attempt in range(2):
            out = gateway.execute(resolution, question, image_b64=image_b64, media_type=media_type,
                                  max_tokens=max(MIN_ANSWER_TOKENS, max_tokens), temperature=None)
            if out.get('success') and (out.get('content') or '').strip():
                return {'ok': True, 'content': out.get('content') or '', 'model': out.get('model'),
                        'usage': out.get('usage'), 'profile': name}
            last = {'ok': False, 'error': out.get('error') or 'call failed / empty answer',
                    'profile': name}
            if _is_refusal(last.get('error')):
                break   # the provider refused this profile: the next one has its own allowance
    return last


def _has(text: str, *words: str) -> bool:
    """Whole-word containment, case- and punctuation-insensitive.

    Word boundaries matter: the poster question answers MENU or NOMENU, and a substring test for MENU would
    match inside NOMENU — the exact opposite of what was asked.
    """
    return any(re.search(rf'\b{re.escape(w)}\b', text or '', re.IGNORECASE) for w in words)


def liveness_of(row: Dict[str, Any]) -> str:
    """'settled' when the registration path already proved the frame is not live; 'ask' when it cannot.

    A single still picture is NOT evidence of motion: asking "is this moving?" of a thumbnail gets a coin-flip
    answer, which is exactly what happened when the first version asked it of a freeze row (three identical
    calls on one stored frame answered MOVING, STILL, STILL). So the question is only asked where the path
    that made the row cannot answer it.

      freeze            the freeze detector froze this frame: by definition not live. Settled.
      localize_abstain  Localize read this frame and could not name it; a moving picture is answered `live`
                        and skipped before a row is made (monitor_localize.GATE_LIVE). Settled.
      screen            registered by the settled-screen path, which is opt-in per device
                        (DEVICE<N>_LOCALIZE_SETTLED=1) and CAN force a `live` frame to the matcher when its
                        dHash is stable (TASK-159 s12 known limit). This is the only case that is genuinely
                        unknown, so this is the only case the model is asked about.
    """
    return 'ask' if (row.get('incident_type') == 'screen') else 'settled'


def _vote(profile: str, question: str, path: str, team_id: str, votes: int,
          positive: Tuple[str, ...], negative: Tuple[str, ...],
          names: Tuple[str, str] = ('yes', 'no')) -> Tuple[str, str]:
    """Ask a two-sided closed question ``votes`` times; return (verdict, human-readable summary).

    Unanimity, for the reason measured in ask_live: this model samples on its own and three identical calls on
    one frame answered both ways. A closed question is only worth asking if its answer is stable; when it is
    not, 'unknown' is the honest result and the caller leaves the row alone.

    ``names`` puts the two sides into the words a human will read in ``label_note`` ("live, screen, screen"),
    not the mechanism's ("yes, no, no").
    """
    decided: List[str] = []      # 'yes' / 'no' / 'unclear' / 'error' — what the unanimity check reads
    shown: List[str] = []        # the same answers in words a human reads in label_note
    for _ in range(max(1, votes)):
        out = _ask(profile, question, path, team_id, max_tokens=MIN_ANSWER_TOKENS)
        if not out.get('ok'):
            decided.append('error')
            shown.append(f'error: {str(out.get("error"))[:60]}')
            continue
        raw = (out.get('content') or '').strip()
        yes, no = _has(raw, *positive), _has(raw, *negative)
        decided.append('yes' if yes and not no else ('no' if no and not yes else 'unclear'))
        shown.append(names[0] if decided[-1] == 'yes' else (names[1] if decided[-1] == 'no' else 'unclear'))
    summary = f'{votes} vote(s): ' + ', '.join(shown)
    real = [a for a in decided if a in ('yes', 'no')]
    if real and len(real) == votes and len(set(real)) == 1:
        return real[0], summary
    return 'unknown', summary


def ask_ui(profile: str, path: str, team_id: str, votes: int = 3) -> Tuple[str, str]:
    """('screen'|'photo'|'unknown', raw): is this a picture OF a device screen at all?

    This is the precondition of every state hint: the TASK-159 poster rule reads "no menu -> poster", which is
    only an inference when a menu was possible. Without this gate a blurry photo of a wall is confidently
    named "Full-screen poster" — which is exactly what the first run of this worker did (see BUG-0849).
    """
    verdict, summary = _vote(profile, UI_QUESTION, path, team_id, votes, ('SCREEN',), ('PHOTO',),
                             names=('screen', 'photo'))
    return {'yes': 'screen', 'no': 'photo'}.get(verdict, 'unknown'), summary


def ask_live(profile: str, path: str, team_id: str, votes: int = 3) -> Tuple[str, str]:
    """('live'|'screen'|'unknown', raw) after asking ``votes`` times.

    MEASURED 2026-10-23 on the free MiniMax model, the non-determinism is not theoretical: three identical
    calls on ONE stored frame answered MOVING, STILL, STILL. No temperature is sent (the profile sets none
    and the SDK that carries it does not), so the provider samples on its own and a single answer is noise.
    Naming a screen on one sample is the "named three ways" incoherence TASK-159 §1 was opened for, so this
    gate requires UNANIMITY. The measurement was taken on the coding_plan/vlm endpoint; the guard is kept
    on the M3.1-Flash endpoint because nothing promises that one is deterministic either.

    A split vote returns 'unknown' and the row is left alone, which is the safe direction: a screen nobody
    names costs one sighting, a live picture named "poster" costs the truth. The individual answers are
    returned so the note records what was actually said.
    """
    verdict, summary = _vote(profile, LIVE_QUESTION, path, team_id, votes,
                             ('MOVING', 'LIVE', 'VIDEO', 'PLAYING'),
                             ('STILL', 'SCREEN', 'STATIC', 'SETTLED'),
                             names=('live', 'screen'))
    return {'yes': 'live', 'no': 'screen'}.get(verdict, 'unknown'), summary


def ask_states(profile: str, path: str, team_id: str, hints=None) -> Optional[Dict[str, Any]]:
    """TASK-159 G5's closed states, asked in order; the first hit names the row. None = none of them."""
    for node_label, label, question, answer in (hints or []):
        out = _ask(profile, question, path, team_id, max_tokens=MIN_ANSWER_TOKENS)
        if not out.get('ok'):
            continue
        raw = (out.get('content') or '').strip()
        if not _has(raw, answer):
            continue
        return {'label': label, 'node_label': node_label,
                'how': f'state_check:{label}', 'raw': raw[:120],
                'model': out.get('model')}
    return None


def ask_open(profile: str, path: str, team_id: str) -> Dict[str, Any]:
    """Open-set naming with an explicit confidence. Returns {'label', 'confidence', 'raw', 'model'}.

    Only HIGH is allowed to become a name. The confidence word is asked for precisely because an
    open-set slug is always fluent: fluency is not evidence, so the model has to say how sure it is.
    """
    out = _ask(profile, OPEN_QUESTION, path, team_id, max_tokens=OPEN_ANSWER_TOKENS)
    if not out.get('ok'):
        return {'label': None, 'confidence': 'none', 'raw': str(out.get('error'))[:200]}
    raw = (out.get('content') or '').strip()
    parts = raw.split('|')
    name = slug(parts[0])
    # Normalise the word, then match it. Truncating to 3 characters first (to allow "HIGH"/"HIGHLY") would
    # turn HIGH into 'HIG', match nothing, and land on LOW — which silently disables every open-set name.
    said = (parts[1].strip().upper() if len(parts) > 1 else '')
    confidence = next((c for c in ('HIGH', 'MED', 'LOW') if said.startswith(c)), 'LOW')
    if not name:
        confidence = 'LOW'
    return {'label': name, 'confidence': confidence, 'raw': raw[:200], 'model': out.get('model')}


def verify_label(profile: str, path: str, team_id: str, label: str) -> Tuple[bool, str]:
    """An independent second opinion: a different question about an existing name. Never writes."""
    out = _ask(profile, VERIFY_QUESTION.format(label=label), path, team_id, max_tokens=MIN_ANSWER_TOKENS)
    if not out.get('ok'):
        return False, str(out.get('error'))[:200]
    raw = (out.get('content') or '').strip()
    return _has(raw, 'YES'), raw[:200]


# ---------------------------------------------------------------- link / propose

def fingerprint_candidates(db, team_id: str) -> List[Dict[str, Any]]:
    """Every fingerprinted navigation node of every interface, flattened for match_screen.

    The interface is read FROM the node that matches; it is never inferred from the scope's device part
    (TASK-159 G6: an unmatched screen is not linked to an interface).
    """
    from shared.src.lib.database.screen_fingerprints_db import fp_from_blob
    trees = (db.table('navigation_trees').select('id,userinterface_id').eq('team_id', team_id).execute().data or [])
    if not trees:
        return []
    tree_of = {t['id']: t.get('userinterface_id') for t in trees}
    uis = (db.table('userinterfaces').select('id,name').eq('team_id', team_id).execute().data or [])
    name_of = {u['id']: u.get('name') for u in uis}
    nodes = (db.table('navigation_nodes')
             .select('tree_id,node_id,label,node_type,data')
             .eq('team_id', team_id)
             .in_('tree_id', list(tree_of.keys()))
             .limit(5000).execute().data or [])
    out: List[Dict[str, Any]] = []
    for n in nodes:
        blob = (n.get('data') or {}).get('fingerprint') if isinstance(n.get('data'), dict) else None
        fp = fp_from_blob(blob)
        if not fp or not n.get('node_id'):
            continue
        if (n.get('node_type') or 'screen') in ('entry', 'action'):
            continue
        ui_id = tree_of.get(n.get('tree_id'))
        out.append({'dhash': fp['dhash'], 'region_center': fp['region_center'],
                    'node_id': n['node_id'], 'label': n.get('label') or n['node_id'],
                    'userinterface': name_of.get(ui_id) or '', 'fingerprint': blob})
    return out


def link_node(row: Dict[str, Any], candidates: List[Dict[str, Any]]):
    """The fingerprinted node this row's picture matches, or None. Ambig across interfaces -> None."""
    from shared.src.lib import screen_memory
    fp = {'dhash': row.get('dhash'), 'region_center': row.get('region_center')}
    if not fp['dhash'] or not fp['region_center'] or not candidates:
        return None
    hit = screen_memory.match_screen(fp, candidates)
    if not hit:
        return None
    best, dist = hit
    others = [c for c in candidates
              if c is not best and c.get('userinterface') != best.get('userinterface')
              and screen_memory.match_screen(fp, [c])]
    if others:
        return None      # two interfaces claim this picture: a human decides, not the worker
    return {**best, 'dist': dist}


def propose_node(db, team_id: str, row: Dict[str, Any], label: str, dom: Dict[str, Any]) -> bool:
    """A pending entry in the operator's existing "Needs a name" queue. Never creates a tree node.

    Same upsert auto_classify_unknowns uses, so one row of the queue per picture whatever worker
    looked at it. ``userinterface`` is required by that table's unique key and is NOT guessed here
    (TASK-159 G6): with no interface the proposal is skipped and the row keeps its name only.
    """
    userinterface = (row.get('userinterface') or '').strip()
    if not userinterface:
        return False
    from datetime import datetime, timezone
    fingerprint = row.get('fingerprint')
    if not isinstance(fingerprint, dict) or not fingerprint.get('dhash'):
        fingerprint = {'dhash': row['dhash'], 'region_center': row.get('region_center')}
    payload = {'team_id': team_id, 'userinterface': userinterface, 'cluster_dhash': row['dhash'],
               'classification': 'unknown', 'status': 'pending', 'proposed_name': label,
               'screen_type': None, 'frame_count': int(row.get('seen_count') or 0),
               'image_url': row.get('sample_image_path'), 'fingerprint': fingerprint,
               'dom': dom, 'last_scan_at': datetime.now(timezone.utc).isoformat()}
    try:
        db.table('userinterface_unknown_screens').upsert(
            payload, on_conflict='team_id,userinterface,cluster_dhash').execute()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f'[screen_label] propose failed for {row["id"]}: {exc}')
        return False


# ---------------------------------------------------------------- writes

def name_row(db, team_id: str, row_id: str, label: str) -> bool:
    """The ONLY way a label is written: name_screen_row, which cannot touch a real name (G4).

    The function RETURNS integer, and PostgREST hands back a bare scalar, but a function that returns a set
    would hand back a one-element list — and ``bool([0])`` is True, which would report "named" for a row it
    did not touch. Unwrap a list explicitly so the success flag means what it says.
    """
    try:
        res = db.rpc(_NAME_RPC, {'p_team_id': team_id, 'p_id': row_id, 'p_label': label}).execute()
        data = res.data
        if isinstance(data, (list, tuple)):
            data = data[0] if data else 0
        return bool(data)
    except Exception as exc:  # noqa: BLE001
        print(f'[screen_label] name_screen_row failed for {row_id}: {exc}')
        return False


def store_fingerprint(db, team_id: str, row_id: str, blob: Dict[str, Any],
                      node_id: Optional[str] = None) -> bool:
    """Give a row a fingerprint, ONCE, through the single writer.

    The blob is the NODE's own v6 fingerprint (never re-derived) when the row was linked to a
    navigation tree node.  The write goes through ``link_screen_fingerprint`` (migration 20261023b),
    so "written once" is a database rule and not a convention: a row that already has a fingerprint
    keeps it, and a name is never touched.
    """
    from shared.src.lib.database.screen_fingerprints_db import link_screen_fingerprint
    if not blob or not blob.get('dhash'):
        return False
    if link_screen_fingerprint(team_id, row_id, blob, node_id):
        return True
    # The RPC refuses when the row already has one: that is the rule working, not a failure.
    return False


def mark(db, team_id: str, row_id: str, state: str, note: str = '', profile: Optional[str] = None,
         node_id: Optional[str] = None, bump_attempts: bool = True) -> None:
    """This worker's own bookkeeping. Never touches ``label``."""
    from datetime import datetime, timezone
    upd: Dict[str, Any] = {'label_state': state,
                           'label_note': (note or '')[:500] or None,
                           'label_profile': profile,
                           'labeled_at': datetime.now(timezone.utc).isoformat()}
    if node_id is not None:
        upd['linked_node_id'] = node_id
    try:
        q = (db.table('screen_fingerprints').select('label_attempts')
             .eq('id', row_id).eq('team_id', team_id).limit(1).execute())
        cur = ((q.data or [{}])[0]).get('label_attempts') or 0
        upd['label_attempts'] = int(cur) + (1 if bump_attempts else 0)
        db.table('screen_fingerprints').update(upd).eq('id', row_id).eq('team_id', team_id).execute()
    except Exception as exc:  # noqa: BLE001
        print(f'[screen_label] mark({state}) failed for {row_id}: {exc}')


# ---------------------------------------------------------------- sample images

def resolve_sample(sample: Optional[str], scope: Optional[str] = None
                   ) -> Tuple[Optional[str], Optional[str]]:
    """(path, reason). The durable data-URI thumbnail the registry stores, or the host fetch.

    Reuses auto_classify_unknowns.resolve_sample_path so both workers read a row's picture the same way.
    A temp file returned here is the caller's to delete.
    """
    from backend_server.scripts.auto_classify_unknowns import resolve_sample_path
    return resolve_sample_path(sample, scope)


# ---------------------------------------------------------------- fingerprints

def pick_unfingerprinted_rows(db, team_id: str, min_seen: int, limit: int) -> List[Dict[str, Any]]:
    """Rows that HAVE a real name but NO fingerprint, most-seen first.

    The owner's goal is a screen that is labelled AND fingerprinted, so a named row without a
    fingerprint is unfinished work, not a finished one.  A row that is still ``unknown_N`` is the
    naming pass's business, not this one's.
    """
    rows = (db.table('screen_fingerprints').select(_SELECT)
            .eq('team_id', team_id).is_('merged_into', 'null')
            .not_.is_('label', 'null').is_('fingerprint', 'null')
            .gt('seen_count', min_seen)
            .order('seen_count', desc=True).limit(limit).execute().data or [])
    return [r for r in rows if not re.match(UNNAMED_RE, str(r.get('label') or ''))]


def build_row_fingerprint(row: Dict[str, Any], path: str) -> Optional[Dict[str, Any]]:
    """The row's OWN v6 fingerprint, from the picture the row still has. None when it cannot be trusted.

    The identity is the row's own measured hash, and that is exactly what a monitor-computed blob
    carries: measured on every row that has one, the row's ``dhash`` IS the blob's ``dhash`` and
    the row's ``region_center`` IS the blob's ``regions.center`` -- distance 0, not "close".

    The picture adds the layers the identity cannot: the other regions, the focused-tile crop and
    the focus signature.  It must AGREE with the identity, or it is not this row's picture: the
    row goes to the review list instead of being written with a fingerprint that describes another
    screen.  Measured 2026-10-23 on the 21 unfinished rows: the stored 320x180 thumbnail's dHash is
    within the matcher's tolerance of the row's own full-frame dHash for 26 of them (median 7).
    """
    try:
        import cv2
        from backend_host.src.controllers.verification import image_helpers as ih
        from shared.src.lib import screen_memory
    except Exception as exc:  # noqa: BLE001
        print(f'[screen_label] fingerprint tooling unavailable: {exc}')
        return None
    img = cv2.imread(path)
    if img is None or not getattr(img, 'size', 0):
        return None
    try:
        thumb = ih.ImageHelpers(None, None).compute_fingerprint(img, ocr=False)
    except Exception as exc:  # noqa: BLE001
        print(f'[screen_label] compute_fingerprint failed: {exc}')
        return None
    if not thumb or not thumb.get('dhash'):
        return None
    full_max, _ = screen_memory.tolerance()
    dist = screen_memory.dhash_hamming(row.get('dhash') or '', thumb['dhash'])
    if dist > full_max:
        return None      # the picture does not agree with the row's own identity -> a human
    # The identity is the row's own.  The thumbnail's per-region hashes (top/bottom/left) are NOT
    # taken: a region is a FRACTION of the frame, and a 320x180 thumbnail of a portrait screen has
    # a different aspect, so its "top" covers a different part of the screen than the original's.
    # `focus` is normalised (x, y in 0..1) and `crop` is the focused tile's own hash, so both
    # survive the downscale and are kept.
    regions = {'full': row.get('dhash'), 'center': row.get('region_center')}
    from datetime import datetime, timezone
    return {'v': 6,
            'dhash': row.get('dhash'),
            'regions': regions,
            'crop': thumb.get('crop'),
            'focus': thumb.get('focus'),
            'title': None,
            'text': None,
            'captured_at': row.get('last_seen') or datetime.now(timezone.utc).isoformat(),
            'derived_from': 'row-thumbnail'}


def fingerprint_pass(db, team_id: str, min_seen: int, limit: int, apply: bool,
                     candidates: Optional[List[Dict[str, Any]]] = None) -> Dict[str, int]:
    """Give every named-but-unfingerprinted row a fingerprint. Never renames, never deletes.

    Two ways to get one, in this order:

    1. **the navigation tree knows this picture** -- the node's own v6 fingerprint, and the row is
       linked to that node.  Measured 2026-10-23: none of the 21 unfinished rows is in the tree
       (they are screens the tree does not know -- a broadcast, a promo, a photo of a room), so this
       is rare; it is still the right answer when it happens.
    2. **the row's own picture** -- the v6 of the image the row still has, checked against the
       row's own measured identity.

    A row that can do neither is listed for review and NOT written.  A row that already has a
    fingerprint is left alone: a fingerprint is written once.
    """
    stats = {'fp_picked': 0, 'fp_linked': 0, 'fp_written': 0, 'fp_review': 0, 'fp_no_sample': 0, 'fp_failed': 0}
    rows = pick_unfingerprinted_rows(db, team_id, min_seen, limit)
    stats['fp_picked'] = len(rows)
    if not rows:
        return stats
    if candidates is None:
        candidates = fingerprint_candidates(db, team_id)
    for row in rows:
        link = link_node(row, candidates)
        if link:
            blob, node_id = link.get('fingerprint'), link.get('node_id')
            how = f'linked to tree node {node_id} ({link.get("label")})'
        else:
            path, reason = resolve_sample(row.get('sample_image_path'), row.get('scope'))
            if not path:
                stats['fp_no_sample'] += 1
                print(f'  [fp] {row["scope"]:<22} {str(row.get("label"))[:26]:<26} no sample image '
                      f'({reason}) — left for a human')
                continue
            temp = path != row.get('sample_image_path')
            try:
                blob = build_row_fingerprint(row, path)
                node_id = None
                how = 'its own picture'
            finally:
                if temp:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
            if not blob:
                stats['fp_review'] += 1
                print(f'  [fp] {row["scope"]:<22} {str(row.get("label"))[:26]:<26} picture does not agree '
                      f'with the row\'s own identity — left for a human')
                continue
        if not apply:
            stats['fp_written'] += 1
            print(f'  [fp] [dry-run] {row["scope"]:<22} {str(row.get("label"))[:26]:<26} -> fingerprint from {how}')
            continue
        if store_fingerprint(db, team_id, row['id'], blob, node_id):
            stats['fp_written'] += 1
            stats['fp_linked'] += int(bool(node_id))
            print(f'  [fp] {row["scope"]:<22} {str(row.get("label"))[:26]:<26} -> fingerprint from {how}')
        else:
            stats['fp_failed'] += 1
            print(f'  [fp] {row["scope"]:<22} {str(row.get("label"))[:26]:<26} NOT written '
                  f'(already had one?)')
    return stats


# ---------------------------------------------------------------- the loop

def run_once(team_id: str, min_seen: int, limit: int, apply: bool, profile: str,
             max_attempts: int = MAX_ATTEMPTS, min_confidence: str = 'HIGH',
             votes: int = LIVENESS_VOTES, fingerprints: bool = True) -> Dict[str, int]:
    from shared.src.lib.utils.supabase_utils import get_supabase_client
    db = get_supabase_client()
    if db is None:
        print('[screen_label] no Supabase client — nothing to do')
        return {}

    rows = pick_rows(db, team_id, min_seen, max_attempts, limit)
    stats = {'picked': len(rows), 'live': 0, 'named': 0, 'linked': 0, 'proposed': 0,
             'review': 0, 'unknown': 0, 'no_sample': 0, 'failed': 0}
    print(f'[screen_label] {len(rows)} unnamed row(s) with seen_count > {min_seen} '
          f'(profile={profile}, apply={apply}, need confidence >= {min_confidence}, '
          f'liveness {votes} vote(s))')
    if not rows:
        # A named row without a fingerprint is unfinished work too, and the naming pass says
        # nothing about those rows -- so the fingerprint pass still runs.
        if fingerprints:
            stats.update(fingerprint_pass(db, team_id, min_seen, limit, apply))
        return stats

    candidates = fingerprint_candidates(db, team_id)
    print(f'[screen_label] {len(candidates)} fingerprinted node(s) to match against')

    for row in rows:
        path, reason = resolve_sample(row.get('sample_image_path'), row.get('scope'))
        if not path:
            stats['no_sample'] += 1
            print(f'  {row["scope"]:<22} no sample image ({reason}) — left alone')
            continue
        temp = path != row.get('sample_image_path')
        try:
            # CLOSED QUESTION 0a: is this a picture OF a screen at all? Every state hint below assumes it is.
            ui, ui_raw = ask_ui(profile, path, team_id, votes=votes)
            if ui != 'screen':
                stats['review' if ui == 'photo' else 'unknown'] += 1
                print(f'  {row["scope"]:<22} {str(row.get("label")):<14} '
                      f'{"not a device screen" if ui == "photo" else "is-it-a-screen split"} ({ui_raw})'
                      f'{" -> left for a human" if ui == "photo" else ""}')
                if apply:
                    mark(db, team_id, row['id'], 'review', f'not a device screen ({ui_raw})' if ui == 'photo'
                         else f'is-it-a-screen split ({ui_raw})', profile)
                continue

            # IS IT A SCREEN AT ALL? A freeze row was frozen and an abstain row passed the live gate, so
            # only a row from the opt-in settled path can still be a moving picture and needs asking.
            if liveness_of(row) == 'ask':
                liveness, raw = ask_live(profile, path, team_id, votes=votes)
                if liveness != 'screen':
                    if liveness == 'live':
                        stats['live'] += 1
                        print(f'  {row["scope"]:<22} {str(row.get("label")):<14} MOVING -> not a screen, not named')
                        if apply:
                            mark(db, team_id, row['id'], 'live', f'settled-path row, {raw}', profile)
                    else:
                        stats['unknown'] += 1
                        print(f'  {row["scope"]:<22} {str(row.get("label")):<14} liveness split '
                              f'({raw}) -> left for a human')
                        if apply:
                            mark(db, team_id, row['id'], 'review', f'settled-path row, liveness split: {raw}',
                                 profile)
                    continue
                raw = raw
            else:
                raw = f'not live by path: incident_type={row.get("incident_type")}'

            # CLOSED QUESTIONS 1..n: the TASK-159 states, then open-set naming.
            hints = STATE_HINTS if state_hints_for is None else state_hints_for(row)
            state = ask_states(profile, path, team_id, hints)
            if state:
                # HIGH here is EARNED, not assumed: two unanimous closed gates (is-it-a-screen, and for a
                # settled-path row liveness) stand in front of it. The first version of this worker called a
                # closed yes/no HIGH on its own and named two blurry photos of a wall "Full-screen poster".
                label, how, confidence = state['label'], state['how'], 'HIGH'
                raw = f'{ui_raw}; state_check {state["raw"]}'
            else:
                opened = ask_open(profile, path, team_id)
                label, confidence, how = opened.get('label'), opened.get('confidence'), 'open_set'
                raw = opened.get('raw') or ''
                if not label:
                    stats['review'] += 1
                    if apply:
                        mark(db, team_id, row['id'], 'review', f'no name offered: {raw}', profile)
                    print(f'  {row["scope"]:<22} {str(row.get("label")):<14} no name offered — left for a human')
                    continue

            # LOW CONFIDENCE IS NOT A GUESS
            order = {'LOW': 0, 'MED': 1, 'HIGH': 2}
            if order.get(confidence, 0) < order.get(min_confidence, 2):
                stats['review'] += 1
                print(f'  {row["scope"]:<22} {str(row.get("label")):<14} confidence={confidence} '
                      f'-> left unknown_N for a human ({label})')
                if apply:
                    mark(db, team_id, row['id'], 'review',
                         f'{how} confidence={confidence}, would say {label}: {raw}', profile)
                continue

            if not apply:
                print(f'  [dry-run] {row["scope"]:<22} {str(row.get("label")):<14} -> {label} ({how}, {confidence})')
                stats['named'] += 1
                continue

            # LINK or PROPOSE
            link = link_node(row, candidates)
            proposed = False
            if link:
                stats['linked'] += 1
                store_fingerprint(db, team_id, row['id'], link.get('fingerprint'))
            else:
                proposed = propose_node(db, team_id, row, label,
                                       {'screen_type': None, 'screen_summary': label,
                                        'state_of_node': state.get('node_label') if state else None,
                                        'worker': 'screen_label_worker', 'how': how})
                stats['proposed'] += int(proposed)

            # NAME, once, through the single writer.
            if name_row(db, team_id, row['id'], label):
                stats['named'] += 1
                mark(db, team_id, row['id'], 'named',
                     f'{how} confidence={confidence}: {raw or label}',
                     profile, node_id=(link or {}).get('node_id'))
                print(f'  {row["scope"]:<22} {str(row.get("label")):<14} -> {label} '
                      f'({how}; {"linked " + link["label"] if link else ("proposed" if proposed else "named only")})')
            else:
                stats['failed'] += 1
                mark(db, team_id, row['id'], 'review', 'name_screen_row wrote 0 rows', profile)
                print(f'  {row["scope"]:<22} {str(row.get("label")):<14} -> {label} NOT written '
                      f'(already had a real name?)')
        finally:
            if temp:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    # The fingerprint pass.  A row that has a real NAME but no fingerprint is still unfinished:
    # the owner's goal is a screen that is labelled AND fingerprinted.
    if fingerprints:
        stats.update(fingerprint_pass(db, team_id, min_seen, limit, apply, candidates))
    return stats


def run_verify(team_id: str, limit: int, apply: bool, profile: str,
               only_profile: Optional[str] = 'own') -> Dict[str, int]:
    """Re-check, never re-decide.  ``profile`` is the model asked the second question, which defaults to
    the same free model: the independence the owner asked for is in the PROMPT (\"is this label correct?\"
    rather than \"name this screen\"), and keeping one model keeps the bill at 0."""
    """The second, independent pass. Re-checks; it does not decide. Disagreements are listed."""
    from shared.src.lib.utils.supabase_utils import get_supabase_client
    db = get_supabase_client()
    if db is None:
        print('[screen_label] no Supabase client — nothing to verify')
        return {}
    scope = profile if only_profile == 'own' else only_profile
    rows = pick_named_rows(db, team_id, limit, only_profile=scope)
    stats = {'checked': 0, 'agree': 0, 'disagree': 0, 'unreadable': 0, 'no_sample': 0}
    print(f'[screen_label] verify: re-checking {len(rows)} row(s) named by {scope or "any profile"} '
          f'with an independent prompt')
    for row in rows:
        label = row.get('label')
        if not label or re.match(UNNAMED_RE, str(label)):
            continue
        stats['checked'] += 1
        path, reason = resolve_sample(row.get('sample_image_path'), row.get('scope'))
        if not path:
            stats['no_sample'] += 1
            print(f'  {row["scope"]:<22} {label:<24} no sample ({reason})')
            continue
        temp = path != row.get('sample_image_path')
        try:
            ok, raw = verify_label(profile, path, team_id, str(label))
            if raw.startswith(('router', 'image', 'call failed')):
                stats['unreadable'] += 1
                continue
            if ok:
                stats['agree'] += 1
                print(f'  {row["scope"]:<22} {label:<24} AGREED')
            else:
                stats['disagree'] += 1
                print(f'  {row["scope"]:<22} {label:<24} DISAGREED ({raw[:80]}) — listed, not applied')
                if apply:
                    mark(db, team_id, row['id'], 'disagree',
                         f'verify said NO to "{label}": {raw}', profile, bump_attempts=False)
        finally:
            if temp:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    answered = stats['agree'] + stats['disagree']
    rate = (100.0 * stats['agree'] / answered) if answered else 0.0
    print(f'\nAGREEMENT {stats["agree"]}/{answered} = {rate:.1f} % '
          f'({stats["unreadable"]} unreadable, {stats["no_sample"]} without a sample)')
    stats['agreement_pct'] = round(rate, 1)
    return stats


def review_list(db, team_id: str, limit: int = 50) -> None:
    """The human queue: what the worker would not decide, and what the verifier disagreed with."""
    res = (db.table('screen_fingerprints')
           .select('scope,label,label_state,label_note,seen_count,sample_image_path')
           .eq('team_id', team_id).is_('merged_into', 'null')
           .in_('label_state', ['review', 'disagree', 'live'])
           .order('seen_count', desc=True).limit(limit).execute())
    rows = res.data or []
    print(f'\nHUMAN REVIEW ({len(rows)} row(s)):')
    for r in rows:
        print(f'  [{r.get("label_state"):<9}] {r.get("scope"):<22} '
              f'{str(r.get("label")):<16} seen={r.get("seen_count"):<6} {(r.get("label_note") or "")[:90]}')


# ---------------------------------------------------------------- cli

def parse_args(argv=None):
    from backend_server.scripts.auto_classify_unknowns import STATE_HINTS as _STATES, state_hints_for as _for
    global STATE_HINTS, state_hints_for
    STATE_HINTS = _STATES
    state_hints_for = _for   # the states are asked only of the devices they were written for (operator STB)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--team-id', default=_team_id_arg())
    p.add_argument('--min-seen', type=int, default=MIN_SEEN,
                   help=f'only screens seen MORE than this often (default {MIN_SEEN}, the retention '
                        f'prune floor). The owner\'s ">10 seen" METRIC lives in '
                        f'screen_label_coverage.py and is deliberately not this number.')
    p.add_argument('--limit', type=int, default=DEFAULT_LIMIT)
    p.add_argument('--apply', action='store_true', default=False,
                   help='actually write; default is read-only (dry run)')
    p.add_argument('--dry-run', action='store_true', help='explicitly read-only (the default)')
    p.add_argument('--verify', action='store_true',
                   help='re-check named rows with an independent prompt; disagreements are listed only')
    p.add_argument('--verify-limit', type=int, default=VERIFY_SAMPLE)
    p.add_argument('--profile', default=DEFAULT_PROFILE,
                   help=f'pinned AI profile (default {DEFAULT_PROFILE}, the free MiniMax VLM)')
    p.add_argument('--min-confidence', choices=('HIGH', 'MED'), default='HIGH',
                   help='the lowest confidence allowed to become a name (default HIGH)')
    p.add_argument('--liveness-votes', type=int, default=LIVENESS_VOTES,
                   help=f'how many times to ask "moving or still" before deciding '
                        f'(default {LIVENESS_VOTES}; unanimity required)')
    p.add_argument('--verifier-profile', default=None,
                   help='AI profile for --verify (default: the same profile as --profile, free; pin a '
                        'second model here for a stronger agreement number)')
    p.add_argument('--verify-all', action='store_true',
                   help='--verify every named row, not only the ones this worker wrote')
    p.add_argument('--review', action='store_true', help='print the human review list and exit')
    p.add_argument('--no-fingerprints', action='store_true',
                   help='skip the fingerprint pass (a row with a name but no fingerprint stays unfinished)')
    p.add_argument('--fingerprints-only', action='store_true',
                   help='run ONLY the fingerprint pass: give every named row that has no fingerprint one, '
                        'without naming anything')
    return p.parse_args(argv)


def main(argv=None) -> int:
    load_dotenv(os.path.join(_REPO, '.env'), override=False, encoding='utf-8-sig')
    args = parse_args(argv)
    if not args.team_id:
        print('[screen_label] team_id is required (--team-id or VIRTUALPYTEST_TEAM_ID)', file=sys.stderr)
        return 2
    from shared.src.lib.utils.supabase_utils import get_supabase_client
    if args.review:
        db = get_supabase_client()
        if db is None:
            return 2
        review_list(db, args.team_id)
        return 0

    started = time.time()
    if args.verify:
        print(f'[screen_label] VERIFY team={args.team_id} profile={args.verifier_profile or args.profile} '
              f'(named by {args.profile}) apply={args.apply}')
        stats = run_verify(args.team_id, args.verify_limit, args.apply,
                           args.verifier_profile or args.profile,
                           only_profile=None if args.verify_all else 'own')
    else:
        print(f'[screen_label] team={args.team_id} min_seen>{args.min_seen} profile={args.profile} '
              f'apply={args.apply}')
        if args.fingerprints_only:
            from shared.src.lib.utils.supabase_utils import get_supabase_client as _c
            db = _c()
            if db is None:
                return 2
            print('[screen_label] FINGERPRINT PASS only: naming is not part of this run')
            stats = fingerprint_pass(db, args.team_id, args.min_seen, args.limit, args.apply)
        else:
            stats = run_once(args.team_id, args.min_seen, args.limit, args.apply, args.profile,
                             min_confidence=args.min_confidence, votes=args.liveness_votes,
                             fingerprints=not args.no_fingerprints)
        if args.apply:
            from shared.src.lib.utils.supabase_utils import get_supabase_client as _c
            if _c() is not None:
                review_list(_c(), args.team_id)
    print(f'[screen_label] done in {time.time() - started:.1f}s — {stats}')
    return 0


if __name__ == '__main__':
    sys.exit(main())