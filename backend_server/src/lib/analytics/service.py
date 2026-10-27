"""Query guardrails and declarative artifact composition for Atlas analytics."""

from __future__ import annotations

import difflib
import csv
import io
import json
import os
import re
import logging
from decimal import Decimal
from numbers import Number
from uuid import UUID
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor

from .catalog import ANALYTICS_SOURCES, ARTIFACT_PRESETS, Source

DEFAULT_HOURLY_SPAN_DAYS = 2  # a time axis without time_grain: up to this many days -> hour buckets, else day
MAX_ROWS = 500
MAX_OFFSET = 10000
MAX_CATEGORIES = 40
MAX_SERIES = 12
RADAR_MIN_CATEGORIES = 3
RADAR_MAX_CATEGORIES = 20
RADAR_MAX_SERIES = 8
MAX_CANVAS_PANELS = 6
STATEMENT_TIMEOUT = "15s"
ALLOWED_MARKS = {"radar", "line", "area", "bar", "stacked-bar", "pie", "scatter", "heatmap", "stat", "state-timeline", "table"}
TIME_GRAINS = ("hour", "day", "week", "month")
SCOPES = ("visible", "current_device")
EXPORT_FORMATS = ("csv", "json")
ELEVATED_ROLES = {"admin", "service"}
NUMERIC_TEXT = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalyticsContext:
    team_id: str
    user_id: str = ""
    user_email: str = ""
    user_role: str = "viewer"
    workspace_id: str = ""
    selected_server: str = ""
    selected_server_name: str = ""
    selected_server_hosts: Tuple[str, ...] = ()
    host_name: str = ""
    device_id: str = ""
    # Set only by a forwarding server that already resolved the current device in its own
    # registry (the server that runs the SQL may not know that device).
    device_name: str = ""
    # The conversation's current user interface (chat context); defaults a preset's required
    # userinterface_name filter.
    userinterface_name: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {**self.__dict__, "selected_server_hosts": list(self.selected_server_hosts)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AnalyticsContext":
        fields = {name: data.get(name) for name in cls.__dataclass_fields__ if data.get(name) is not None}
        fields.setdefault("team_id", "")
        fields["selected_server_hosts"] = tuple(str(h) for h in fields.get("selected_server_hosts") or ())
        return cls(**{k: (v if k == "selected_server_hosts" else str(v)) for k, v in fields.items()})


class AnalyticsValidationError(ValueError):
    pass


class RemoteAnalytics:
    """Runs the database half of analytics on a server that has the datasource.

    A backend server on another network (e.g. a Pi-hosted server) reaches the database only
    through the Supabase API, not with a direct read-only connection. It forwards the
    compiled request and its trusted context to the primary server, authenticated with the
    shared service key; rendering, comparison and export stay local.
    """

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    @classmethod
    def from_env(cls) -> Optional["RemoteAnalytics"]:
        """``ANALYTICS_FORWARD_URL``, else the public origin that serves ``SUPABASE_URL``."""
        api_key = (os.getenv("API_KEY") or "").strip()
        url = (os.getenv("ANALYTICS_FORWARD_URL") or "").strip()
        if not url:
            supabase = urlparse((os.getenv("SUPABASE_URL") or "").strip())
            if supabase.scheme in {"http", "https"} and supabase.hostname not in {None, "localhost", "127.0.0.1"}:
                url = f"{supabase.scheme}://{supabase.netloc}"
        return cls(url, api_key) if url and api_key else None

    def call(self, operation: str, payload: Mapping[str, Any]) -> Any:
        import requests
        response = requests.post(f"{self.base_url}/server/atlas-analytics/{operation}", json=payload,
                                 headers={"X-API-Key": self.api_key}, timeout=30)
        body = response.json() if response.content else {}
        if response.status_code in (400, 403) and body.get("error"):
            # The primary server's own refusal (validation, team scope); never driver details.
            raise AnalyticsValidationError(str(body["error"]))
        response.raise_for_status()
        return body["result"]


def _iso(value: Any, default: datetime) -> datetime:
    if not value:
        return default
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AnalyticsValidationError(f"Invalid ISO-8601 time: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _int(request: Mapping[str, Any], name: str, default: int) -> int:
    value = request.get(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsValidationError(f"{name} must be an integer") from exc


def _values(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return [value]


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def public_preset(name: str, preset: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "id": name, "title": preset["title"], "description": preset.get("description", ""),
        "source_id": preset["source"], "mark": preset["mark"], "dimensions": list(preset["dimensions"]),
        "metrics": list(preset["metrics"]), "required_filters": list(preset.get("required_filters", [])),
        "default_filters": dict(preset.get("default_filters") or {}), "time_grain": preset.get("time_grain"),
        "dashboard_ref": preset.get("dashboard_ref"), "dashboard_panel": preset.get("dashboard_panel"),
    }


def public_source(source: Source) -> Dict[str, Any]:
    return {
        "id": source.id, "title": source.title, "description": source.description, "family": source.family,
        "dimensions": {k: {"type": v.kind, "filterable": v.filterable, "unit": v.unit} for k, v in source.dimensions.items()},
        "metrics": {k: {"unit": v.unit, "type": v.kind} for k, v in source.metrics.items()},
        "time_bounded": bool(source.time_expression), "live": source.live,
        "required_role": source.required_role,
        "supports_current_device_scope": bool(source.host_expression and source.device_expression),
        "default_dimensions": list(source.default_dimensions), "default_metrics": list(source.default_metrics),
        "dashboard_refs": list(source.dashboard_refs),
        "artifact_presets": [name for name, preset in ARTIFACT_PRESETS.items() if preset["source"] == source.id],
    }


def _csv_cell(value: Any) -> str:
    """Serialize one cell; text that a spreadsheet would evaluate is neutralized."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Number):
        return str(value)
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True)
    else:
        text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not NUMERIC_TEXT.match(text):
        return "'" + text
    return text


# Every key a query/render/export/draft request may carry. Anything else is refused, so a
# typo cannot silently drop a filter (live: "filter" instead of "filters" charted all
# devices under a two-device title).
REQUEST_KEYS = frozenset({
    "source_id", "preset", "dimensions", "metrics", "filters", "scope", "time_grain", "from_time", "to_time",
    "time_range_days", "sort", "limit", "offset", "comparison", "mark", "category", "series", "title", "panels",
    "columns", "max_categories", "max_series", "flag_match_mode", "overflow", "rank_by", "format",
    "prefer_existing", "ttl_hours", "filter_origin",
})


def _unsupported_fields_message(source: "Source", unknown_dims, unknown_metrics, cap: int = 25) -> str:
    """Name the bad fields with a close match each, plus the source's valid dimensions and metrics."""
    valid = list(source.dimensions) + list(source.metrics)
    unknown = sorted(unknown_dims | unknown_metrics)
    close = []
    for name in unknown:
        match = difflib.get_close_matches(str(name), valid, n=1, cutoff=0.5)
        if match:
            close.append(f"'{name}' -> '{match[0]}'")

    def show(names):
        names = list(names)
        return ", ".join(names[:cap]) + (f", ... (+{len(names) - cap} more)" if len(names) > cap else "")

    return (f"Unsupported fields: {unknown}" + (f" (did you mean {'; '.join(close)}?)" if close else "")
            + f". Valid dimensions for {source.id}: [{show(source.dimensions)}]. "
              f"Valid metrics: [{show(source.metrics)}]")


NO_KPI_INTERFACE = "(no interface with KPI samples)"
IDENTITY_FILTERS = ("device_name", "device_id", "device", "host_name", "host")


def unmatched_identity_filters(source: "Source", filters: Any, data: Mapping[str, Any]) -> Dict[str, List[str]]:
    """Device/host filter values that matched no row. An empty result leaves every value unmatched; a
    non-empty one is checked only when the filtered field is in the output."""
    if not isinstance(filters, dict):
        return {}
    rows = data.get("rows") or []
    fields = data.get("fields") or []
    found: Dict[str, List[str]] = {}
    for name, raw in filters.items():
        if name not in IDENTITY_FILTERS or name not in source.dimensions:
            continue
        wanted = [str(value) for value in _values(raw) if value is not None]
        # A truncated result may hold the value past the row limit: only an empty result proves no match.
        if rows and (name not in fields or data.get("truncated")):
            continue
        present = {str(row.get(name)) for row in rows}
        missing = [value for value in wanted if value not in present]
        if missing:
            found[name] = missing
    return found


def check_request_keys(request: Mapping[str, Any]) -> None:
    unknown = sorted(key for key in request if key not in REQUEST_KEYS and not key.startswith("_context_"))
    if unknown:
        hints = {"filter": "filters", "dimension": "dimensions", "metric": "metrics", "source": "source_id",
                 "group_by": "dimensions", "where": "filters", "days": "time_range_days"}
        suggestion = "; ".join(f"use '{hints[key]}' instead of '{key}'" for key in unknown if key in hints)
        raise AnalyticsValidationError(f"Unknown parameter(s) {unknown}" + (f": {suggestion}" if suggestion else ""))


class Binder:
    """How a compiled query receives values and trusted bounds."""

    narrow_to_selected_server = True

    def bind(self, value: Any, cast: str) -> str:
        raise NotImplementedError

    def scope_arguments(self) -> str:
        raise NotImplementedError

    def time_bounds(self, from_time: datetime, to_time: datetime) -> Tuple[str, str]:
        raise NotImplementedError

    def filter_clause(self, name: str, expression: str, selected: Optional[List[Any]], match: str = "") -> Optional[str]:
        """A predicate that replaces the literal filter (a dashboard variable), or None to inline the values.

        ``expression`` is the filtered column; for the ``flags`` filter it is the alias of the run table."""
        return None

    def unfiltered_names(self) -> List[str]:
        """Filter names that get a predicate even when the request set no value (dashboard variables)."""
        return []


class PsycopgBinder(Binder):
    """Server-side execution: every value is a driver parameter."""

    def __init__(self, context: AnalyticsContext):
        self.context = context
        self.values: List[Any] = []

    def bind(self, value: Any, cast: str) -> str:
        self.values.append(value)
        return f"%s::{cast}"

    def scope_arguments(self) -> str:
        login = "admin" if self.context.user_role in ELEVATED_ROLES else ""
        return ", ".join(self.bind(value, "text") for value in (self.context.user_email, login, self.context.workspace_id))

    def time_bounds(self, from_time: datetime, to_time: datetime) -> Tuple[str, str]:
        return self.bind(from_time, "timestamptz"), self.bind(to_time, "timestamptz")


KPI_AVAILABILITY_CAP = 8
# What a Grafana draft needs from a panel once the service resolved it (preset expansion, defaulted
# userinterface, named devices, scope): the draft is built from exactly this, never re-resolved.
RESOLVED_KEYS = ("source_id", "dimensions", "metrics", "filters", "time_grain", "sort", "limit", "scope",
                 "flag_match_mode", "from_time", "to_time", "time_range_days", "mark", "title")
# Filters that name a device are the user's even when a canvas panel carries them (named devices, BUG-0355).
IDENTITY_FILTER_NAMES = ("device_name", "host_name")
PANEL_FILTERS_KEY = "_context_panel_filters"
PANEL_SCOPE_KEY = "_context_panel_scope"  # the panel's own scope (not the canvas-level one): not the user's, stays literal in a draft
# Where a resolved filter came from. Only "user" filters may become dashboard variable selections.
ORIGIN_USER, ORIGIN_PRESET, ORIGIN_DEFAULTED, ORIGIN_PANEL = "user", "preset_default", "defaulted", "panel"


class AnalyticsService:
    def __init__(self, dsn: Optional[str] = None, api_client: Any = None,
                 remote: Optional[RemoteAnalytics] = None):
        self.dsn = dsn or os.getenv("ANALYTICS_DB_URI") or os.getenv("SUPABASE_DB_URI")
        self.api = api_client
        self.remote = remote if remote is not None else (None if self.dsn else RemoteAnalytics.from_env())

    # ------------------------------------------------------------------ catalog
    def list_sources(self) -> List[Dict[str, Any]]:
        return [public_source(source) for source in ANALYTICS_SOURCES.values()]

    def list_presets(self) -> List[Dict[str, Any]]:
        return [public_preset(name, preset) for name, preset in ARTIFACT_PRESETS.items()]

    def describe_source(self, source_id: str) -> Dict[str, Any]:
        source = self._source(source_id)
        described = public_source(source)
        described["presets"] = [public_preset(name, ARTIFACT_PRESETS[name]) for name in described["artifact_presets"]]
        return described

    def _source(self, source_id: str) -> Source:
        try:
            return ANALYTICS_SOURCES[source_id]
        except KeyError as exc:
            valid = list(ANALYTICS_SOURCES)
            close = difflib.get_close_matches(str(source_id), valid, n=3, cutoff=0.5)
            raise AnalyticsValidationError(
                (f"Unknown analytics source: '{source_id}'" if source_id else "Missing analytics source_id")
                + (f" (did you mean {', '.join(close)}?)" if close else "")
                + f". Valid source ids: {valid}. Pass source_id or a preset") from exc

    def _preset(self, name: str) -> Dict[str, Any]:
        try:
            return dict(ARTIFACT_PRESETS[name])
        except KeyError as exc:
            raise AnalyticsValidationError(f"Unknown artifact preset: {name}") from exc

    def preset_request(self, request: Mapping[str, Any], context: Optional[AnalyticsContext] = None,
                       lenient: bool = False) -> Dict[str, Any]:
        """Expand a preset into a plain query/render request; caller values override defaults.

        With a ``context`` a missing ``userinterface_name`` is defaulted (see ``_default_userinterface``);
        ``lenient`` skips the required-filter check for callers that only read encoding fields."""
        return self._expand_preset(request, context, lenient)[0]

    def _expand_preset(self, request: Mapping[str, Any], context: Optional[AnalyticsContext] = None,
                       lenient: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Like ``preset_request`` but also returns the filters the service defaulted (name -> value/note)."""
        preset = self._preset(str(request.get("preset") or ""))
        filters = dict(preset.get("default_filters") or {})
        incoming = request.get("filters") or {}
        if not isinstance(incoming, dict):
            raise AnalyticsValidationError("filters must be an object")
        filters.update(incoming)
        missing = [name for name in preset.get("required_filters", []) if not filters.get(name)]
        defaulted: Dict[str, Any] = {}
        if missing == ["userinterface_name"] and context is not None and not lenient:
            value, note = self._default_userinterface(preset, request, filters, context)
            filters["userinterface_name"] = value
            defaulted = {"userinterface_name": value, "note": note}
            missing = []
        if missing and not lenient:
            # A bare error here made the model stop and ask the user (live, 2026-10-04: "Which
            # userinterface would you like?"). Hand it the way forward instead.
            raise AnalyticsValidationError(
                f"Missing preset filters: {missing}. Do not ask the user for them. Either pass a value "
                f"(list the choices with query_analytics_data(source_id='{preset['source']}', dimensions={missing}))"
                f" or build this panel without the preset from source_id='{preset['source']}', "
                f"dimensions={list(preset['dimensions'])}, metrics={list(preset['metrics'])} across everything visible.")
        expanded = {"limit": MAX_ROWS}
        expanded.update({key: value for key, value in preset.items()
                         if key in {"time_grain", "sort", "limit", "time_range_days", "category", "series",
                                    "max_categories", "max_series", "overflow", "rank_by"}})
        expanded.update({key: value for key, value in request.items() if value not in (None, "", [], {})})
        expanded.update({"source_id": preset["source"], "dimensions": list(preset["dimensions"]),
                         "metrics": list(preset["metrics"]), "filters": filters,
                         "mark": str(request.get("mark") or preset["mark"]),
                         "title": str(request.get("title") or preset["title"])})
        return expanded, defaulted

    def _default_userinterface(self, preset: Mapping[str, Any], request: Mapping[str, Any],
                               filters: Mapping[str, Any], context: AnalyticsContext) -> Tuple[str, str]:
        """The interface a KPI preset runs on when none was given: the conversation's current one, else the
        one with the most samples in the request's scope and time range (same query path, so team/scope/
        server narrowing and forwarding to the data server apply). KPIs are only comparable within one
        interface, so the choice is disclosed, never silent."""
        if context.userinterface_name:
            return (context.userinterface_name,
                    f"Interface: {context.userinterface_name} (the conversation's current interface); "
                    "ask for another interface to change")
        source = self._source(str(preset["source"]))
        pick = {"source_id": source.id, "dimensions": ["userinterface_name"], "metrics": ["sample_count"],
                "filters": {k: v for k, v in filters.items() if k != "userinterface_name"},
                "sort": [{"field": "sample_count", "direction": "desc"}], "limit": 1}
        pick.update({k: request[k] for k in ("scope", "from_time", "to_time", "time_range_days")
                     if request.get(k) not in (None, "", [], {})})
        if preset.get("time_range_days") and "time_range_days" not in pick and "from_time" not in pick:
            pick["time_range_days"] = preset["time_range_days"]
        rows = self._run_query(pick, context, source).get("rows") or []
        name = str(rows[0].get("userinterface_name") or "") if rows else ""
        if not name:
            return (NO_KPI_INTERFACE,
                    "No user interface has KPI samples in this scope and time range, so nothing matched")
        return name, f"Interface: {name} (most KPI samples in scope); ask for another interface to change"

    def _selected_device_note(self, context: AnalyticsContext) -> str:
        host, _, name = self._current_device(context)
        return f"Limited to your selected device {name} ({host})" if name else f"Limited to your selected device ({host})"

    # ------------------------------------------------------------------ query
    def _current_device(self, context: AnalyticsContext) -> Tuple[str, str, str]:
        """Resolve the caller's selected device (host, id, name) from the live registry."""
        if not context.host_name or not context.device_id:
            raise AnalyticsValidationError(
                "No current device is selected in this conversation. Do not ask the user which devices: "
                "retry with scope='visible' (every device this user can see) and say that scope in the answer")
        if context.device_name:
            return context.host_name, context.device_id, context.device_name
        if not self.api:
            raise AnalyticsValidationError("Live device registry is unavailable to resolve the current device")
        result = self.api.get("/server/system/getAllHosts", params={"include_actions": "false"})
        for host in (result.get("hosts", []) if isinstance(result, dict) else []):
            if str(host.get("host_name") or "") != context.host_name:
                continue
            for device in host.get("devices", []):
                if str(device.get("device_id") or "") == context.device_id:
                    return context.host_name, context.device_id, str(device.get("device_name") or "")
        raise AnalyticsValidationError(
            "The current device is not registered on the selected server. Do not ask the user which devices: "
            "retry with scope='visible' (every device this user can see) and say that scope in the answer")

    @staticmethod
    def _effective_grain(source: "Source", request: Mapping[str, Any], dimensions: List[str],
                         metrics: List[str]) -> Tuple[Optional[str], bool]:
        """The requested time_grain, or one derived from the time range when metrics are grouped by a time
        dimension without a grain (live: a line chart returned one raw row per incident, each count 1)."""
        grain = request.get("time_grain")
        if grain not in (None, ""):
            if grain not in TIME_GRAINS:
                raise AnalyticsValidationError(f"time_grain must be one of {list(TIME_GRAINS)}")
            return grain, False
        if not metrics or not any(source.dimensions[name].kind == "time" for name in dimensions if name in source.dimensions):
            return None, False
        days = max(1, min(_int(request, "time_range_days", 30), 3650))
        to_time = _iso(request.get("to_time"), datetime.now(timezone.utc))
        from_time = _iso(request.get("from_time"), to_time - timedelta(days=days))
        span = to_time - from_time
        return ("hour" if span <= timedelta(days=DEFAULT_HOURLY_SPAN_DAYS) else "day"), True

    def _grain_for_request(self, source: "Source", request: Mapping[str, Any]) -> Tuple[Optional[str], bool]:
        dimensions = list(request.get("dimensions") if request.get("dimensions") is not None else source.default_dimensions)
        metrics = list(request.get("metrics") if request.get("metrics") is not None else source.default_metrics)
        return self._effective_grain(source, request, dimensions, metrics)

    def build_query(self, request: Mapping[str, Any], context: AnalyticsContext) -> Tuple[str, List[Any], List[str]]:
        """Compile a request to parameterized SQL for psycopg (values never enter the SQL text)."""
        binder = PsycopgBinder(context)
        sql, fields = self.compile(request, context, binder)
        return sql, binder.values, fields

    def compile(self, request: Mapping[str, Any], context: AnalyticsContext, binder: "Binder") -> Tuple[str, List[str]]:
        """Single compiler for every dialect; the binder decides how values reach the SQL."""
        source = self._source(str(request.get("source_id") or ""))
        if source.live:
            raise AnalyticsValidationError("live_system_status uses the live status adapter, not SQL")
        if not context.team_id:
            raise AnalyticsValidationError("Authenticated team context is required")
        if source.required_role == "admin" and context.user_role not in ELEVATED_ROLES:
            raise AnalyticsValidationError(f"{source.id} is limited to administrators")

        dimensions = list(request.get("dimensions") if request.get("dimensions") is not None else source.default_dimensions)
        metrics = list(request.get("metrics") if request.get("metrics") is not None else source.default_metrics)
        if not dimensions and not metrics:
            raise AnalyticsValidationError("At least one dimension or metric is required")
        unknown_dims = set(dimensions) - set(source.dimensions)
        unknown_metrics = set(metrics) - set(source.metrics)
        if unknown_dims or unknown_metrics:
            raise AnalyticsValidationError(_unsupported_fields_message(source, unknown_dims, unknown_metrics))
        if len(set(dimensions + metrics)) != len(dimensions + metrics):
            raise AnalyticsValidationError("Fields must not repeat")

        grain, _defaulted = self._effective_grain(source, request, dimensions, metrics)

        def dim_expr(name: str) -> str:
            field = source.dimensions[name]
            if grain and field.kind == "time":
                return f"date_trunc('{grain}', {field.expression})"
            return field.expression

        # Values are bound in SQL text order: CTEs, then WHERE clauses, then the page.
        ctes: List[str] = []
        clauses: List[str] = list(source.base_predicates)

        # Device ceiling: the same grafana_device_scope as the dashboards, evaluated once.
        if source.host_expression:
            ctes.append(f"ads AS MATERIALIZED (SELECT device_key FROM grafana_device_scope({binder.scope_arguments()}))")

        if source.time_expression:
            days = max(1, min(_int(request, "time_range_days", 30), 3650))
            now = datetime.now(timezone.utc)
            to_time = _iso(request.get("to_time"), now)
            from_time = _iso(request.get("from_time"), to_time - timedelta(days=days))
            if from_time >= to_time:
                raise AnalyticsValidationError("from_time must be before to_time")
            range_from, range_to = binder.time_bounds(from_time, to_time)
            ctes.append(f"b AS (SELECT {range_from} AS range_from, {range_to} AS range_to)")
            clauses.append(source.time_predicate or f"{source.time_expression} >= b.range_from AND {source.time_expression} <= b.range_to")

        if source.team_expression:
            clauses.append(f"{source.team_expression} = {binder.bind(context.team_id, 'uuid')}")

        filters = request.get("filters") or {}
        if not isinstance(filters, dict):
            raise AnalyticsValidationError("filters must be an object")
        for name, raw in filters.items():
            if source.id in {"execution_metrics", "kpi_measurements"} and name == "flags":
                selected = [str(value) for value in _values(raw)]
                if not selected or len(selected) > 30:
                    raise AnalyticsValidationError("Flag filter needs 1 to 30 values")
                bound = binder.filter_clause("flags", "er", selected, str(request.get("flag_match_mode") or "AND").upper())
                if bound:
                    clauses.append(bound)
                    continue
                operator = "@>" if str(request.get("flag_match_mode") or "AND").upper() == "AND" else "&&"
                clauses.append(
                    "EXISTS (SELECT 1 FROM device_flags df WHERE df.host_name = er.host_name "
                    "AND df.device_name = er.device_name AND "
                    "EXISTS (SELECT 1 FROM ads WHERE ads.device_key = '*' OR ads.device_key = df.host_name || ':' || df.device_id) "
                    f"AND df.flags {operator} {binder.bind(selected, 'text[]')})"
                )
                continue
            field = source.dimensions.get(name)
            if not field or not field.filterable:
                raise AnalyticsValidationError(f"Unsupported filter: {name}")
            selected = _values(raw)
            if not selected or len(selected) > 100:
                raise AnalyticsValidationError(f"Filter {name} needs 1 to 100 values")
            if any(isinstance(value, (dict, list)) or value is None for value in selected):
                raise AnalyticsValidationError(f"Filter {name} accepts scalar values only")
            if field.kind == "boolean":
                selected = [{"true": True, "false": False}.get(value.lower(), value) if isinstance(value, str) else value
                            for value in selected]
                if not all(isinstance(value, bool) for value in selected):
                    raise AnalyticsValidationError(f"Filter {name} accepts true/false only")
                clauses.append(f"{field.expression} = ANY({binder.bind(selected, 'boolean[]')})")
            elif field.kind == "time":
                raise AnalyticsValidationError(f"Use from_time/to_time to bound {name}")
            elif (bound := binder.filter_clause(name, field.expression, [str(v) for v in selected])):
                clauses.append(bound)
            else:
                clauses.append(f"({field.expression})::text = ANY({binder.bind([str(v) for v in selected], 'text[]')})")

        # Dashboard variables apply to every panel whose source has the column, filtered or not.
        for name in binder.unfiltered_names():
            if name in filters:
                continue
            if name == "flags":
                if source.id in {"execution_metrics", "kpi_measurements"} and (bound := binder.filter_clause("flags", "er", None, "OR")):
                    clauses.append(bound)
                continue
            field = source.dimensions.get(name)
            if field and field.filterable and field.expression and field.kind not in ("time", "boolean") \
                    and (bound := binder.filter_clause(name, field.expression, None)):
                clauses.append(bound)

        scope = str(request.get("scope") or "visible")
        if scope not in SCOPES:
            raise AnalyticsValidationError(f"scope must be one of {list(SCOPES)}")
        if scope == "current_device":
            if not (source.host_expression and source.device_expression):
                raise AnalyticsValidationError(f"{source.id} has no device dimension for the current device")
            host, device_id, device_name = self._current_device(context)
            device_value = device_id if source.device_key_kind == "id" else device_name
            if not device_value:
                raise AnalyticsValidationError("The current device has no name in the live registry")
            clauses.append(f"{source.host_expression} = {binder.bind(host, 'text')} "
                           f"AND {source.device_expression} = {binder.bind(device_value, 'text')}")

        if source.host_expression:
            if context.selected_server and binder.narrow_to_selected_server:
                hosts = list(context.selected_server_hosts) or ["__no_hosts__"]
                clauses.append(f"{source.host_expression} = ANY({binder.bind(hosts, 'text[]')})")
            if source.device_expression:
                key = f"{source.host_expression} || ':' || {source.device_expression}"
                clauses.append(f"EXISTS (SELECT 1 FROM ads WHERE ads.device_key = '*' OR ads.device_key = {key})")
            else:
                clauses.append(
                    "EXISTS (SELECT 1 FROM ads WHERE ads.device_key = '*' "
                    f"OR split_part(ads.device_key, ':', 1) = {source.host_expression})"
                )
        if source.server_expression and context.selected_server_name and binder.narrow_to_selected_server:
            clauses.append(f"{source.server_expression} = {binder.bind(context.selected_server_name, 'text')}")

        select = [f"{dim_expr(name)} AS \"{name}\"" for name in dimensions]
        select += [f"{source.metrics[name].expression} AS \"{name}\"" for name in metrics]
        sql = ("WITH " + ", ".join(ctes) + " " if ctes else "") + f"SELECT {', '.join(select)} FROM {source.relation}"
        if source.time_expression:
            sql += " CROSS JOIN b"
        if clauses:
            sql += " WHERE " + " AND ".join(f"({clause})" for clause in clauses)
        if metrics and dimensions:
            sql += " GROUP BY " + ", ".join(dim_expr(name) for name in dimensions)

        sort = request.get("sort") or []
        if not isinstance(sort, list):
            raise AnalyticsValidationError("sort must be a list")
        order_parts = []
        aliases = set(dimensions + metrics)
        for item in sort[:3]:
            name = str(item.get("field") or "") if isinstance(item, dict) else ""
            direction = str(item.get("direction") or "asc").lower() if isinstance(item, dict) else "asc"
            if name not in aliases or direction not in {"asc", "desc"}:
                raise AnalyticsValidationError("Invalid sort field or direction")
            order_parts.append(f'"{name}" {direction.upper()} NULLS LAST')
        if order_parts:
            sql += " ORDER BY " + ", ".join(order_parts)
        limit = max(1, min(_int(request, "limit", 100), MAX_ROWS))
        offset = max(0, min(_int(request, "offset", 0), MAX_OFFSET))
        # One row past the page reveals truncation without a second COUNT query.
        sql += f" LIMIT {binder.bind(limit + 1, 'int')} OFFSET {binder.bind(offset, 'int')}"
        return sql, dimensions + metrics

    def query(self, request: Mapping[str, Any], context: AnalyticsContext) -> Dict[str, Any]:
        """Run the query, then disclose what the caller did not ask for: a defaulted time grain and
        identity filters (device/host) whose values matched no row."""
        check_request_keys(request)
        defaulted: Dict[str, Any] = {}
        if request.get("preset"):
            request, defaulted = self._expand_preset(request, context)
        source = self._source(str(request.get("source_id") or ""))
        data = self._run_query(request, context, source)
        if defaulted:
            data = {**data, "defaulted_filters": defaulted}
        grain, defaulted = self._grain_for_request(source, request)
        if defaulted and not data.get("time_grain"):
            data = {**data, "time_grain": grain, "time_grain_defaulted": True}
        unmatched = unmatched_identity_filters(source, request.get("filters"), data)
        if unmatched:
            data = {**data, "unmatched_filters": unmatched}
        if not data.get("rows") and source.id == "kpi_measurements" and not data.get("availability_note"):
            data = {**data, "availability_note": self._kpi_availability_note(request, context, source)}
        return data

    def _kpi_availability_note(self, request: Mapping[str, Any], context: AnalyticsContext, source: "Source") -> str:
        """What KPI data DOES exist in scope after an empty KPI result, so the model answers instead of
        guessing fields (live: 46 s and 12 queries to conclude 'no data'). One small query on the same
        path as the original (team/scope/server narrowing, forwarding); only run for an empty result."""
        filters = request.get("filters") or {}
        wanted = filters.get("userinterface_name")
        wanted = ", ".join(map(str, wanted)) if isinstance(wanted, list) else (str(wanted) if wanted else "")
        variants = filters.get("variant")
        variants = [str(v) for v in variants] if isinstance(variants, list) else ([str(variants)] if variants else [])
        probe = {"source_id": source.id, "dimensions": ["userinterface_name", "variant"], "metrics": ["sample_count"],
                 "filters": {k: v for k, v in filters.items() if k not in ("userinterface_name", "variant")},
                 "sort": [{"field": "sample_count", "direction": "desc"}], "limit": 200}
        probe.update({k: request[k] for k in ("scope", "from_time", "to_time", "time_range_days")
                      if request.get(k) not in (None, "", [], {})})
        try:
            rows = self._run_query(probe, context, source).get("rows") or []
        except Exception:
            return ""
        asked = f"userinterface '{wanted}'" if wanted else "this request"
        if variants:
            asked += f" (variants {', '.join(variants)})"
        head = f"No KPI samples for {asked} in the requested time range on this server's hosts. "
        if not rows:
            return head + "KPI data in scope: none at all -> tell the user and stop; do not query other sources"
        per_ui: Dict[str, int] = {}
        per_variant: Dict[str, set] = {}
        for row in rows:
            ui = str(row.get("userinterface_name") or "?")
            per_ui[ui] = per_ui.get(ui, 0) + int(row.get("sample_count") or 0)
            per_variant.setdefault(ui, set()).add(str(row.get("variant") or "?"))
        if wanted and wanted in per_ui:
            return (head + f"Interface '{wanted}' has data, but only for variants: "
                    f"{', '.join(sorted(per_variant[wanted])[:10])} -> tell the user and stop; do not retry with guessed fields")
        top = sorted(per_ui.items(), key=lambda kv: -kv[1])[:KPI_AVAILABILITY_CAP]
        more = len(per_ui) - len(top)
        return (head + "KPI data in scope exists for: " + ", ".join(f"{n} ({c} samples)" for n, c in top)
                + (f" and {more} more" if more > 0 else "")
                + " -> tell the user, offer these; do not retry with guessed fields")

    def _run_query(self, request: Mapping[str, Any], context: AnalyticsContext, source: "Source") -> Dict[str, Any]:
        logger.info(
            "analytics_query source=%s team=%s user=%s workspace=%s server=%s dimensions=%s metrics=%s",
            source.id, context.team_id, context.user_id, context.workspace_id,
            context.selected_server_name or context.selected_server,
            list(request.get("dimensions") or source.default_dimensions),
            list(request.get("metrics") or source.default_metrics),
        )
        if source.live:
            return self._live_status(source, request, context)
        if not self.dsn and self.remote:
            if str(request.get("scope") or "") == "current_device":
                host, device_id, device_name = self._current_device(context)
                context = AnalyticsContext(**{**context.__dict__, "device_name": device_name})
            payload = {"request": {k: v for k, v in request.items() if k != "preset"}, "context": context.as_dict()}
            return self.remote.call("query", payload)
        sql, values, fields = self.build_query(request, context)
        if not self.dsn:
            raise AnalyticsValidationError("Analytics datasource is not configured")
        limit = max(1, min(_int(request, "limit", 100), MAX_ROWS))
        with psycopg2.connect(self.dsn, connect_timeout=5) as connection:
            connection.set_session(readonly=True, autocommit=False)
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
                cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '20s'")
                cursor.execute(sql, values)
                rows = [{key: _json_value(value) for key, value in dict(row).items()} for row in cursor.fetchall()]
        truncated = len(rows) > limit
        rows = rows[:limit]
        return {"model": "analytics-tabular-v1", "source_id": source.id, "fields": fields, "rows": rows,
                "row_count": len(rows), "truncated": truncated,
                "units": self._units(source, fields), "time_grain": request.get("time_grain") or None}

    @staticmethod
    def _units(source: Source, fields: List[str]) -> Dict[str, Optional[str]]:
        units: Dict[str, Optional[str]] = {}
        for name in fields:
            item = source.metrics.get(name) or source.dimensions.get(name)
            units[name] = item.unit if item else None
        return units

    # ------------------------------------------------------------------ comparison
    def comparison_defaults(self, request: Mapping[str, Any], data: Mapping[str, Any]) -> Dict[str, str]:
        """Comparison fields implied by the chart: category, series, first numeric metric, a count."""
        expanded = self.preset_request(request, lenient=True) if request.get("preset") else request
        source = self._source(str(data.get("source_id") or ""))
        fields = list(data.get("fields") or [])
        dimensions = [f for f in fields if f in source.dimensions]
        numeric = [f for f in fields if f in source.metrics and source.metrics[f].kind == "number"]
        defaults = {"align_by": str(expanded.get("category") or (dimensions[0] if dimensions else "")),
                    "series_field": str(expanded.get("series") or (dimensions[1] if len(dimensions) > 1 else "")),
                    "metric": numeric[0] if numeric else ""}
        counts = [f for f in ("sample_count", "run_count", "test_count", "incident_count", "zap_count",
                              "device_count", "session_count") if f in fields]
        if counts:
            defaults["sample_metric"] = counts[0]
        return defaults

    def compare(self, data: Mapping[str, Any], config: Mapping[str, Any],
                defaults: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        """Align two series on a shared dimension and disclose deltas and samples.

        ``defaults`` (from ``comparison_defaults``) fill the fields the caller left out, so
        "compare v1 and v2" only needs baseline and candidate.
        """
        if not isinstance(config, dict):
            raise AnalyticsValidationError("comparison must be an object with baseline and candidate")
        config = {**(defaults or {}), **{k: v for k, v in config.items() if v not in (None, "")}}
        fields = list(data.get("fields") or [])
        axis = str(config.get("align_by") or (fields[0] if fields else ""))
        series_field = str(config.get("series_field") or "")
        metric = str(config.get("metric") or "")
        baseline = config.get("baseline")
        candidate = config.get("candidate")
        sample_metric = str(config.get("sample_metric") or "sample_count")
        if not axis or not series_field or not metric or baseline is None or candidate is None:
            raise AnalyticsValidationError("comparison requires align_by, series_field, metric, baseline and candidate")
        source = ANALYTICS_SOURCES.get(str(data.get("source_id") or ""))
        numeric = {name for name, item in (source.metrics.items() if source else ()) if item.kind == "number"}
        if source and metric not in numeric:
            raise AnalyticsValidationError(
                f"comparison metric must be a numeric metric of the result {sorted(numeric & set(fields))}; got {metric}")
        if not {axis, series_field, metric}.issubset(fields) or len({axis, series_field, metric}) != 3:
            raise AnalyticsValidationError(
                f"comparison align_by/series_field/metric must be distinct fields of the result {fields}; "
                f"got align_by={axis}, series_field={series_field}, metric={metric}")
        direction = str(config.get("direction") or "lower_is_better")
        direction_note = None
        if direction not in {"lower_is_better", "higher_is_better"}:
            # The metric decides the direction anyway; an unrecognised value is ignored, not an error.
            direction_note = f"unrecognised direction '{direction}' ignored; the metric's own direction is used"
            direction = "lower_is_better"
        # A timing that goes up or a rate that goes down is a regression whatever the caller
        # guessed (live: "higher_is_better" on KPI ms reported a 41% speed-up as a regression).
        preferred = source.metrics[metric].preferred if source and metric in source.metrics else None
        if preferred and direction != f"{preferred}_is_better":
            if config.get("direction") and not direction_note:
                direction_note = f"{metric} is {preferred}-is-better; requested {direction} was overridden"
            direction = f"{preferred}_is_better"
        threshold = config.get("regression_over_percent")
        if threshold is not None:
            try:
                threshold = float(threshold)
            except (TypeError, ValueError) as exc:
                raise AnalyticsValidationError("regression_over_percent must be a number") from exc
        indexed: Dict[Any, Dict[str, Mapping[str, Any]]] = {}
        for row in data.get("rows") or []:
            indexed.setdefault(row.get(axis), {})[str(row.get(series_field))] = row
        rows = []
        lower_is_better = direction == "lower_is_better"
        for key, by_series in indexed.items():
            base_row, candidate_row = by_series.get(str(baseline)), by_series.get(str(candidate))
            if base_row is None and candidate_row is None:
                continue
            base_value = base_row.get(metric) if base_row else None
            candidate_value = candidate_row.get(metric) if candidate_row else None
            delta = candidate_value - base_value if isinstance(base_value, Number) and isinstance(candidate_value, Number) else None
            percent_delta = (100.0 * delta / abs(base_value)) if delta is not None and base_value not in (None, 0) else None
            regression_percent = (percent_delta if lower_is_better else (-percent_delta if percent_delta is not None else None))
            missing = "baseline" if base_row is None else ("candidate" if candidate_row is None else None)
            # A one-sided row cannot be ranked as a regression, but it is never hidden.
            if threshold is not None and missing is None and (regression_percent is None or regression_percent <= threshold):
                continue
            rows.append({axis: key, "baseline": base_value, "candidate": candidate_value,
                         "delta": delta, "percent_delta": round(percent_delta, 2) if percent_delta is not None else None,
                         "regression": bool(regression_percent is not None and regression_percent > 0),
                         "baseline_samples": base_row.get(sample_metric) if base_row else 0,
                         "candidate_samples": candidate_row.get(sample_metric) if candidate_row else 0,
                         "missing": missing})
        if bool(config.get("rank", True)):
            sign = 1 if lower_is_better else -1
            rows.sort(key=lambda row: (row["percent_delta"] is None, -sign * (row["percent_delta"] or 0)))
        return {"model": "analytics-comparison-v1", "align_by": axis, "series_field": series_field,
                "metric": metric, "baseline": baseline, "candidate": candidate, "rows": rows,
                "direction": direction, "direction_note": direction_note, "regression_over_percent": threshold,
                "missing_policy": "explicit-null", "sample_metric": sample_metric}

    # ------------------------------------------------------------------ live status
    def _live_status(self, source: Source, request: Mapping[str, Any], context: AnalyticsContext) -> Dict[str, Any]:
        if not self.api:
            raise AnalyticsValidationError("Live status adapter is unavailable")
        filters = request.get("filters") or {}
        if not isinstance(filters, dict) or set(filters) - set(source.dimensions):
            raise AnalyticsValidationError("Unsupported live status filter")
        result = self.api.get("/server/system/getAllHosts", params={"include_actions": "false"})
        hosts = result.get("hosts", []) if isinstance(result, dict) else []
        host_filter = filters.get("host_name") or context.host_name or ""
        wanted_hosts = {str(value) for value in _values(host_filter) if value}
        wanted_device_ids = {str(value) for value in _values(filters.get("device_id")) if value}
        wanted_device_names = {str(value) for value in _values(filters.get("device_name")) if value}
        allowed_keys = self._allowed_device_keys(context)
        rows = []
        for host in hosts:
            host_name = str(host.get("host_name") or "")
            if wanted_hosts and host_name not in wanted_hosts:
                continue
            if context.selected_server and host_name not in set(context.selected_server_hosts):
                continue
            for device in host.get("devices", []):
                device_id = str(device.get("device_id") or "")
                device_name = str(device.get("device_name") or "")
                if wanted_device_ids and device_id not in wanted_device_ids:
                    continue
                if wanted_device_names and device_name not in wanted_device_names:
                    continue
                if "*" not in allowed_keys and not ({f"{host_name}:{device_id}", f"{host_name}:{device_name}"} & allowed_keys):
                    continue
                rows.append({"host_name": host_name, "host_status": host.get("status"),
                             "device_id": device.get("device_id"), "device_name": device.get("device_name"),
                             "device_model": device.get("device_model"), "device_status": device.get("status")})
        for field in ("host_status", "device_model", "device_status"):
            selected = {str(value) for value in _values(filters.get(field)) if value}
            if selected:
                rows = [row for row in rows if str(row.get(field)) in selected]
        fields = list(source.dimensions)
        return {"model": "analytics-tabular-v1", "source_id": source.id, "fields": fields,
                "rows": rows[:MAX_ROWS], "row_count": min(len(rows), MAX_ROWS), "truncated": len(rows) > MAX_ROWS,
                "units": {name: None for name in fields}, "time_grain": None}

    def allowed_device_keys(self, context: AnalyticsContext) -> set[str]:
        return self._allowed_device_keys(context)

    def _allowed_device_keys(self, context: AnalyticsContext) -> set[str]:
        if context.user_role in ELEVATED_ROLES:
            return {"*"}
        if not self.dsn and self.remote:
            return set(self.remote.call("device-scope", {"context": context.as_dict()}))
        if not self.dsn:
            raise AnalyticsValidationError("Analytics datasource is required to authorize live device scope")
        with psycopg2.connect(self.dsn, connect_timeout=5) as connection:
            connection.set_session(readonly=True, autocommit=False)
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute(
                    "SELECT device_key FROM grafana_device_scope(%s, %s, %s)",
                    [context.user_email, "", context.workspace_id],
                )
                return {str(row[0]) for row in cursor.fetchall()}

    # ------------------------------------------------------------------ export
    def export(self, request: Mapping[str, Any], context: AnalyticsContext) -> Dict[str, Any]:
        """Serialize a bounded normalized result (and its comparison) as CSV or JSON text."""
        fmt = str(request.get("format") or "csv").lower()
        if fmt not in EXPORT_FORMATS:
            raise AnalyticsValidationError(f"format must be one of {list(EXPORT_FORMATS)}")
        data = self.query(request, context)
        comparison = (self.compare(data, request["comparison"], self.comparison_defaults(request, data))
                      if request.get("comparison") else None)
        name = str(request.get("preset") or data["source_id"])
        if fmt == "json":
            payload = {"schema": "analytics-export-v1", "data": data}
            if comparison:
                payload["comparison"] = comparison
            return {"format": "json", "filename": f"{name}.json", "mime_type": "application/json",
                    "content": json.dumps(payload, indent=2, sort_keys=True), "row_count": data["row_count"],
                    "truncated": data["truncated"]}
        rows = comparison["rows"] if comparison else data["rows"]
        fields = ([comparison["align_by"], "baseline", "candidate", "delta", "percent_delta", "regression",
                   "baseline_samples", "candidate_samples", "missing"] if comparison else data["fields"])
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(fields)
        for row in rows:
            writer.writerow([_csv_cell(row.get(name)) for name in fields])
        return {"format": "csv", "filename": f"{name}.csv", "mime_type": "text/csv",
                "content": buffer.getvalue(), "row_count": len(rows), "truncated": data["truncated"]}

    # ------------------------------------------------------------------ resolved requests (Grafana drafts)
    @staticmethod
    def merge_canvas_panel(shared: Mapping[str, Any], panel: Mapping[str, Any]) -> Dict[str, Any]:
        """A canvas panel with the canvas-level values merged in (what render and drafts both run).

        ``_context_panel_filters`` records the filters only this panel asked for, so their origin survives
        the merge: canvas-level filters are the user's for the whole dashboard, panel ones are the panel's."""
        merged = {**{k: v for k, v in shared.items() if k != "filters"}, **panel}
        if shared.get("filters") or panel.get("filters"):
            merged["filters"] = {**(shared.get("filters") or {}), **(panel.get("filters") or {})}
        own = [name for name in (panel.get("filters") or {})
               if name not in (shared.get("filters") or {}) and name not in IDENTITY_FILTER_NAMES]
        if own:
            merged[PANEL_FILTERS_KEY] = own
        if panel.get("scope") and panel.get("scope") != shared.get("scope"):
            merged[PANEL_SCOPE_KEY] = True
        return merged

    @staticmethod
    def filter_origins(request: Mapping[str, Any], defaulted: Optional[Mapping[str, Any]] = None) -> Dict[str, str]:
        """Origin of every filter of a (merged) request: user, preset_default, defaulted or panel."""
        preset = ARTIFACT_PRESETS.get(str(request.get("preset") or "")) or {}
        explicit = request.get("filters") or {}
        own = set(request.get(PANEL_FILTERS_KEY) or [])
        origins: Dict[str, str] = {}
        for name in explicit:
            origins[name] = ORIGIN_PANEL if name in own else ORIGIN_USER
        for name in (defaulted or {}):
            if name != "note" and name not in origins:
                origins[name] = ORIGIN_DEFAULTED
        for name in (preset.get("default_filters") or {}):
            origins.setdefault(name, ORIGIN_PRESET)
        return origins

    @classmethod
    def resolved_request(cls, request: Mapping[str, Any], query_request: Mapping[str, Any],
                         defaulted: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """The effective panel request a render ran: presets expanded, filters defaulted.

        ``filter_origin`` lists the filters that are NOT the user's (preset defaults, defaulted
        interface, panel-only filters); a Grafana draft keeps those literal in their panel."""
        kept = {key: query_request[key] for key in RESOLVED_KEYS if query_request.get(key) not in (None, "", [], {})}
        if request.get("preset"):
            kept["preset"] = request["preset"]  # lets the draft still point at a maintained panel
        origins = cls.filter_origins(request, defaulted)
        literal = {name: origin for name, origin in origins.items()
                   if origin != ORIGIN_USER and name in (kept.get("filters") or {})}
        if kept.get("scope") == "current_device" and request.get(PANEL_SCOPE_KEY):
            literal["scope"] = ORIGIN_PANEL  # a draft keeps this panel's own current-device scope literal (BUG-0410)
        if literal:
            kept["filter_origin"] = literal
        return kept

    def resolve_draft_request(self, request: Mapping[str, Any], context: AnalyticsContext
                              ) -> Tuple[Dict[str, Any], AnalyticsContext]:
        """Resolve a draft request the way ``render`` would, on THIS server: presets expanded, the KPI
        interface defaulted, shared filters merged into each panel, and the current device resolved
        into the returned context (``device_name``). The result needs no registry or context lookups
        elsewhere, so a server that only pushes (the primary, for a Pi's forward) builds the same SQL."""
        check_request_keys(request)
        panels = request.get("panels")
        shared = {key: request[key] for key in ("from_time", "to_time", "time_range_days", "filters", "scope")
                  if request.get(key) not in (None, "", {}, [])}
        leaves = []
        for panel in (panels if panels is not None else [None]):
            if panel is not None and (not isinstance(panel, dict) or panel.get("panels") is not None):
                raise AnalyticsValidationError("Each panel must be an object and canvases cannot nest")
            merged = self.merge_canvas_panel(shared, panel) if panel is not None else dict(request)
            defaulted: Dict[str, Any] = {}
            if merged.get("preset"):
                query_request, defaulted = self._expand_preset(merged, context)
            else:
                query_request = dict(merged)
            leaves.append(self.resolved_request(merged, query_request, defaulted))
        context = self.resolve_current_device(leaves, context)
        extras = {k: request[k] for k in ("title", "ttl_hours", "prefer_existing") if request.get(k) is not None}
        if panels is None:
            return {**leaves[0], **extras}, context
        return {**extras, "panels": leaves}, context

    def resolve_current_device(self, leaves: List[Mapping[str, Any]], context: AnalyticsContext) -> AnalyticsContext:
        """Fill ``device_name`` from the live registry when a panel runs on the current device."""
        if context.device_name or not any(leaf.get("scope") == "current_device" for leaf in leaves):
            return context
        _, _, name = self._current_device(context)
        return replace(context, device_name=name)

    # ------------------------------------------------------------------ render
    def render(self, request: Mapping[str, Any], context: AnalyticsContext) -> Dict[str, Any]:
        check_request_keys(request)
        panels = request.get("panels")
        if panels is not None:
            if not isinstance(panels, list) or not 1 <= len(panels) <= MAX_CANVAS_PANELS:
                raise AnalyticsValidationError(f"panels must contain between 1 and {MAX_CANVAS_PANELS} artifact requests")
            children = []
            shared = {key: request[key] for key in ("from_time", "to_time", "time_range_days", "filters", "scope")
                      if request.get(key) not in (None, "", {}, [])}
            for index, panel in enumerate(panels, 1):
                if not isinstance(panel, dict) or panel.get("panels") is not None:
                    raise AnalyticsValidationError("Nested canvases are not supported")
                label = f"Panel {index}" + (f" '{panel['title']}'" if panel.get("title") else "")
                merged = self.merge_canvas_panel(shared, panel)
                try:
                    children.append(self.render(merged, context)["content_data"]["artifact_spec"])
                except AnalyticsValidationError as exc:
                    raise AnalyticsValidationError(f"{label}: {exc}") from exc
            title = str(request.get("title") or "Analytics canvas")
            columns = max(1, min(_int(request, "columns", min(len(children), 2)), 3))
            grammar = {"schema": "vpt-artifact/v1", "kind": "canvas", "title": title,
                       "layout": {"columns": columns}, "panels": children}
            return {"content_type": "report-chart", "title": title,
                    "content_data": {"chart_type": "canvas", "artifact_spec": grammar}}
        preset_name = str(request.get("preset") or "")
        query_request, defaulted_filters = (self._expand_preset(request, context) if preset_name else (dict(request), {}))
        preset = ARTIFACT_PRESETS[preset_name] if preset_name else {}
        mark = str(query_request.get("mark") or "table")
        title = str(query_request.get("title") or "Analytics")
        if mark not in ALLOWED_MARKS:
            raise AnalyticsValidationError(f"Unsupported mark: {mark}")
        source = self._source(str(query_request.get("source_id") or ""))
        data = self.query({k: v for k, v in query_request.items() if k != "preset"}, context)
        comparison = (self.compare(data, request["comparison"], self.comparison_defaults(query_request, data))
                      if request.get("comparison") else None)
        dimensions = [f for f in data["fields"] if f in source.dimensions]
        metrics = [f for f in data["fields"] if f in source.metrics]
        category = str(query_request.get("category") or (dimensions[0] if dimensions else ""))
        series = str(query_request.get("series") or (dimensions[1] if len(dimensions) > 1 and mark != "table" else ""))
        for name in (category, series):
            if name and name not in data["fields"]:
                raise AnalyticsValidationError(f"Encoding field {name} is not in the query output")
        values = [str(v) for v in dict.fromkeys(row.get(category) for row in data["rows"]) if v is not None] if category else []
        series_values = [str(v) for v in dict.fromkeys(row.get(series) for row in data["rows"]) if v is not None] if series else []
        max_categories = max(1, min(_int(query_request, "max_categories", MAX_CATEGORIES), MAX_CATEGORIES))
        max_series = max(1, min(_int(query_request, "max_series", MAX_SERIES), MAX_SERIES))
        fallback, reason, overflow = None, None, None
        time_axis = category in source.dimensions and source.dimensions[category].kind == "time"
        numeric = [name for name in metrics if source.metrics[name].kind == "number"]
        if mark == "radar" and len(values) > min(max_categories, RADAR_MAX_CATEGORIES) and query_request.get("overflow") == "top":
            # Declared reduction: keep the best-sampled categories, disclose the rest.
            rank_by = str(query_request.get("rank_by") or "")
            if rank_by not in data["fields"]:
                raise AnalyticsValidationError("overflow 'top' needs rank_by to be a selected metric")
            totals: Dict[str, float] = {}
            for row in data["rows"]:
                value = row.get(rank_by)
                totals[str(row.get(category))] = totals.get(str(row.get(category)), 0.0) + (value if isinstance(value, Number) else 0.0)
            keep = set(sorted(totals, key=lambda key: (-totals[key], key))[:min(max_categories, RADAR_MAX_CATEGORIES)])
            overflow = {"kept": len(keep), "omitted": len(values) - len(keep), "ranked_by": rank_by,
                        "omitted_categories": sorted(set(values) - keep)}
            data = {**data, "rows": [row for row in data["rows"] if str(row.get(category)) in keep]}
            data["row_count"] = len(data["rows"])
            values = [value for value in values if value in keep]
        if mark == "radar" and data["rows"]:
            radar_categories = min(max_categories, RADAR_MAX_CATEGORIES)
            radar_series = min(max_series, RADAR_MAX_SERIES)
            if len(values) < RADAR_MIN_CATEGORIES or len(values) > radar_categories or len(series_values) > radar_series:
                fallback = "bar" if len(values) <= max_categories and len(series_values) <= max_series else "table"
                reason = (f"radar needs {RADAR_MIN_CATEGORIES}-{radar_categories} categories and at most "
                          f"{radar_series} series; got {len(values)} categories and {len(series_values) or 1} series")
                mark = fallback
        if mark not in {"table", "stat"} and ((len(values) > max_categories and not time_axis) or len(series_values) > max_series):
            reason = (f"{len(values)} categories / {len(series_values) or 1} series exceed the readable "
                      f"{max_categories} / {max_series}")
            fallback, mark = "table", "table"
        grammar = {
            "schema": "vpt-artifact/v1", "kind": "visualization", "title": title, "mark": mark,
            "data": data, "encoding": {"x": category or None, "series": series or None,
                                       "y": numeric[0] if numeric else None,
                                       "tooltip": list(dict.fromkeys(metrics + dimensions)),
                                       "time_grain": data.get("time_grain")},
            "options": {"legend": bool(series), "missing": "gap", "max_categories": max_categories,
                        "max_series": max_series, "fallback_applied": fallback, "fallback_reason": reason,
                        "category_overflow": overflow,
                        "time_grain_note": (f"No time_grain was given; defaulted to '{data.get('time_grain')}' from the time range "
                                            "so rows aggregate per bucket" if data.get("time_grain_defaulted") else None),
                        "unmatched_filters": data.get("unmatched_filters") or None,
                        "defaulted_filters": ({k: v for k, v in defaulted_filters.items() if k != "note"} or None),
                        "defaulted_filters_note": defaulted_filters.get("note"),
                        "filters": dict(query_request.get("filters") or {}),
                        # The UI sends the selected server's hosts; say so, or a result limited to them
                        # (live: stb-<operator> KPIs live on another server's hosts) reads as "no data".
                        "availability_note": data.get("availability_note") or None,
                        "scope_note": (self._selected_device_note(context)
                                       if str(query_request.get("scope") or "") == "current_device" else
                                       f"Limited to the {len(context.selected_server_hosts)} host(s) of the selected "
                                       f"server{(' ' + context.selected_server_name) if context.selected_server_name else ''}"
                                       if context.selected_server and source.host_expression else None),
                        "unit": source.metrics[numeric[0]].unit if numeric else None,
                        "units": data.get("units") or {}},
            "provenance": {"source_id": source.id, "preset": preset_name or None,
                           "dashboard_ref": preset.get("dashboard_ref"),
                           # what the Grafana draft is built from (see resolved_request)
                           "resolved_request": self.resolved_request(request, query_request, defaulted_filters)},
        }
        if comparison:
            grammar["comparison"] = comparison
        return {"content_type": "data-table" if mark == "table" else "report-chart", "title": title,
                "content_data": {"chart_type": mark, "artifact_spec": grammar,
                                 "chart_data": self._legacy_chart_data(grammar),
                                 "columns": [{"field": f, "header": f.replace("_", " ").title()} for f in data["fields"]],
                                 "rows": data["rows"]}}

    @staticmethod
    def _legacy_chart_data(grammar: Mapping[str, Any]) -> Dict[str, Any]:
        data = grammar["data"]
        x, series, y = grammar["encoding"]["x"], grammar["encoding"]["series"], grammar["encoding"]["y"]
        if not x or not y:
            return {"rows": data["rows"]}
        categories = list(dict.fromkeys(str(row.get(x)) for row in data["rows"]))
        series_names = list(dict.fromkeys(str(row.get(series) if series else y) for row in data["rows"]))
        payload = []
        for name in series_names:
            by_category = {str(row.get(x)): row.get(y) for row in data["rows"] if str(row.get(series) if series else y) == name}
            payload.append({"name": name, "values": [by_category.get(category) for category in categories]})
        return {"categories": categories, "series": payload, "unit": grammar["options"].get("unit")}
