"""Per-family label schemas of the AI Dataset review (TASK-27 step 4, moved here in step 4i).

The single definition of what a label looks like, used by the review routes
(``backend_server/server_training_samples_routes.py`` re-exports every name) and by the
step 4i teacher importer (``scripts/triage_batch.py``), which must validate an AI answer
exactly as the review route validates a human one without importing Flask.

Pure: no Flask, no DB, no network.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

# Visual faults only (step 4f): audio loss cannot be seen in a frame, so it is not a label.
AV_FAULT_TYPES = ('blackscreen', 'freeze', 'macroblocks')
# Explicit "there is no channel banner on this frame": both fields present and null.
NO_BANNER = {'channel_number': None, 'channel_name': None}
# 'content-type' (TASK-05): the flat screen taxonomy and the content categories of a playback
# screen. Same values as features/companion/lib/profiles.py (SCREENS, CATEGORIES); written out
# here because one feature never imports another.
CONTENT_SCREENS = ('home', 'menu', 'settings', 'live_tv', 'vod_playback', 'advertisement', 'loading',
                   'error_no_signal')
CONTENT_PLAYBACK_SCREENS = ('live_tv', 'vod_playback')
CONTENT_CATEGORIES = ('sport', 'movie', 'series', 'news', 'debate', 'documentary', 'music', 'kids', 'game_show',
                      'other')

# Label shape per family: what the page writes and what the label route accepts.
LABEL_SCHEMAS: Dict[str, Optional[Dict[str, Any]]] = {
    # node_id null + label = a screen not in the tree (step 4f). Step 4k: node_id/label are
    # the screen GROUP; the optional node / node_label / focus name the original node and
    # what is focused on it (null: nothing extra). Labels without them stay valid.
    'screen-id': {'fields': ['node_id', 'label', 'node', 'node_label', 'focus'],
                  'required': ['node_id', 'label']},
    # Step 4k: focused null = nothing is focused (fullscreen video, splash).
    'focus':     {'fields': ['focused'], 'required': ['focused']},
    # A numeric-zap run label carries only channel_number, so one field is enough.
    'banner':    {'fields': ['channel_number', 'channel_name'], 'required': []},
    'menu':      {'fields': ['items', 'selected'], 'required': ['items']},
    # null = no fault. Step 4g: a freeze strip answered "not a problem" also says whether
    # the screen is legitimately still (static_screen true: menu, radio, guide, pause) or
    # was moving (false: a detector false alarm). Optional, only with a null type, and
    # never compared with the model answer (training_samples.ANNOTATION_KEYS).
    'av-fault':  {'fields': ['incident_type', 'static_screen'], 'required': ['incident_type']},
    # Screen type + content category when playing (live-TV companion identify call).
    'content-type': {'fields': ['screen', 'category', 'subcategory'], 'required': ['screen']},
    'other':     None,  # free JSON
}

# Step 4k: the optional keys of a grouped screen-id label (core screen_groups.GROUP_KEYS).
GROUP_KEYS = ('node', 'node_label', 'focus')

# Step 4g: the three answers of a freeze strip (the fourth, "Can't tell", saves nothing).
STRIP_ANSWERS = (
    {'incident_type': 'freeze'},
    {'incident_type': None, 'static_screen': True},
    {'incident_type': None, 'static_screen': False},
)


def _text(value: Any) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip() != ''


def validate_label(family: str, label: Any) -> Optional[str]:
    """Return an error message, or None when ``label`` fits the family's schema."""
    if family not in LABEL_SCHEMAS:
        return f"unknown family '{family}'"
    if label is None:
        return 'ground_truth is required'
    schema = LABEL_SCHEMAS[family]
    if schema is None:
        return None
    if not isinstance(label, dict):
        return f"{family} label must be an object with {schema['fields']}"
    extra = sorted(set(label) - set(schema['fields']))
    if extra:
        return f"{family} label has unknown fields {extra}; allowed {schema['fields']}"
    missing = [k for k in schema['required'] if k not in label]
    if missing:
        return f"{family} label is missing {missing}"

    if family == 'screen-id':
        if label.get('node_id') is None:
            if not isinstance(label.get('label'), str) or not label['label'].strip():
                return 'screen-id not in the tree needs node_id null and a non-empty label'
        elif not all(_text(label.get(k)) for k in ('node_id', 'label')):
            return 'screen-id needs a non-empty node_id and label'
        if label.get('node_id') is None and any(k in label for k in GROUP_KEYS):
            return 'screen-id node / node_label / focus only go with a screen of the tree'
        for key in ('node', 'node_label'):
            if key in label and not _text(label[key]):
                return f'screen-id {key} must be non-empty text'
        if label.get('focus') is not None and not _text(label.get('focus')):
            return 'screen-id focus must be text, or null for nothing focused'
    elif family == 'focus':
        if label.get('focused') is not None and not _text(label.get('focused')):
            return 'focus needs the focused text, or null for nothing focused'
    elif family == 'banner':
        values = [label.get(k) for k in schema['fields']]
        if any(v is not None and not isinstance(v, (str, int)) for v in values):
            return 'banner fields must be text or null'
        if not any(_text(v) for v in values) and label != NO_BANNER:
            return 'banner needs channel_number or channel_name, or both null for no banner'
    elif family == 'menu':
        items = label.get('items')
        if not isinstance(items, list) or not items or not all(_text(i) for i in items):
            return 'menu needs a non-empty items list of text'
        selected = label.get('selected')
        if selected is not None and str(selected) not in [str(i) for i in items]:
            return 'menu selected must be null or one of items'
    elif family == 'content-type':
        if label.get('screen') not in CONTENT_SCREENS:
            return f"content-type screen must be one of {list(CONTENT_SCREENS)}"
        category = label.get('category')
        if category is not None and (category not in CONTENT_CATEGORIES
                                     or label['screen'] not in CONTENT_PLAYBACK_SCREENS):
            return f"content-type category must be null, or one of {list(CONTENT_CATEGORIES)} on a playback screen"
        if label.get('subcategory') is not None and (category is None or not _text(label['subcategory'])):
            return 'content-type subcategory needs a category'
    elif family == 'av-fault':
        kind = label.get('incident_type')
        if kind is not None and kind not in AV_FAULT_TYPES:
            return f"av-fault incident_type must be null or one of {list(AV_FAULT_TYPES)}"
        if 'static_screen' in label:
            if not isinstance(label['static_screen'], bool):
                return 'av-fault static_screen must be true or false'
            if kind is not None:
                return 'av-fault static_screen is only allowed with incident_type null'
    return None


