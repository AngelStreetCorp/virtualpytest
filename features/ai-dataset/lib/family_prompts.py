"""Per-family prompts and answer format for the TASK-27 eval and training (step 5).

One module is the single source of what a model is asked and what it must answer, so
scoring (step 5), export (step 6) and training (step 7) all use the same text:

- ``FAMILY_PROMPTS[family]``: the base prompt of each family. ``screen-id`` and
  ``av-fault`` are ``str.format`` templates (``{screen_list}`` / ``{evidence}``, doubled
  braces): always go through ``build_prompt``, never send ``FAMILY_PROMPTS`` as is.
- ``build_prompt(family, sample, context)``: the prompt for one sample.
- ``answer_to_text(family, ground_truth)``: the canonical JSON string a trained model
  should output for that truth (the training target).
- ``parse_answer(family, text, context=None)``: tolerant JSON extraction from model
  output, mapped onto the family's label schema (``LABEL_SCHEMAS`` in the feature's
  routes). Returns None when nothing usable is found.

Answer format per family (what ``parse_answer`` returns, i.e. the label shape):

``screen-id``  ``{"node_id": <tree node id or null>, "label": "<screen name>"}``.
    Node ids are tree UUIDs or ``node-<ms>`` ids, which no model can know or should
    learn, so **the model names the screen**: the prompt lists the tree's screen
    names (``context={'screen_labels': [...]}``) and the model answers
    ``{"label": "<name as listed>"}``, or ``{"node_id": null, "label": "<short name>"}``
    when the frame is none of them. ``parse_answer`` with the same context maps a
    listed name back to its ``node_id`` (exact after lowercase and strip); an unlisted
    name becomes ``{"node_id": null, "label": <lowercased name>}``. ``screen_labels``
    items are names or ``{"node_id", "label"}`` dicts. Scoring needs the dicts (the
    comparator matches ``node_id``); plain names are enough to build a prompt (export,
    training), where the ``node_id`` is not used. ``answer_to_text`` emits ``{"label": "home"}`` for an on-tree truth
    and ``{"node_id": null, "label": "popup"}`` for an off-tree one.
    **Step 4k:** the listed screens are **screen groups** (core ``screen_groups``): Home
    with any tab focused is ``home``, so ``screen_labels`` holds group names and group node
    ids. The prompt says the highlighted item is asked separately: a grouped label's
    ``focus`` is scored and trained with the ``focus`` prompt on the same image
    (``focus_truth``).
``focus``      ``{"focused": "<visible text of the focused element>"}``, or
    ``{"focused": null}`` when nothing is focused (step 4k: fullscreen video, splash).
``banner``     ``{"channel_number": ..., "channel_name": ...}``; ``{null, null}`` = no banner.
    The prompt **is** the runtime prompt (``ai_utils._create_banner_analysis_prompt``,
    used by ``analyze_channel_banner_ai``), verbatim, so the eval scores exactly what
    production asks. It requests eight fields (``banner_detected``, channel, programme,
    episode, times, confidence); labels only hold the channel number and name. So the
    training target is the runtime shape **restricted to what a label knows**:
    ``{"banner_detected": true, "channel_name": "ITV2", "channel_number": ""}``, empty
    strings for unknown fields as the runtime does. The runtime parser
    (``analyze_channel_banner_ai``) reads missing fields as empty, so a tuned model's
    answer still parses there, but it will not learn to fill programme/episode/time
    fields from these labels. Step 6/8 must know this difference.
``menu``       ``{"items": [...], "selected": "<item or null>"}``.
    The runtime menu prompt (``analyze_language_menu_ai``) is **not** reused: it asks for
    two lists (audio and subtitle languages) and selected *indexes*, while a label is
    one list and the selected *text*. ``parse_answer`` still accepts the runtime shape
    (audio list first, subtitles when there is no audio list), like the review page's
    proposed label.
``av-fault``   ``{"incident_type": "blackscreen" | "freeze" | "macroblocks" | null}``.
    A freeze sample (``model_answer.evidence == 'strip'``) is one image holding 2-3
    frames side by side with their relative times; the prompt says so.

Pure: no Flask, no DB, no network. Importing it imports ``shared.src.lib.utils.ai_utils``
(for the banner prompt), which needs ``cv2`` installed.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from shared.src.lib.utils.ai_utils import _create_banner_analysis_prompt

FAMILIES = ('screen-id', 'focus', 'banner', 'menu', 'av-fault')
AV_FAULT_TYPES = ('blackscreen', 'freeze', 'macroblocks')

_JSON_ONLY = 'Respond ONLY with the JSON object - no markdown, no explanation.'

FAMILY_PROMPTS: dict[str, str] = {
    'screen-id': (
        "This is a screenshot of a TV / set-top box user interface.\n"
        "Which screen of the app is shown? The known screens are:\n"
        "{screen_list}\n\n"
        "A screen stays the same screen whichever tab, tile or menu entry is highlighted on it: "
        "name the screen only (the highlighted item is asked separately).\n"
        "Answer with the screen name exactly as listed: {{\"label\": \"<screen name>\"}}\n"
        "If it is none of these, answer {{\"node_id\": null, \"label\": \"<short name e.g. popup>\"}} "
        "(for example popup, error / no signal, loading / black, dialog, tip).\n"
        f"{_JSON_ONLY}"
    ),
    'focus': (
        "This is a screenshot of a TV / set-top box user interface.\n"
        "At most one element has the focus (the highlighted tile, tab, button or menu entry "
        "that the remote's OK key would select). Give its visible text.\n"
        "Answer: {\"focused\": \"<text of the focused element>\"}\n"
        "If nothing is focused (fullscreen video, a splash or loading screen), answer "
        "{\"focused\": null}.\n"
        f"{_JSON_ONLY}"
    ),
    'banner': _create_banner_analysis_prompt(),
    'menu': (
        "This screenshot may show a menu (for example an audio, subtitle or language menu).\n"
        "List the menu's items top to bottom, exactly as displayed (keep descriptors such as "
        "\"AD\", \"Stereo\", \"Dolby\"), and the item that is currently selected or highlighted.\n"
        "Answer: {\"items\": [\"<item>\", ...], \"selected\": \"<item as listed, or null>\"}\n"
        "If there is no menu, answer {\"items\": [], \"selected\": null}.\n"
        f"{_JSON_ONLY}"
    ),
    'av-fault': (
        "{evidence}\n"
        "Is there a video fault? Choose one:\n"
        "- \"blackscreen\": the picture is black (or blank) where video should play\n"
        "- \"freeze\": the video is frozen, the picture does not move when it should\n"
        "- \"macroblocks\": blocky corruption / pixelation artefacts\n"
        "- null: no fault (normal video, or a screen that is legitimately still such as a menu, "
        "radio screen, guide or paused video)\n"
        "Answer: {{\"incident_type\": \"blackscreen\" | \"freeze\" | \"macroblocks\" | null}}\n"
        f"{_JSON_ONLY}"
    ),
}

_SINGLE_FRAME = "This is one frame captured from a TV / set-top box video output."
_STRIP = ("This image is a strip of {n} frames from the same TV / set-top box video output, "
          "placed side by side, oldest on the left. Each frame has its time relative to the first "
          "frame written on it ({times}). The footer gives the detector's measurement "
          "(\"frozen <seconds> s | diff <percent>%\": how long the picture seemed frozen and the "
          "largest pixel difference between compared frames). Compare the frames: if they are "
          "identical over that time while video should be playing, the video is frozen. A menu, "
          "guide, radio screen, paused video, promo carousel or loading page is a still screen, not "
          "moving video, even when it changes in steps between frames.")


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {}
        except ValueError:
            return {}
    return {}


def is_strip(sample: Optional[dict]) -> bool:
    """A freeze strip sample (step 4g): one image, several frames with their times."""
    return _as_dict((sample or {}).get('model_answer')).get('evidence') == 'strip'


def _fmt_time(value: Any) -> Optional[str]:
    try:
        return f"+{float(value):.1f} s"
    except (TypeError, ValueError):
        return None


def _screen_entries(context: Optional[dict]) -> list[dict]:
    """``context['screen_labels']`` as ``[{'node_id', 'label'}]`` (names or dicts), deduped."""
    out, seen = [], set()
    for item in (context or {}).get('screen_labels') or []:
        if isinstance(item, dict):
            label, node_id = str(item.get('label') or '').strip(), item.get('node_id')
        else:
            label, node_id = str(item or '').strip(), None
        if label and label.lower() not in seen:
            seen.add(label.lower())
            out.append({'node_id': node_id, 'label': label})
    return out


def focus_truth(ground_truth: Any) -> Optional[dict]:
    """Step 4k: the ``focus`` label of a grouped ``screen-id`` truth (``{"focused": <text>}``),
    or None when there is no focus question (the group's own node, a pre-4k label, a screen
    not in the tree)."""
    gt = _as_dict(ground_truth)
    if gt.get('node_id') is None or not _text(gt.get('focus')):
        return None
    return {'focused': str(gt['focus']).strip()}


def build_prompt(family: str, sample: Optional[dict] = None, context: Optional[dict] = None) -> str:
    """The prompt for one sample. ``screen-id`` needs ``context={'screen_labels': [...]}``."""
    if family not in FAMILY_PROMPTS:
        raise ValueError(f"unknown family '{family}'")
    template = FAMILY_PROMPTS[family]
    if family == 'screen-id':
        entries = _screen_entries(context)
        if not entries:
            raise ValueError("screen-id needs context={'screen_labels': [...]} (the tree's screen names)")
        return template.format(screen_list="\n".join(f"- {e['label']}" for e in entries))
    if family == 'av-fault':
        if is_strip(sample):
            frames = _as_dict(sample.get('model_answer')).get('frames') or []
            times = [t for t in (_fmt_time(f) for f in frames) if t]
            evidence = _STRIP.format(n=len(frames) or 'several',
                                     times=", ".join(times) if times else "e.g. +0.0 s, +15.0 s, +30.2 s")
        else:
            evidence = _SINGLE_FRAME
        return template.format(evidence=evidence)
    return template


# ---- training target -----------------------------------------------------------------

def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(', ', ': '))


def answer_to_text(family: str, ground_truth: dict) -> str:
    """The canonical JSON string a trained model should output for ``ground_truth``."""
    gt = _as_dict(ground_truth)
    if family == 'screen-id':
        label = str(gt.get('label') or '').strip()
        if gt.get('node_id') is None:
            return _dump({'node_id': None, 'label': label.lower()})
        return _dump({'label': label})
    if family == 'focus':
        # Step 4k: null = nothing focused.
        focused = gt.get('focused')
        return _dump({'focused': str(focused).strip() if _text(focused) else None})
    if family == 'banner':
        name, number = gt.get('channel_name'), gt.get('channel_number')
        detected = any(_text(v) for v in (name, number))
        return _dump({'banner_detected': detected,
                      'channel_name': str(name).strip() if _text(name) else '',
                      'channel_number': str(number).strip() if _text(number) else ''})
    if family == 'menu':
        return _dump({'items': list(gt.get('items') or []), 'selected': gt.get('selected')})
    if family == 'av-fault':
        return _dump({'incident_type': gt.get('incident_type')})
    raise ValueError(f"unknown family '{family}'")


# ---- parsing model output ------------------------------------------------------------

_FENCE_RE = re.compile(r'```(?:json)?\s*(.*?)```', re.S | re.I)
_THINK_RE = re.compile(r'<think>.*?</think>', re.S | re.I)


def _text(value: Any) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip() != ''


def _loads(candidate: str) -> Optional[dict]:
    candidate = candidate.strip()
    for attempt in (candidate, re.sub(r',\s*([}\]])', r'\1', candidate)):  # trailing commas
        try:
            value = json.loads(attempt)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def extract_json(text: Any) -> Optional[dict]:
    """First JSON object in model output: bare, fenced, or embedded in prose."""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str) or not text.strip():
        return None
    text = _THINK_RE.sub('', text)
    candidates = [m.group(1) for m in _FENCE_RE.finditer(text)] + [text]
    for candidate in candidates:
        found = _loads(candidate)
        if found is not None:
            return found
    # Balanced-brace scan for an object inside prose.
    for start in (i for i, ch in enumerate(text) if ch == '{'):
        depth, in_str, esc = 0, False, False
        for end in range(start, len(text)):
            ch = text[end]
            if in_str:
                esc = (ch == '\\') and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    found = _loads(text[start:end + 1])
                    if found is not None:
                        return found
                    break
    return None


def _pick(items: Any, index: Any) -> Optional[str]:
    if isinstance(index, int) and not isinstance(index, bool) and isinstance(items, list) \
            and 0 <= index < len(items):
        return items[index]
    return None


def parse_answer(family: str, text: Any, context: Optional[dict] = None) -> Optional[dict]:
    """Model output → the family's label shape, or None. Never raises.

    ``context`` is only used by ``screen-id`` (same ``screen_labels`` as the prompt) to
    map an answered screen name back to its ``node_id``.
    """
    try:
        answer = extract_json(text)
        if answer is None:
            return None
        return _PARSERS[family](answer, context)
    except Exception:
        return None


def _parse_screen(answer: dict, context: Optional[dict]) -> Optional[dict]:
    label = answer.get('label', answer.get('screen'))
    if not _text(label):
        return None
    label = str(label).strip()
    if 'node_id' in answer and answer['node_id'] is None:
        return {'node_id': None, 'label': label.lower()}
    for entry in _screen_entries(context):
        if entry['label'].lower() == label.lower():
            return {'node_id': entry['node_id'], 'label': entry['label']}
    node_id = answer.get('node_id')
    if _text(node_id):
        for entry in _screen_entries(context):
            if entry['node_id'] is not None and str(entry['node_id']) == str(node_id):
                return {'node_id': entry['node_id'], 'label': entry['label']}
    return {'node_id': None, 'label': label.lower()}


def _parse_focus(answer: dict, _context) -> Optional[dict]:
    value = answer.get('focused', answer.get('label'))
    if 'focused' in answer and (value is None or (isinstance(value, str)
                                                  and value.strip().lower() in ('', 'null', 'none'))):
        return {'focused': None}  # step 4k: nothing focused
    return {'focused': str(value).strip()} if _text(value) else None


def _parse_banner(answer: dict, _context) -> Optional[dict]:
    fields = ('channel_number', 'channel_name')
    if not any(k in answer for k in fields + ('banner_detected',)):
        return None
    label = {k: str(answer[k]).strip() for k in fields if _text(answer.get(k))}
    if not label:
        return {'channel_number': None, 'channel_name': None}
    return {'channel_number': label.get('channel_number'), 'channel_name': label.get('channel_name')}


def _parse_menu(answer: dict, _context) -> Optional[dict]:
    if 'items' not in answer:
        # analyze_language_menu_ai shape: audio first, subtitles when there is no audio list.
        for items_key, index_key in (('audio_languages', 'selected_audio'),
                                     ('subtitle_languages', 'selected_subtitle')):
            items = answer.get(items_key)
            if isinstance(items, list) and items:
                return {'items': [str(i) for i in items], 'selected': _pick(items, answer.get(index_key))}
        if answer.get('menu_detected') is False:
            return {'items': [], 'selected': None}
        return None
    items = answer.get('items')
    if not isinstance(items, list):
        return None
    selected = answer.get('selected')
    if isinstance(selected, int) and not isinstance(selected, bool):
        selected = _pick(items, selected)
    return {'items': [str(i).strip() for i in items if _text(i)],
            'selected': str(selected).strip() if _text(selected) else None}


def _parse_av_fault(answer: dict, _context) -> Optional[dict]:
    if 'incident_type' not in answer:
        return None
    kind = answer['incident_type']
    if kind is None or (isinstance(kind, str) and kind.strip().lower() in ('', 'null', 'none')):
        return {'incident_type': None}
    kind = str(kind).strip().lower().replace(' ', '')
    return {'incident_type': kind} if kind in AV_FAULT_TYPES else None


_PARSERS = {
    'screen-id': _parse_screen,
    'focus': _parse_focus,
    'banner': _parse_banner,
    'menu': _parse_menu,
    'av-fault': _parse_av_fault,
}
