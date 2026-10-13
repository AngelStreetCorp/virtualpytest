"""CSV export with spreadsheet formula-injection protection (TASK-42 §3 Export).

A cell whose text starts with ``= + - @``, a tab or a carriage return is
prefixed with ``'`` so spreadsheet applications treat it as text. Quoting is
done by the ``csv`` module (RFC 4180). Numbers and booleans are written as-is
(a negative number is data, not a formula).
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Iterable, Sequence

FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def escape_cell(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def build_csv(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\r\n', quoting=csv.QUOTE_MINIMAL)
    writer.writerow([escape_cell(h) for h in headers])
    for row in rows:
        writer.writerow([escape_cell(v) for v in row])
    return buffer.getvalue()