def normalize_label(family: str, label: Any) -> Any:
    """A screen-not-in-the-tree label is stored trimmed and lowercased, so the suggestion
    list and the conflict check see one spelling. Step 4k: a focus text (``focused``, or a
    grouped ``screen-id``'s ``focus``) is trimmed; an empty ``focus`` means null."""
    if family == 'screen-id' and isinstance(label, dict) and label.get('node_id') is None \
            and isinstance(label.get('label'), str):
        return {'node_id': None, 'label': label['label'].strip().lower()}
    if family == 'screen-id' and isinstance(label, dict) and isinstance(label.get('focus'), str):
        return {**label, 'focus': label['focus'].strip() or None}
    if family == 'focus' and isinstance(label, dict) and isinstance(label.get('focused'), str):
        return {**label, 'focused': label['focused'].strip()}
    return label


def _parse_answer(answer: Any) -> Any:
    """Generic vision samples store ``{'content': '<raw model text>'}``: parse the JSON in it."""
    if isinstance(answer, dict) and set(answer) == {'content'} and isinstance(answer['content'], str):
        text = answer['content'].strip()
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return answer
    return answer


def _pick(items: Any, index: Any) -> Optional[str]:
    if isinstance(index, int) and not isinstance(index, bool) and isinstance(items, list) \
            and 0 <= index < len(items):
        return items[index]
    return None


def label_from_model_answer(family: str, model_answer: Any) -> Any:
    """Map a model answer onto the family's label schema, or None when it does not map."""
    answer = _parse_answer(model_answer)
    if answer is None:
        return None
    if LABEL_SCHEMAS.get(family) is None:
        return answer
    if not isinstance(answer, dict):
        return None
    if family == 'menu' and 'items' not in answer:
        # analyze_language_menu_ai shape: audio first, subtitles when there is no audio list.
        for items_key, index_key in (('audio_languages', 'selected_audio'),
                                     ('subtitle_languages', 'selected_subtitle')):
            items = answer.get(items_key)
            if isinstance(items, list) and items:
                answer = {'items': items, 'selected': _pick(items, answer.get(index_key))}
                break
        else:
            return None
    fields = LABEL_SCHEMAS[family]['fields']
    label = {k: answer.get(k) for k in fields if k in answer}
    if family == 'banner':
        label = {k: v for k, v in label.items() if _text(v)}
        if not label and any(k in answer for k in fields):
            # The model answered in banner shape but saw nothing: its answer is "no banner".
            return dict(NO_BANNER)
    return label if validate_label(family, label) is None else None


def is_strip(row: Optional[Dict[str, Any]]) -> bool:
    """A step-4g freeze strip: one JPEG holding several frames side by side."""
    answer = (row or {}).get('model_answer')
    return isinstance(answer, dict) and answer.get('evidence') == 'strip'


def is_failed_verification(row: Optional[Dict[str, Any]]) -> bool:
    """A step-4d ``screen-id`` frame on which a node verification failed (no label)."""
    answer = (row or {}).get('model_answer')
    return (row or {}).get('family') == 'screen-id' and isinstance(answer, dict) \
        and answer.get('verified') is False
