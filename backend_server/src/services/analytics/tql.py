"""TQL v1 — the run query language (TASK-42 §4.4).

Grammar::

    query   := clause (WS clause)*          -- whitespace = AND
    clause  := key ':' value
    key     := script | host | device | ui | env | status | milestone | label
             | since | until | flaky
    value   := bare | '"' ( [^"\\] | '\\' ["\\] )* '"'

* ``script:`` matches the persisted ``script_name`` exactly (case-insensitive);
  a single trailing ``*`` makes it a prefix match. ``*`` anywhere else is an error.
* ``host:`` / ``device:`` match ``script_results.host_name`` / ``device_name``
  exactly. ``device_name`` holds the host-local device id (e.g. ``device1``).
* ``ui:`` matches ``userinterface_name`` (case-insensitive); ``env:`` is one of
  ``dev | test | prod``.
* ``status:`` is ``passed | failed | unknown`` — the verdicts derivable from
  completed execution records. ``running | pending | skipped | cancelled`` are
  valid status words but are never persisted on a result row, so they are
  rejected rather than silently matching nothing.
* ``milestone:`` / ``label:`` take catalog NAMES; the server resolves them to
  ids within the caller's team (assignment is always by id).
* ``since:`` / ``until:`` take a UTC ISO date (``2026-10-01``), a UTC ISO
  datetime (``2026-10-01T08:00:00Z``) or a relative duration ``<n>d`` /
  ``<n>h`` up to 365 days, meaning "now minus n". At most one of each;
  ``since`` must be earlier than ``until``.
* ``flaky:true`` keeps attempts whose comparable identity is flaky in the window.
* ``tag:`` is deferred until a producer exists and is rejected.

Errors raise ``TqlError`` with a 0-based character position.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

KEYS = ('script', 'host', 'device', 'ui', 'env', 'status', 'milestone', 'label',
        'since', 'until', 'flaky')
STATUS_VALUES = ('passed', 'failed', 'unknown')
NON_PERSISTED_STATUSES = ('running', 'pending', 'skipped', 'cancelled')
ENV_VALUES = ('dev', 'test', 'prod')
MAX_QUERY_LENGTH = 1000
MAX_CLAUSES = 30
MAX_VALUE_LENGTH = 200
MAX_RELATIVE_DAYS = 365

_RELATIVE_RE = re.compile(r'^(\d{1,5})([dh])$')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_DATETIME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|\+00:00)$')
_KEY_RE = re.compile(r'[a-z]+')


class TqlError(ValueError):
    def __init__(self, message: str, position: int) -> None:
        super().__init__(message)
        self.message = message
        self.position = position

    def to_dict(self) -> Dict[str, Any]:
        return {'error': self.message, 'position': self.position}


@dataclass
class TqlClause:
    key: str
    value: str
    start: int
    end: int


@dataclass
class TqlFilter:
    scripts: List[str] = field(default_factory=list)
    hosts: List[str] = field(default_factory=list)
    devices: List[str] = field(default_factory=list)
    uis: List[str] = field(default_factory=list)
    envs: List[str] = field(default_factory=list)
    statuses: List[str] = field(default_factory=list)
    milestones: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    flaky: bool = False
    clauses: List[TqlClause] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out['since'] = self.since.isoformat() if self.since else None
        out['until'] = self.until.isoformat() if self.until else None
        return out


def _parse_time(raw: str, position: int, now: datetime) -> datetime:
    rel = _RELATIVE_RE.match(raw)
    if rel:
        amount, unit = int(rel.group(1)), rel.group(2)
        delta = timedelta(days=amount) if unit == 'd' else timedelta(hours=amount)
        if delta > timedelta(days=MAX_RELATIVE_DAYS):
            raise TqlError(f'relative duration {raw!r} exceeds {MAX_RELATIVE_DAYS} days', position)
        return now - delta
    if _DATE_RE.match(raw):
        try:
            return datetime.strptime(raw, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        except ValueError:
            raise TqlError(f'invalid date {raw!r}', position)
    if _DATETIME_RE.match(raw):
        try:
            return datetime.fromisoformat(raw.replace('Z', '+00:00')).astimezone(timezone.utc)
        except ValueError:
            raise TqlError(f'invalid datetime {raw!r}', position)
    raise TqlError(f'expected a UTC ISO date/datetime or a duration like 7d / 24h, got {raw!r}', position)


def _read_value(text: str, i: int) -> Tuple[str, int]:
    """Return (value, index after value). ``i`` points at the first value char."""
    n = len(text)
    if i >= n or text[i].isspace():
        raise TqlError('missing value after ":"', i)
    if text[i] == '"':
        j = i + 1
        buf: List[str] = []
        while j < n:
            ch = text[j]
            if ch == '\\':
                if j + 1 < n and text[j + 1] in '"\\':
                    buf.append(text[j + 1])
                    j += 2
                    continue
                raise TqlError('invalid escape in quoted value (only \\" and \\\\ are allowed)', j)
            if ch == '"':
                if j + 1 < n and not text[j + 1].isspace():
                    raise TqlError('a quoted value must be followed by whitespace', j + 1)
                return ''.join(buf), j + 1
            buf.append(ch)
            j += 1
        raise TqlError('unterminated quoted value', i)
    j = i
    while j < n and not text[j].isspace():
        if text[j] == '"':
            raise TqlError('unexpected quote inside an unquoted value', j)
        j += 1
    return text[i:j], j


def parse(query: Optional[str], *, now: Optional[datetime] = None) -> TqlFilter:
    text = query or ''
    if len(text) > MAX_QUERY_LENGTH:
        raise TqlError(f'query longer than {MAX_QUERY_LENGTH} characters', MAX_QUERY_LENGTH)
    current = now or datetime.now(timezone.utc)
    result = TqlFilter()
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        start = i
        match = _KEY_RE.match(text, i)
        if not match or match.end() >= n or text[match.end()] != ':':
            raise TqlError('expected key:value', start)
        key = match.group(0)
        if key == 'tag':
            raise TqlError('tag: is not supported yet', start)
        if key not in KEYS:
            raise TqlError(f'unknown key {key!r}; allowed: {", ".join(KEYS)}', start)
        value_start = match.end() + 1
        value, i = _read_value(text, value_start)
        if not value.strip():
            raise TqlError(f'empty value for {key}:', value_start)
        if len(value) > MAX_VALUE_LENGTH:
            raise TqlError(f'value longer than {MAX_VALUE_LENGTH} characters', value_start)
        if len(result.clauses) >= MAX_CLAUSES:
            raise TqlError(f'more than {MAX_CLAUSES} clauses', start)
        _apply(result, key, value, value_start, current)
        result.clauses.append(TqlClause(key=key, value=value, start=start, end=i))
    if result.since and result.until and result.since >= result.until:
        since_clause = next(c for c in result.clauses if c.key == 'since')
        raise TqlError('reversed range: since must be earlier than until', since_clause.start)
    return result


def _apply(result: TqlFilter, key: str, value: str, position: int, now: datetime) -> None:
    if key == 'script':
        if '*' in value[:-1]:
            raise TqlError('only a single trailing * is allowed in script:', position)
        if value == '*':
            raise TqlError('script:* needs a prefix', position)
        result.scripts.append(value)
    elif key == 'host':
        result.hosts.append(value)
    elif key == 'device':
        result.devices.append(value)
    elif key == 'ui':
        result.uis.append(value.lower())
    elif key == 'env':
        if value not in ENV_VALUES:
            raise TqlError(f'env must be one of {", ".join(ENV_VALUES)}', position)
        result.envs.append(value)
    elif key == 'status':
        lowered = value.lower()
        if lowered in NON_PERSISTED_STATUSES:
            raise TqlError(f'status:{lowered} is never recorded on a completed result; '
                           f'use one of {", ".join(STATUS_VALUES)}', position)
        if lowered not in STATUS_VALUES:
            raise TqlError(f'status must be one of {", ".join(STATUS_VALUES)}', position)
        result.statuses.append(lowered)
    elif key == 'milestone':
        result.milestones.append(value)
    elif key == 'label':
        result.labels.append(value)
    elif key in ('since', 'until'):
        if getattr(result, key) is not None:
            raise TqlError(f'{key}: may appear only once', position)
        setattr(result, key, _parse_time(value, position, now))
    elif key == 'flaky':
        if value != 'true':
            raise TqlError('flaky only accepts true', position)
        result.flaky = True
