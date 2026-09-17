#!/usr/bin/env python3
"""Centralized per-execution UI dump traces for device (Android) scripts.

The device counterpart of dom_capture.py. "What was actually on screen?" is the question
behind almost every argument with a device test, and the answer belongs in an artifact you
open after the run rather than in a hundred lines of accessibility tree buried in
execution.txt. That is what Playwright does with its traces, and what dom_capture already
does for web scripts.

**Every dump is recorded.** If the agent asked the phone for its tree, that tree is in the
trace — including the repeats a polling verification produces, because "we looked eight times
and it never changed" is itself the answer to most questions about a stuck screen.

To keep that readable, a dump whose tree is byte-identical to the one before it is written as
a one-line back-reference instead of forty repeated lines. Nothing is dropped: every dump
still gets its own numbered entry and timestamp. Outcomes (what a click hit, whether a
verification passed) are appended to the entry they belong to rather than duplicating it.

State is process-global for the same reason it is in dom_capture: one script execution is
one process (ScriptExecutor._execute_script_subprocess spawns each script on its own), so
the report generator can pick the traces up without any plumbing through the executors.
Recording never raises — a trace is diagnostics, and must not fail a test step.

The phone controller keeps writing its own rolling file on the host as well; that one is
cumulative across runs and is what you read over SSH. This module holds only the sections
THIS execution produced, which is what belongs in this execution's report.
"""

import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Sequence

_LOG = '[@ui_dump_capture]'
# A long run with a lot of polling can dump hundreds of times. Identical trees collapse to a
# line each, so this only bites when the screen keeps genuinely changing — at which point the
# oldest entries are the least interesting. Nothing is silently lost: the file says how many
# were dropped and the host's own rolling copy still has them.
MAX_ENTRIES = 500

# A selector matches on the WHOLE label, so a trace that cuts the label short cannot answer the
# question it exists for. A YouTube feed card runs to about 180 characters
# ("<title> - <duration> - Go to channel <channel> - <views> - <age> - play video") and the
# duration everyone selects on sits in the middle of it. Generous, and marked when it does cut.
DESC_WIDTH = 200
TEXT_WIDTH = 34

_lock = threading.Lock()
_sections: List[str] = []
_dropped = 0
# The previous dump's body and the entry it was first seen in, so repeats collapse.
_last_body: str = ''
_last_index: int = 0


def _clip(value, width: int) -> str:
    """Quoted, and marked with an ellipsis when it had to be cut."""
    text = str(value or '')
    return repr(text) if len(text) <= width else repr(text[:width]) + '…'


def render_header(index: int, device_id: str, why: str, labelled: int, total: int) -> str:
    """The one line that identifies a dump: when, on what, why, and how much of it matters."""
    return ("\n=== dump %d | %s | %s | %s | %d labelled of %d nodes ===\n"
            % (index, time.strftime('%Y-%m-%d %H:%M:%S'), device_id, why, labelled, total))


def render_body(rows: Sequence[Dict[str, Any]], total: int) -> str:
    """The tree itself, carrying only what a selector can match on.

    Unlabelled layout nodes are dropped by the caller — nothing can select them, so they are
    noise — while `total` records how many there were, because "3 labelled of 210" is itself a
    finding (a screen still drawing).
    """
    if not total:
        return "  (empty tree - the window was still settling)\n"
    return ''.join(
        "  %-9s %-16s text=%-34s desc=%s\n" % (
            'clickable' if row.get('clickable') else '',
            str(row.get('class_name') or '').split('.')[-1][:16],
            _clip(row.get('text'), TEXT_WIDTH),
            _clip(row.get('content_desc'), DESC_WIDTH),
        )
        for row in rows
    )


def render_section(index: int, device_id: str, why: str,
                   rows: Sequence[Dict[str, Any]], total: int) -> str:
    """Header + body, for a caller writing its own file (the host's rolling copy)."""
    return render_header(index, device_id, why, len(rows), total) + render_body(rows, total)


def record(device_id: str, note: str, rows: Sequence[Dict[str, Any]], total: int) -> str:
    """Record one dump. Returns the rendered text (or the short form, when unchanged).

    A dump identical to the one before it collapses to a back-reference. A polling
    verification can dump twenty times in twenty seconds; twenty identical trees are one
    fact, and printing it twenty times buries the dumps that differ.
    """
    global _last_body, _last_index
    try:
        body = render_body(rows, total)
        with _lock:
            index = len(_sections) + 1
            unchanged = body == _last_body
            same_as = _last_index if unchanged else None
        header = render_header(index, device_id, note, len(rows), total)
        section = header + (f"  (identical to dump {same_as})\n" if unchanged else body)
        with _lock:
            _sections.append(section)
            _last_body, _last_index = body, (same_as if unchanged else index)
            _trim_locked()
        return section
    except Exception as e:  # pragma: no cover - diagnostics must never break a step
        print(f"{_LOG} could not render a dump trace: {e}")
        return ''


def _trim_locked() -> None:
    """Drop the oldest entries past MAX_ENTRIES. Caller holds the lock."""
    global _dropped
    excess = len(_sections) - MAX_ENTRIES
    if excess > 0:
        del _sections[:excess]
        _dropped += excess


def note(text: str) -> None:
    """Append a one-line outcome to the dump it belongs to, rather than repeating the tree."""
    if not text:
        return
    try:
        with _lock:
            if _sections:
                _sections[-1] = _sections[-1].rstrip('\n') + f"\n  -> {text}\n"
    except Exception as e:  # pragma: no cover
        print(f"{_LOG} could not annotate a dump trace: {e}")


def record_ui_dump(section: str) -> None:
    """Keep one rendered trace section for this execution's report."""
    if not section:
        return
    try:
        with _lock:
            _sections.append(section if section.endswith('\n') else section + '\n')
    except Exception as e:  # pragma: no cover - diagnostics must never break a step
        print(f"{_LOG} could not record a dump trace: {e}")


def get_ui_dump_count() -> int:
    with _lock:
        return len(_sections)


def get_ui_dump_file() -> str:
    """Write this execution's sections to one file and return its path ('' when there are none).

    One file rather than one per miss: reading three dumps side by side is how you spot that
    the screen never changed, and the report links one artifact instead of a list.
    """
    with _lock:
        sections = list(_sections)
    if not sections:
        return ''
    try:
        fd, path = tempfile.mkstemp(prefix='ui_dumps_', suffix='.txt')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            if _dropped:
                fh.write(f"# {_dropped} earlier dump(s) dropped - this file keeps the most "
                         f"recent {MAX_ENTRIES}. The host's ui_dumps.txt has them all.\n")
            fh.write(''.join(sections))
        return path
    except Exception as e:
        print(f"{_LOG} could not assemble the dump file: {e}")
        return ''


def reset_ui_dumps() -> None:
    global _last_body, _last_index, _dropped
    with _lock:
        _sections.clear()
        _last_body, _last_index, _dropped = '', 0, 0
