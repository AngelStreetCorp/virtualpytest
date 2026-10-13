"""Per-family answer comparators for TASK-27 scoring (step 5).

``compare(family, truth, parsed) -> (correct, detail)``. ``truth`` is a sample's
``ground_truth`` (label schema of the feature's routes); ``parsed`` is
``family_prompts.parse_answer(...)`` output (same shape) or None when the model's
answer could not be parsed, which always scores wrong. ``detail`` is a short human
reason, used in the result file and the report.

Pure: no Flask, no DB, no network.
"""
from __future__ import annotations

import re
import string
from typing import Any, Callable, Optional

Result = tuple[bool, str]


def _norm(value: Any) -> str:
    return str(value if value is not None else '').strip().lower()


def _present(value: Any) -> bool:
    return value is not None and _norm(value) != ''


def normalize_channel_name(value: Any) -> str:
    """Lowercase, drop punctuation and spaces, drop a trailing "hd": "ITV 2 HD" -> "itv2"."""
    text = _norm(value).translate(str.maketrans('', '', string.punctuation))
    text = re.sub(r'\s+', '', text)
    return re.sub(r'hd$', '', text) or text


def screen_id(truth: dict, parsed: Optional[dict]) -> Result:
    """Step 4k: correct when the **group** matches. A grouped truth holds the group in
    ``node_id`` / ``label`` (its ``node`` / ``focus`` are not compared here; the focus is the
    ``screen-id/focus`` sub-metric), and the prompt lists group names, so a parsed answer
    maps to a group node id too."""
    if parsed is None:
        return False, 'unparsed answer'
    t_id, p_id = truth.get('node_id'), parsed.get('node_id')
    t_label, p_label = _norm(truth.get('label')), _norm(parsed.get('label'))
    if t_id is not None:
        if p_id is not None:
            ok = str(t_id) == str(p_id)
            return ok, 'node_id match' if ok else f'expected {t_label}, got {p_label}'
        return False, f'expected {t_label}, got off-tree "{p_label}"'
    # Truth is a screen not in the tree.
    if p_id is not None:
        return False, f'expected off-tree "{t_label}", got {p_label}'
    ok = t_label == p_label
    return ok, 'off-tree label match' if ok else f'expected off-tree "{t_label}", got "{p_label}"'


def focus(truth: dict, parsed: Optional[dict]) -> Result:
    """Focused text, trimmed and lowercased. Step 4k: null is "nothing focused"; null vs
    null is correct, null vs a text (either way) is wrong."""
    if parsed is None:
        return False, 'unparsed answer'
    t, p = _norm(truth.get('focused')), _norm(parsed.get('focused'))
    show = lambda v: f'"{v}"' if v else 'nothing focused'  # noqa: E731
    return (t == p), ('match' if t == p else f'expected {show(t)}, got {show(p)}')


# Step 4k: a grouped screen-id row's focus is scored as its own sub-metric.
FOCUS_SUBMETRIC = 'screen-id/focus'


def screen_focus(truth: dict, parsed_focus: Optional[dict]) -> Result:
    """The ``screen-id/focus`` sub-metric: the ``focus`` of a grouped ``screen-id`` truth
    against a ``focus``-family answer (``{"focused": ...}``) on the same image. Only rows
    whose truth has a focus are scored (``family_prompts.focus_truth``)."""
    return focus({'focused': (truth or {}).get('focus')}, parsed_focus)


def banner(truth: dict, parsed: Optional[dict]) -> Result:
    if parsed is None:
        return False, 'unparsed answer'
    t_num, t_name = truth.get('channel_number'), truth.get('channel_name')
    p_num, p_name = parsed.get('channel_number'), parsed.get('channel_name')
    if not _present(t_num) and not _present(t_name):
        ok = not _present(p_num) and not _present(p_name)
        return ok, 'no banner, as expected' if ok else f'expected no banner, got {p_num or ""} {p_name or ""}'.strip()
    problems = []
    if _present(t_num) and _norm(t_num) != _norm(p_num):
        problems.append(f'number expected {_norm(t_num)}, got {_norm(p_num) or "-"}')
    if _present(t_name) and normalize_channel_name(t_name) != normalize_channel_name(p_name):
        problems.append(f'name expected {normalize_channel_name(t_name)}, got {normalize_channel_name(p_name) or "-"}')
    return (not problems), ('match' if not problems else '; '.join(problems))


def menu(truth: dict, parsed: Optional[dict]) -> Result:
    if parsed is None:
        return False, 'unparsed answer'
    # Exact (surrounding spaces aside): "English - AD" and "English" are different tracks.
    t_items = {str(i).strip() for i in truth.get('items') or []}
    p_items = {str(i).strip() for i in parsed.get('items') or []}
    problems = []
    if t_items != p_items:
        missing, extra = sorted(t_items - p_items), sorted(p_items - t_items)
        problems.append(f'items differ (missing {missing}, extra {extra})')
    t_sel, p_sel = truth.get('selected'), parsed.get('selected')
    if (str(t_sel).strip() if t_sel is not None else None) != (str(p_sel).strip() if p_sel is not None else None):
        problems.append(f'selected expected {truth.get("selected")!r}, got {parsed.get("selected")!r}')
    return (not problems), ('match' if not problems else '; '.join(problems))


def av_fault(truth: dict, parsed: Optional[dict]) -> Result:
    if parsed is None:
        return False, 'unparsed answer'
    t, p = truth.get('incident_type'), parsed.get('incident_type')
    return (t == p), ('match' if t == p else f'expected {t}, got {p}')


def content_type(truth: dict, parsed: Optional[dict]) -> Result:
    """The live-TV companion's ``content-type`` (2026-10-04, for the Langfuse verdicts): the
    screen and the category must match; ``subcategory`` is free text and is not compared."""
    if parsed is None:
        return False, 'unparsed answer'
    problems = []
    for key in ('screen', 'category'):
        t, p = truth.get(key), parsed.get(key)
        if (_norm(t) if t is not None else None) != (_norm(p) if p is not None else None):
            problems.append(f'{key} expected {t}, got {p}')
    return (not problems), ('match' if not problems else '; '.join(problems))


COMPARATORS: dict[str, Callable[[dict, Optional[dict]], Result]] = {
    'screen-id': screen_id,
    'focus': focus,
    'banner': banner,
    'menu': menu,
    'av-fault': av_fault,
    'content-type': content_type,
}


def compare(family: str, truth: dict, parsed: Optional[dict]) -> Result:
    if family not in COMPARATORS:
        raise ValueError(f"unknown family '{family}'")
    return COMPARATORS[family](truth or {}, parsed)


def confusion_key(family: str, value: Optional[dict]) -> str:
    """The readable class of a label for the confusion table (screen / focused text)."""
    if value is None:
        return '(unparsed)'
    if family == 'screen-id':
        label = _norm(value.get('label')) or '?'
        return label if value.get('node_id') is not None else f'off-tree:{label}'
    if family == 'focus':
        return _norm(value.get('focused')) or '(nothing focused)'
    return str(value)
