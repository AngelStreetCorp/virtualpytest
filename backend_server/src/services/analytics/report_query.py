"""Report query model shared by ``POST /server/run-management/query``, its CSV
export and saved custom reports (TASK-42 §4.4).

A report definition is::

    {"filter": {"schema_version": 1, "tql": "<TQL v1>"},
     "columns": ["script_name", "status", ...],
     "chart": {"type": "status_by_day" | "status_by_group" | "status_share",
               "group_by": "script_name" | "host_name" | "device_name"
                           | "userinterface_name" | "environment"},
     "sort": "started_at", "order": "desc", "include_discarded": false}

Only allowlisted columns, chart types, group-by fields and sort keys are
accepted; nothing is interpolated into SQL. Table rows, counters, chart points
and the CSV export all come from one ``rm_run_query`` call over the same
validated filter, so they agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend_server.src.services.analytics import tql
from backend_server.src.services.analytics.scope import RunScope
from shared.src.lib.database import run_quality_db
from shared.src.lib.database.run_rpc import get_supabase
from shared.src.lib.database.in_filter import chunked_in

SCHEMA_VERSION = 1
DEFAULT_WINDOW_DAYS = 30
MAX_SPAN_DAYS = 366
ALLOWED_COLUMNS = (
    'id', 'script_name', 'script_type', 'status', 'userinterface_name', 'environment',
    'host_name', 'device_name', 'started_at', 'completed_at', 'execution_time_ms', 'discard',
    'milestone', 'run_group', 'labels',
)
DEFAULT_COLUMNS = ('script_name', 'status', 'host_name', 'device_name', 'environment',
                   'started_at', 'execution_time_ms')
CHART_TYPES = ('none', 'status_by_day', 'status_by_group', 'status_share')
GROUP_BY_FIELDS = ('script_name', 'host_name', 'device_name', 'userinterface_name', 'environment')
ALLOWED_SORTS = ('started_at', 'script_name', 'execution_time_ms', 'status')
MAX_PAGE_SIZE = 500        # rm_run_query clamps p_limit to this
EXPORT_ROW_CAP = 5000      # CSV export pages the RPC up to this many rows
STATUS_KEYS = ('passed', 'failed', 'running', 'pending', 'skipped', 'cancelled', 'unknown')


class QueryError(ValueError):
    def __init__(self, message: str, position: Optional[int] = None, field: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.position = position
        self.field = field

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {'error': self.message}
        if self.position is not None:
            out['position'] = self.position
        if self.field is not None:
            out['field'] = self.field
        return out


@dataclass
class ReportDefinition:
    tql: str
    parsed: tql.TqlFilter
    columns: List[str]
    chart_type: str
    group_by: Optional[str]
    sort: str
    descending: bool
    include_discarded: bool

    @property
    def sql_chart(self) -> str:
        if self.chart_type == 'status_by_group':
            return f'group:{self.group_by}'
        return self.chart_type

    def chart_spec(self) -> Dict[str, Any]:
        spec: Dict[str, Any] = {'type': self.chart_type}
        if self.group_by:
            spec['group_by'] = self.group_by
        return spec

    def to_document(self) -> Dict[str, Any]:
        return {
            'filter': {'schema_version': SCHEMA_VERSION, 'tql': self.tql},
            'columns': list(self.columns),
            'chart': self.chart_spec(),
            'sort': self.sort,
            'order': 'desc' if self.descending else 'asc',
            'include_discarded': self.include_discarded,
        }


def validate_definition(doc: Any, *, now: Optional[datetime] = None) -> ReportDefinition:
    if not isinstance(doc, dict):
        raise QueryError('report definition must be an object')
    filter_doc = doc.get('filter')
    if not isinstance(filter_doc, dict):
        raise QueryError('filter must be an object {schema_version, tql}', field='filter')
    version = filter_doc.get('schema_version')
    if version != SCHEMA_VERSION:
        raise QueryError(f'unsupported filter schema_version {version!r}; expected {SCHEMA_VERSION}',
                         field='filter.schema_version')
    query_text = filter_doc.get('tql') or ''
    if not isinstance(query_text, str):
        raise QueryError('filter.tql must be a string', field='filter.tql')
    try:
        parsed = tql.parse(query_text, now=now)
    except tql.TqlError as e:
        raise QueryError(e.message, position=e.position, field='filter.tql')

    columns = doc.get('columns') or list(DEFAULT_COLUMNS)
    if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
        raise QueryError('columns must be a list of column names', field='columns')
    unknown = [c for c in columns if c not in ALLOWED_COLUMNS]
    if unknown:
        raise QueryError(f'unknown columns: {", ".join(unknown)}', field='columns')
    columns = list(dict.fromkeys(columns))

    chart = doc.get('chart') or {'type': 'none'}
    if not isinstance(chart, dict):
        raise QueryError('chart must be an object {type, group_by?}', field='chart')
    chart_type = chart.get('type') or 'none'
    if chart_type not in CHART_TYPES:
        raise QueryError(f'chart.type must be one of {", ".join(CHART_TYPES)}', field='chart.type')
    group_by = chart.get('group_by')
    if chart_type == 'status_by_group':
        group_by = group_by or 'script_name'
        if group_by not in GROUP_BY_FIELDS:
            raise QueryError(f'chart.group_by must be one of {", ".join(GROUP_BY_FIELDS)}',
                             field='chart.group_by')
    elif group_by is not None:
        raise QueryError('chart.group_by is only valid for status_by_group', field='chart.group_by')

    sort = doc.get('sort') or 'started_at'
    if sort not in ALLOWED_SORTS:
        raise QueryError(f'sort must be one of {", ".join(ALLOWED_SORTS)}', field='sort')
    order = doc.get('order') or 'desc'
    if order not in ('asc', 'desc'):
        raise QueryError("order must be 'asc' or 'desc'", field='order')
    include_discarded = doc.get('include_discarded', False)
    if not isinstance(include_discarded, bool):
        raise QueryError('include_discarded must be a boolean', field='include_discarded')
    return ReportDefinition(tql=query_text, parsed=parsed, columns=columns, chart_type=chart_type,
                            group_by=group_by, sort=sort, descending=order == 'desc',
                            include_discarded=include_discarded)


def resolve_window(parsed: tql.TqlFilter, now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    current = now or datetime.now(timezone.utc)
    until = parsed.until or current
    since = parsed.since or (until - timedelta(days=DEFAULT_WINDOW_DAYS))
    if since >= until:
        raise QueryError('reversed range: since must be earlier than until', field='tql')
    if until - since > timedelta(days=MAX_SPAN_DAYS):
        raise QueryError(f'time range longer than {MAX_SPAN_DAYS} days', field='tql')
    return since, until


def _resolve_names(table: str, team_id: str, names: List[str], kind: str) -> Optional[List[str]]:
    if not names:
        return None
    rows = (get_supabase().table(table).select('id, name')
            .eq('team_id', team_id).limit(1000).execute()).data or []
    by_name: Dict[str, List[str]] = {}
    for row in rows:
        by_name.setdefault(str(row.get('name') or '').strip().lower(), []).append(str(row['id']))
    ids: List[str] = []
    for name in names:
        matches = by_name.get(name.strip().lower())
        if not matches:
            raise QueryError(f'unknown {kind} {name!r}', field='tql')
        if len(matches) > 1:
            raise QueryError(f'{kind} name {name!r} is ambiguous', field='tql')
        ids.append(matches[0])
    return ids


def build_filters(team_id: str, parsed: tql.TqlFilter) -> Dict[str, Any]:
    return {
        'scripts': parsed.scripts or None,
        'hosts': parsed.hosts or None,
        'devices': parsed.devices or None,
        'uis': parsed.uis or None,
        'envs': parsed.envs or None,
        'statuses': parsed.statuses or None,
        'milestone_ids': _resolve_names('run_milestones', team_id, parsed.milestones, 'milestone'),
        'label_ids': _resolve_names('run_label_definitions', team_id, parsed.labels, 'label'),
        'flaky': parsed.flaky,
    }


def _governance_names(team_id: str, rows: List[Dict[str, Any]], columns: List[str]) -> Dict[str, Any]:
    """Resolve milestone / group / label names for one page of rows (bounded)."""
    supabase = get_supabase()
    names: Dict[str, Any] = {'milestone': {}, 'run_group': {}, 'labels': {}}
    if 'milestone' in columns:
        ids = sorted({str(r['milestone_id']) for r in rows if r.get('milestone_id')})
        if ids:
            for m in (supabase.table('run_milestones').select('id, name').eq('team_id', team_id)
                      .in_('id', ids).execute()).data or []:
                names['milestone'][str(m['id'])] = m.get('name')
    if 'run_group' in columns:
        ids = sorted({str(r['run_group_id']) for r in rows if r.get('run_group_id')})
        if ids:
            for g in (supabase.table('run_groups').select('id, name').eq('team_id', team_id)
                      .in_('id', ids).execute()).data or []:
                names['run_group'][str(g['id'])] = g.get('name')
    if 'labels' in columns and rows:
        links = chunked_in(
            lambda chunk: supabase.table('script_result_labels').select('script_result_id, run_label_id')
            .eq('team_id', team_id).in_('script_result_id', chunk),
            [str(r['id']) for r in rows])
        label_ids = sorted({str(link['run_label_id']) for link in links})
        label_names = {}
        if label_ids:
            for label in (supabase.table('run_label_definitions').select('id, name').eq('team_id', team_id)
                          .in_('id', label_ids).execute()).data or []:
                label_names[str(label['id'])] = label.get('name')
        for link in links:
            names['labels'].setdefault(str(link['script_result_id']), []).append(
                label_names.get(str(link['run_label_id'])))
    return names


def _project(team_id: str, rows: List[Dict[str, Any]], columns: List[str]) -> List[Dict[str, Any]]:
    names = _governance_names(team_id, rows, columns)
    out = []
    for row in rows:
        projected: Dict[str, Any] = {}
        for col in columns:
            if col == 'milestone':
                projected[col] = names['milestone'].get(str(row.get('milestone_id')))
            elif col == 'run_group':
                projected[col] = names['run_group'].get(str(row.get('run_group_id')))
            elif col == 'labels':
                projected[col] = ', '.join(sorted(n for n in names['labels'].get(str(row.get('id')), []) if n))
            elif col == 'id':
                projected[col] = str(row.get('id'))
            else:
                projected[col] = row.get(col)
        projected['script_result_id'] = str(row.get('id'))
        out.append(projected)
    return out


def _counts(raw: Optional[Dict[str, Any]], total: int) -> Dict[str, int]:
    counts = {key: 0 for key in STATUS_KEYS}
    for key in ('passed', 'failed', 'unknown'):
        counts[key] = int((raw or {}).get(key) or 0)
    counts['total'] = total
    return counts


def execute(scope: RunScope, definition: ReportDefinition, *, limit: int, offset: int,
            now: Optional[datetime] = None) -> Dict[str, Any]:
    since, until = resolve_window(definition.parsed, now)
    filters = build_filters(scope.team_id, definition.parsed)
    if scope.host_names:
        data = run_quality_db.run_query(
            scope.team_id, scope.host_names, scope.device_keys, since, until,
            filters=filters, sort=definition.sort, descending=definition.descending,
            limit=limit, offset=offset, chart=definition.sql_chart,
            include_discarded=definition.include_discarded,
        )
    else:
        data = {'total': 0, 'counts': {}, 'rows': [], 'series': []}
    total = int(data.get('total') or 0)
    return {
        'definition': definition.to_document(),
        'window': {'since': since.isoformat(), 'until': until.isoformat()},
        'scope': scope.describe(),
        'total': total,
        'counts': _counts(data.get('counts'), total),
        'chart': {**definition.chart_spec(), 'points': data.get('series') or []},
        'columns': definition.columns,
        'rows': _project(scope.team_id, list(data.get('rows') or []), definition.columns),
        'limit': limit,
        'offset': offset,
    }


def export_rows(scope: RunScope, definition: ReportDefinition, *, cap: Optional[int] = None,
                now: Optional[datetime] = None) -> Dict[str, Any]:
    """Rows for the CSV export: the same query paged in ``MAX_PAGE_SIZE`` steps
    (the RPC's own clamp) until ``cap`` rows or the end. One time window for
    every page. Returns ``{'columns', 'rows', 'total'}``; ``total`` is the
    matching row count, which may exceed ``cap``."""
    cap = EXPORT_ROW_CAP if cap is None else cap
    current = now or datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []
    total = 0
    columns = definition.columns
    while len(rows) < cap:
        limit = min(MAX_PAGE_SIZE, cap - len(rows))
        page = execute(scope, definition, limit=limit, offset=len(rows), now=current)
        total = page['total']
        columns = page['columns']
        rows.extend(page['rows'])
        if len(page['rows']) < limit or len(rows) >= total:
            break
    return {'columns': columns, 'rows': rows[:cap], 'total': total}
