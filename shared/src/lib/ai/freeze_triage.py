"""Freeze-alert triage by Jev (TASK-38 goal 5, TASK-55): two questions over the facts the host measured.

1. a closed choice over the change facts: still / moving / freeze;
2. a focused UI-or-video question over the words OCR read, asked alone (mixed with the change facts,
   Jev ignored the words).

``triage`` turns both into keep (a real freeze to look at) or dismiss. Cameras are always kept
(owner 2026-10-05: camera alerts are never dismissed by Jev). Used by the bench
(``scripts/jev_freeze/decide.py``) and the server (``nightwatch_handler``, shadow).
"""
from typing import Any, Callable, Mapping, Optional

from .freeze_facts import is_camera

USAGE = 'text.decision.freeze_triage'
INSTRUCTIONS = 'Is this freeze alert a real freeze, a still screen by design, or moving video?'
OPTIONS = [
    {'id': 'still', 'facts': 'the screen is still by design: a menu, guide, paused or static picture; '
                             'the frames show the same content'},
    {'id': 'moving', 'facts': 'the picture is moving: video or animation changes between the frames, '
                              'so the freeze alert is false'},
    {'id': 'freeze', 'facts': 'the video should be playing but the picture is stuck: the same frame on a '
                              'channel or player that normally moves'},
]

# Second, focused question on the words OCR read (owner's idea, 2026-10-05): a menu, guide, splash or
# notice screen is never a video freeze. Asked on the words alone: mixed with the change facts, Jev
# weighed the change and ignored the words.
UI_QUESTION = {'ui': {'type': 'noul',
                      'instructions': 'From the words read on the TV screen, is it showing a user interface (menu, '
                                      'guide, app home, splash or logo screen, list of titles, a notice like a '
                                      'broadcast pause) rather than full-screen video?',
                      'criteria': {'true': 'menu words, section names, buttons, lists of titles, a notice or a '
                                           'brand or logo on its own',
                                   'false': 'no words, or only scattered words like subtitles or a channel caption '
                                            'over video'}}}
UI_DISMISS = 0.5  # P(UI) at or above this turns a "freeze" verdict into "still"


def ui_state(device_model: Any, record: Mapping[str, Any]) -> dict:
    text = record.get('text') or {}
    return {'device': device_model or 'unknown',
            'words_first_frame': text.get('read_first') or '(none readable)',
            'words_last_frame': text.get('read_last') or '(none readable)'}


def triage(choice: Optional[str], ui: Optional[float], device_model: Any = None) -> str:
    """keep (a real freeze to look at) or dismiss. Cameras are always kept."""
    if is_camera(device_model):
        return 'keep'
    if choice == 'freeze' and (ui is None or ui < UI_DISMISS):
        return 'keep'
    return 'dismiss'


def ask(resolution: Any, facts: Mapping[str, Any], device_model: Any, refs: Mapping[str, Any],
        choose: Callable, decide: Callable) -> dict:
    """The two Jev calls for one alert. ``facts`` is the ``jev_facts`` record (``facts`` lines,
    ``n_frames``, ``text``). Returns ``{choice, confidence, ui, triage, cost, decision_ids, success,
    error}``; ``success`` is False when the choice failed or Jev is off (``error`` says why). A failed
    UI question leaves ``ui`` None, which keeps the alert. Never raises."""
    refs = dict(refs or {})
    try:
        state = {'facts': list(facts.get('facts') or []), 'frames': facts.get('n_frames')}
        out = choose(resolution, state, OPTIONS, instructions=INSTRUCTIONS, refs=refs, log=True) or {}
        ui_out: dict = {}
        if decide and out.get('success') and not is_camera(device_model):
            ui_out = decide(resolution, ui_state(device_model, facts), UI_QUESTION, refs=refs, log=True) or {}
        ui = ((ui_out.get('answers') or {}).get('ui') or {}).get('noul')
        choice = out.get('choice')
        return {'choice': choice, 'confidence': out.get('confidence'), 'ui': ui,
                'triage': triage(choice, ui, device_model),
                'probabilities': out.get('probabilities') or {},
                'cost': float(out.get('cost') or 0) + float(ui_out.get('cost') or 0),
                'decision_ids': [d for d in (out.get('decision_id'), ui_out.get('decision_id')) if d],
                'ms': out.get('ms'),
                'success': bool(out.get('success')),
                'error': out.get('error') or ui_out.get('error')}
    except Exception as e:
        return {'choice': None, 'confidence': None, 'ui': None, 'triage': 'keep', 'probabilities': {},
                'cost': 0.0, 'decision_ids': [], 'ms': None, 'success': False, 'error': str(e)[:200]}
