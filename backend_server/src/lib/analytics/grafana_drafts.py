"""Ephemeral Grafana dashboard drafts compiled from the Atlas semantic catalog.

A draft is a file the user may review and promote by hand.  This module never talks
to Grafana, never writes outside its temporary root, and never touches the
maintained dashboard folder.  Panel SQL comes only from ``AnalyticsService.compile``
— the same catalog fragments and guardrails as Atlas queries — with values inlined
as validated literals and the viewer's device scope and time range left to Grafana.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .catalog import ANALYTICS_SOURCES, ARTIFACT_PRESETS
from .service import (
    ALLOWED_MARKS, AnalyticsContext, AnalyticsService, AnalyticsValidationError, Binder, TIME_GRAINS,
    check_request_keys, ORIGIN_PANEL, ORIGIN_USER,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DRAFT_ROOT = PROJECT_ROOT / "tmp" / "atlas-grafana"
MAINTAINED_DASHBOARDS = PROJECT_ROOT / "infra" / "monitoring" / "grafana" / "dashboards"
TEMPLATE_FILENAME = "template.json"
TEMPLATE_PATH = MAINTAINED_DASHBOARDS / TEMPLATE_FILENAME
TEMPLATE_MARKER = "__template"
DRAFT_SCHEMA = "atlas-grafana-draft/v1"
logger = logging.getLogger(__name__)
DATASOURCE = {"type": "grafana-postgresql-datasource", "uid": "supabase-postgres"}
DEFAULT_TTL_HOURS = 24
MAX_TTL_HOURS = 24 * 7
UID_PREFIX = "atlas-draft-"
REQUEST_ID = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")
PANEL_TYPES = {"timeseries", "barchart", "piechart", "stat", "table", "state-timeline"}
# Grafana has no core radar/heatmap-of-categories/scatter panel; plugins are not allowed.
MARK_TO_PANEL = {"line": "timeseries", "area": "timeseries", "bar": "barchart", "stacked-bar": "barchart",
                 "pie": "piechart", "stat": "stat", "table": "table", "state-timeline": "state-timeline",
                 "radar": "barchart", "heatmap": "table", "scatter": "table"}
WORKSPACE_VARIABLE_QUERY = (
    "SELECT __text, __value FROM (SELECT 0 AS o, 'None' AS __text, 'none' AS __value UNION ALL "
    "SELECT 1, name, id FROM grafana_user_workspaces(${__user.email:sqlstring}, ${__user.login:sqlstring})) w "
    "ORDER BY o, __text"
)
# Dashboard-level settings a draft takes from the template as they are.
TEMPLATE_COPIED_KEYS = ("timezone", "schemaVersion", "editable", "graphTooltip", "refresh", "annotations", "links",
                        "fiscalYearStartMonth", "timepicker", "weekStart", "preload")
DASHBOARD_KEYS = {"title", "uid", "tags", "time", "templating", "panels", "description", *TEMPLATE_COPIED_KEYS}
# Panel filter -> dashboard variable of the same meaning (names as declared by template.json).
FILTER_VARIABLES = {"host_name": "host", "device_name": "device_name", "userinterface_name": "user_interface",
                    "environment": "environment", "flags": "flag"}
FLAG_ALL_VALUE = "__ALL__"
# allValue of the template's other variables: All is this sentinel, never an expanded option list.
# Grafana inserts a custom allValue RAW (no quoting, unlike selected values), so the template stores it
# quoted: `$host` then becomes '__all' and the predicate reads '__all' IN ('__all'). Unquoted it read
# '__all' IN (__all) and every panel failed with: column "__all" does not exist (BUG-0385).
VARIABLE_ALL_VALUE = "__all"
VARIABLE_ALL_RAW = f"'{VARIABLE_ALL_VALUE}'"
# Panel style keys that depend on the metric, not on the house style.
BAR_LABEL_ROTATE_ABOVE = 6
BAR_LABEL_MAX_LENGTH = 18
STYLE_DROPPED_DEFAULTS = {"unit", "min", "max", "thresholds"}
DEFAULT_PANEL_HEIGHT = 9
SECRET_KEY = re.compile(r"password|secret|token|apikey|api_key|credential|basicauth|securejson", re.IGNORECASE)
WRITE_SQL = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|grant|revoke|truncate|copy|call|do|vacuum|"
    r"refresh|listen|notify|lock|set|reset|execute|prepare|comment|security|pg_sleep|dblink|lo_import)\b",
    re.IGNORECASE,
)
SAFE_TEXT = re.compile(r"^[^\x00-\x1f$\\]*$")


class GrafanaBinder(Binder):
    """Inline validated literals; scope and time range come from the viewer's Grafana session.

    A filter whose meaning matches a dashboard variable (``variables``: filter -> variable name) is
    emitted as that variable's predicate instead of a literal, and the value the user fixed is
    recorded in ``fixed`` so the dashboard can preselect it.  ``claimed`` holds values other panels
    already fixed: a variable has one value per dashboard, so a panel that disagrees stays literal.
    """

    narrow_to_selected_server = False

    def __init__(self, variables: Optional[Mapping[str, str]] = None, claimed: Optional[Mapping[str, List[str]]] = None,
                 literal: Optional[Iterable[str]] = None):
        # Filters that are not the user's (preset defaults, defaulted interface, panel-only): always inlined.
        self.literal = frozenset(literal or ())
        self.variables: Dict[str, str] = dict(variables or {})
        self.claimed: Dict[str, List[str]] = dict(claimed or {})
        self.fixed: Dict[str, List[str]] = {}
        self.bound: Dict[str, str] = {}

    def bind(self, value: Any, cast: str) -> str:
        return f"{self._literal(value)}::{cast}"

    def _literal(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, list):
            return "ARRAY[" + ", ".join(self._literal(item) for item in value) + "]"
        text = str(value)
        # `$` would be expanded by Grafana's variable interpolation inside the SQL text.
        if not SAFE_TEXT.match(text) or len(text) > 200:
            raise AnalyticsValidationError("Draft filter values cannot contain control characters, '$' or '\\'")
        return "'" + text.replace("'", "''") + "'"

    def scope_arguments(self) -> str:
        return "${__user.email:sqlstring}, ${__user.login:sqlstring}, ${workspace:sqlstring}"

    def time_bounds(self, from_time: datetime, to_time: datetime) -> Tuple[str, str]:
        return "$__timeFrom()::timestamptz", "$__timeTo()::timestamptz"

    def unfiltered_names(self) -> List[str]:
        return sorted(name for name in self.variables if name not in self.bound)  # stable: recompile order must match

    def filter_clause(self, name: str, expression: str, selected: Optional[List[Any]], match: str = "") -> Optional[str]:
        """``selected`` None = the request set no value: the predicate is still emitted so the dropdown works."""
        variable = self.variables.get(name)
        if not variable or (selected is not None and name in self.literal):
            return None
        if selected is not None:
            values = sorted({str(value) for value in selected})
            for value in values:
                self._literal(value)  # same character rules as inlined values: nothing Grafana would expand
            if name == "flags" and match != "OR" and len(values) > 1:
                return None  # the variable means "any of"; an all-of match cannot be a variable
            if variable in self.claimed and self.claimed[variable] != values:
                return None
            self.fixed[variable] = values
        self.bound[name] = variable
        if name == "flags":
            alias = expression
            return (f"'${{{variable}}}' = '{FLAG_ALL_VALUE}' OR EXISTS (SELECT 1 FROM device_flags df "
                    f"WHERE df.host_name = {alias}.host_name AND df.device_name = {alias}.device_name AND "
                    "EXISTS (SELECT 1 FROM ads WHERE ads.device_key = '*' OR ads.device_key = df.host_name || ':' || df.device_id) "
                    f"AND df.flags && string_to_array('${{{variable}:csv}}', ','))")
        return (f"'{VARIABLE_ALL_VALUE}' IN (${variable}) OR ({expression})::text IN (${variable}) "
                f"OR ({expression}) IS NULL")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_literals(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def _workspace_variable() -> Dict[str, Any]:
    return {
        "name": "workspace", "label": "Workspace", "type": "query", "datasource": dict(DATASOURCE),
        "query": WORKSPACE_VARIABLE_QUERY, "definition": WORKSPACE_VARIABLE_QUERY, "refresh": 1,
        "current": {"text": "None", "value": "none"}, "includeAll": False, "multi": False, "hide": 0,
    }


@dataclass(frozen=True)
class DashboardTemplate:
    """The house style a draft starts from: variables, time settings, styling and grid."""

    source: str  # "file" or "builtin"
    variables: Tuple[Dict[str, Any], ...]
    time: Dict[str, str]
    settings: Dict[str, Any]
    panel_styles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    panel_height: int = DEFAULT_PANEL_HEIGHT

    @property
    def variable_names(self) -> List[str]:
        return [str(v.get("name")) for v in self.variables]

    def filter_variables(self) -> Dict[str, str]:
        """Panel filters that have a variable of the same meaning in this template."""
        names = set(self.variable_names)
        return {name: variable for name, variable in FILTER_VARIABLES.items() if variable in names}


def builtin_template() -> DashboardTemplate:
    """Fallback skeleton (workspace variable only); used only when template.json is missing or invalid."""
    return DashboardTemplate(
        source="builtin", variables=(_workspace_variable(),), time={"from": "now-30d", "to": "now"},
        settings={"timezone": "browser", "schemaVersion": 41, "editable": True, "graphTooltip": 0, "refresh": "",
                  "annotations": {"list": []}, "links": []})


def _template_problems(raw: Any) -> List[str]:
    if not isinstance(raw, dict):
        return ["not a JSON object"]
    problems: List[str] = []
    if TEMPLATE_MARKER not in (raw.get("tags") or []):
        problems.append(f"missing the {TEMPLATE_MARKER} tag")
    variables = (raw.get("templating") or {}).get("list")
    names = [v.get("name") for v in variables] if isinstance(variables, list) and all(isinstance(v, dict) for v in variables) else []
    if not names or len(set(names)) != len(names):
        problems.append("templating.list must hold uniquely named variables")
    elif "workspace" not in names:
        problems.append("the workspace variable is required")
    if not isinstance(raw.get("time"), dict) or not {"from", "to"} <= set(raw["time"]):
        problems.append("time.from/time.to are required")
    if not isinstance(raw.get("schemaVersion"), int):
        problems.append("schemaVersion is required")

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if SECRET_KEY.search(str(key)):
                    problems.append(f"credential-like key at {path}.{key}")
                if key == "datasource" and value != DATASOURCE:
                    problems.append(f"datasource at {path} is not the configured VirtualPyTest datasource")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
    walk(raw, "template")
    return problems


def parse_template(raw: Mapping[str, Any]) -> DashboardTemplate:
    """Build a template from a validated template.json document."""
    styles: Dict[str, Dict[str, Any]] = {}
    height = DEFAULT_PANEL_HEIGHT
    for panel in raw.get("panels") or []:
        kind = panel.get("type")
        defaults = {k: v for k, v in ((panel.get("fieldConfig") or {}).get("defaults") or {}).items()
                    if k not in STYLE_DROPPED_DEFAULTS}
        styles.setdefault(kind, {"defaults": copy.deepcopy(defaults), "options": copy.deepcopy(panel.get("options") or {})})
        if kind == "timeseries" and isinstance(panel.get("gridPos"), dict):
            height = max(2, min(int(panel["gridPos"].get("h") or height), 30))
    return DashboardTemplate(
        source="file", variables=tuple(copy.deepcopy(raw["templating"]["list"])), time=dict(raw["time"]),
        settings={key: copy.deepcopy(raw[key]) for key in TEMPLATE_COPIED_KEYS if key in raw},
        panel_styles=styles, panel_height=height)


def load_template(path: Optional[Path] = None) -> DashboardTemplate:
    """Read the deployed template (a customer overlay replaces the same file); builtin skeleton if unusable."""
    path = Path(path or TEMPLATE_PATH)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("[grafana_drafts] template %s unusable (%s); using the built-in skeleton", path, type(exc).__name__)
        return builtin_template()
    problems = _template_problems(raw)
    if problems:
        logger.warning("[grafana_drafts] template %s invalid (%s); using the built-in skeleton", path, "; ".join(problems[:3]))
        return builtin_template()
    return parse_template(raw)


def _variable_identity(variable: Mapping[str, Any]) -> Dict[str, Any]:
    """A variable without its selection: what must match the template exactly."""
    return {k: v for k, v in variable.items() if k not in ("current", "options")}


def _current(values: List[str]) -> Dict[str, Any]:
    return {"text": list(values), "value": list(values)}


class GrafanaDraftService:
    def __init__(self, analytics: AnalyticsService, root: Optional[Path] = None,
                 maintained_dir: Optional[Path] = None, template_path: Optional[Path] = None):
        self.analytics = analytics
        self.template_path = Path(template_path) if template_path else TEMPLATE_PATH
        self.root = Path(root or DRAFT_ROOT).resolve()
        self.maintained_dir = Path(maintained_dir or MAINTAINED_DASHBOARDS).resolve()
        if self.root == self.maintained_dir or self.maintained_dir in self.root.parents or self.root in self.maintained_dir.parents:
            raise AnalyticsValidationError("Draft root must be separate from the maintained dashboards")

    def template(self) -> DashboardTemplate:
        return load_template(self.template_path)

    # ------------------------------------------------------------------ reuse
    def find_maintained(self, request: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the maintained dashboard panel that already answers this request, if any."""
        if request.get("panels"):
            return None
        if request.get("preset"):
            candidates = [(str(request["preset"]), ARTIFACT_PRESETS.get(str(request["preset"])))]
        else:
            dims = list(request.get("dimensions") or [])
            mets = set(request.get("metrics") or [])
            candidates = [(name, preset) for name, preset in ARTIFACT_PRESETS.items()
                          if preset["source"] == request.get("source_id") and list(preset["dimensions"]) == dims
                          and mets and mets.issubset(set(preset["metrics"]))]
        for name, preset in candidates:
            if not preset or not preset.get("dashboard_ref") or not preset.get("dashboard_panel"):
                continue
            path = self.maintained_dir / preset["dashboard_ref"]
            if path.name == TEMPLATE_FILENAME or not path.is_file():
                continue
            dashboard = json.loads(path.read_text(encoding="utf-8"))
            titles = self._panel_titles(dashboard.get("panels") or [])
            if preset["dashboard_panel"] in titles:
                return {"preset": name, "dashboard_file": str(path.relative_to(PROJECT_ROOT)) if PROJECT_ROOT in path.parents else str(path),
                        "dashboard_uid": dashboard.get("uid"), "dashboard_title": dashboard.get("title"),
                        "panel_title": preset["dashboard_panel"]}
        return None

    @classmethod
    def _panel_titles(cls, panels: List[Mapping[str, Any]]) -> List[str]:
        titles: List[str] = []
        for panel in panels:
            titles.append(str(panel.get("title") or ""))
            titles.extend(cls._panel_titles(panel.get("panels") or []))
        return titles

    # ------------------------------------------------------------------ compile
    def _panel(self, request: Mapping[str, Any], context: AnalyticsContext, panel_id: int,
               grid: Dict[str, int], template: DashboardTemplate, variables: Mapping[str, str],
               claimed: Optional[Mapping[str, List[str]]] = None) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
        if request.get("panels") is not None:
            raise AnalyticsValidationError("Nested canvases are not supported")
        expanded = self.analytics.preset_request(request) if request.get("preset") else dict(request)
        source = self.analytics._source(str(expanded.get("source_id") or ""))
        mark = str(expanded.get("mark") or "table")
        if mark not in ALLOWED_MARKS:
            raise AnalyticsValidationError(f"Unsupported mark: {mark}")
        query_inputs = {key: expanded[key] for key in ("source_id", "dimensions", "metrics", "filters", "time_grain",
                                                       "sort", "limit", "scope", "flag_match_mode")
                        if expanded.get(key) not in (None, "")}
        # Only the user's filters may become variable selections; the rest stay literal in this panel.
        filter_origin = {name: origin for name, origin in (request.get("filter_origin") or {}).items()
                         if name in (query_inputs.get("filters") or {}) and origin != ORIGIN_USER}
        scope_literal = "scope" in (request.get("filter_origin") or {})
        if query_inputs.get("scope") == "current_device" and not scope_literal:
            self._scope_to_variables(query_inputs, source, context, variables)
        binder = GrafanaBinder(variables, claimed, literal=filter_origin)
        sql, fields = self.analytics.compile(query_inputs, context, binder)
        if filter_origin or (scope_literal and query_inputs.get("scope")):
            # recorded in the provenance so the recompile makes the same literal/variable choice
            query_inputs["filter_origin"] = {**filter_origin, **({"scope": ORIGIN_PANEL} if scope_literal else {})}
        dimensions = [f for f in fields if f in source.dimensions]
        metrics = [f for f in fields if f in source.metrics]
        diagnostics: List[str] = []
        panel_type = MARK_TO_PANEL[mark]
        if mark in {"radar", "heatmap", "scatter"}:
            diagnostics.append(f"{mark} has no core Grafana panel; rendered as {panel_type} (no plugins allowed)")
        time_x = bool(dimensions) and source.dimensions[dimensions[0]].kind == "time"
        if panel_type == "timeseries" and not time_x:
            panel_type = "barchart"
            diagnostics.append("line/area over a non-time axis rendered as barchart")
        fmt = "table"
        if panel_type in {"timeseries", "state-timeline"} and time_x:
            if not expanded.get("time_grain"):
                diagnostics.append("time axis without time_grain: one point per raw timestamp")
            if len(dimensions) == 2 and len(metrics) >= 1:
                # Grafana's long format: time, metric (series name), value.
                sql = (f'SELECT "{dimensions[0]}" AS "time", "{dimensions[1]}"::text AS "metric", '
                       f'"{metrics[0]}" AS "value" FROM ({sql}) q ORDER BY 1')
                fmt = "time_series"
            elif len(dimensions) == 1:
                sql = f'SELECT "{dimensions[0]}" AS "time", {", ".join(chr(34) + m + chr(34) for m in metrics)} FROM ({sql}) q ORDER BY 1'
                fmt = "time_series"
            else:
                panel_type = "table"
                diagnostics.append("more than two dimensions on a time axis rendered as table")
        diagnostics.append("rows are capped at 500 like Atlas queries; use a coarser time_grain for long ranges")
        title = str(expanded.get("title") or source.title)
        panel = {
            "id": panel_id, "type": panel_type, "title": title, "datasource": dict(DATASOURCE), "gridPos": grid,
            "targets": [{"refId": "A", "datasource": dict(DATASOURCE), "editorMode": "code", "format": fmt,
                         "rawQuery": True, "rawSql": sql}],
            "fieldConfig": {"defaults": {"unit": self._grafana_unit(source.metrics[metrics[0]].unit) if metrics else "none"},
                            "overrides": []},
            "options": {"legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"}},
        }
        shown = {name: origin for name, origin in filter_origin.items() if name in FILTER_VARIABLES}
        if shown:
            # Not the user's filters, so not dashboard variables: say what this panel is fixed to.
            fixed_filters = query_inputs.get("filters") or {}
            panel["description"] = "Fixed for this panel (not a dashboard variable): " + "; ".join(
                f"{name} = {', '.join(str(v) for v in (value if isinstance(value, list) else [value]))}"
                f" ({shown[name].replace('_', ' ')})" for name, value in fixed_filters.items() if name in shown)
        self._apply_style(panel, template)
        if mark == "stacked-bar":
            panel["options"]["stacking"] = "normal"
        self._apply_display(panel, source, metrics, expanded,
                            wide=(fmt == "table" or (panel_type == "timeseries" and len(dimensions) == 1)))
        binding = {"mode": "variables" if binder.bound else "literal", "variables": dict(binder.bound),
                   "fixed": {name: list(values) for name, values in binder.fixed.items()}}
        provenance = {"panel_id": panel_id, "source_id": source.id, "preset": request.get("preset"),
                      "query": query_inputs, "mark": mark, "sql_sha256": _sha(sql), "format": fmt, "binding": binding}
        return panel, provenance, diagnostics

    def _scope_to_variables(self, query_inputs: Dict[str, Any], source: Any, context: AnalyticsContext,
                            variables: Mapping[str, str]) -> None:
        """A user-origin current-device scope becomes the host/device_name variable selections (BUG-0410),
        like a device the user named: the viewer sees the device in the dropdowns and can widen to All.
        Anything that cannot be expressed that way (no such variables, id-keyed source, explicit device
        filters) keeps the literal scope clause."""
        filters = dict(query_inputs.get("filters") or {})
        host_field, device_field = source.dimensions.get("host_name"), source.dimensions.get("device_name")
        if (source.device_key_kind == "id" or "host_name" not in variables or "device_name" not in variables
                or "host_name" in filters or "device_name" in filters
                or not (host_field and device_field and host_field.filterable and device_field.filterable)
                or host_field.expression != source.host_expression
                or device_field.expression != source.device_expression):
            return
        host, _, device_name = self.analytics._current_device(context)
        if not device_name:
            return
        query_inputs["filters"] = {**filters, "host_name": [host], "device_name": [device_name]}
        del query_inputs["scope"]

    @staticmethod
    def _apply_style(panel: Dict[str, Any], template: DashboardTemplate) -> None:
        """House styling from the template's example panel of the same type (the metric sets unit and limits)."""
        style = template.panel_styles.get(panel["type"])
        if style is None and "timeseries" in template.panel_styles:
            legend = (template.panel_styles["timeseries"]["options"] or {}).get("legend")
            style = {"defaults": {}, "options": {"legend": legend} if legend else {}}
        if not style:
            return
        panel["fieldConfig"]["defaults"] = {**copy.deepcopy(style["defaults"]), **panel["fieldConfig"]["defaults"]}
        if style["options"]:
            panel["options"] = copy.deepcopy(style["options"])

    def _apply_display(self, panel: Dict[str, Any], source: Any, metrics: List[str],
                       expanded: Mapping[str, Any], wide: bool) -> None:
        """Display-only fieldConfig/options (never touches the SQL or its provenance).

        Every metric column gets its own catalog unit as a byName override. Charts plot the primary metric (the
        first one); a supporting metric whose unit differs (run_count next to pass_rate) is hidden from the
        visualization and its legend but stays in the tooltip, so one axis never mixes % with counts. Tables
        keep every column, each in its own unit (ms durations are humanized by Grafana). A categorical barchart
        with many bars rotates and truncates its x labels.
        """
        ptype = panel["type"]
        if not metrics or ptype not in {"barchart", "timeseries", "table", "stat", "piechart"}:
            return
        units = {m: self._grafana_unit(source.metrics[m].unit) for m in metrics}
        fc = panel["fieldConfig"]
        overrides: List[Dict[str, Any]] = []
        if ptype in {"table", "stat"}:
            fc["defaults"]["unit"] = "none"
        if ptype == "stat":
            # Grafana's default thresholds paint any value above 80 red (a run_count of 1126 looked like a failure).
            fc["defaults"]["thresholds"] = {"mode": "absolute", "steps": [{"color": "blue", "value": None}]}
        for index, name in enumerate(metrics):
            props: List[Dict[str, Any]] = []
            if wide:
                if units[name] != "none":
                    props.append({"id": "unit", "value": units[name]})
                if ptype not in {"table", "stat"} and index > 0 and units[name] != units[metrics[0]]:
                    props.append({"id": "custom.hideFrom", "value": {"viz": True, "legend": True, "tooltip": False}})
            if props:
                overrides.append({"matcher": {"id": "byName", "options": name}, "properties": props})
        fc["overrides"] = overrides
        if ptype in {"barchart", "timeseries"} and units[metrics[0]] == "percent":
            fc["defaults"].update({"min": 0, "max": 100})
        if ptype == "barchart":
            categories = int(expanded.get("limit") or expanded.get("max_categories") or 30)
            many = categories > BAR_LABEL_ROTATE_ABOVE
            panel["options"].update({"xTickLabelRotation": -45 if many else 0, "xTickLabelSpacing": 0,
                                     "xTickLabelMaxLength": BAR_LABEL_MAX_LENGTH, "showValue": "auto"})
            # Hovering a bar lists the hidden supporting metric too (timeseries keep the template's tooltip).
            panel["options"]["tooltip"] = {"mode": "multi", "sort": "desc"}

    @staticmethod
    def _default_days(request: Mapping[str, Any]) -> Optional[int]:
        preset = ARTIFACT_PRESETS.get(str(request.get("preset") or ""), {})
        days = request.get("time_range_days") or preset.get("time_range_days")
        return max(1, min(int(days), 3650)) if days else None

    @staticmethod
    def _grafana_unit(unit: Optional[str]) -> str:
        return {"ms": "ms", "s": "s", "%": "percent", "min": "m", "Mbps": "Mbits", "C": "celsius"}.get(unit or "", "none")

    def compile(self, request: Mapping[str, Any], context: AnalyticsContext,
                template: Optional[DashboardTemplate] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[str]]:
        template = template or self.template()
        variables = template.filter_variables()
        claimed: Dict[str, List[str]] = {}
        requests = request.get("panels") if request.get("panels") is not None else [request]
        if not isinstance(requests, list) or not 1 <= len(requests) <= 6:
            raise AnalyticsValidationError("A draft holds 1 to 6 panels")
        columns = 2 if len(requests) > 1 else 1
        width = 24 // columns
        panels, provenance, diagnostics = [], [], []
        for index, item in enumerate(requests):
            if not isinstance(item, dict):
                raise AnalyticsValidationError("Each panel must be an object")
            merged = {**{k: v for k, v in request.items() if k in {"filters", "scope"} and request.get("panels")}, **item}
            height = template.panel_height
            grid = {"x": (index % columns) * width, "y": (index // columns) * height, "w": width, "h": height}
            panel, origin, notes = self._panel(merged, context, index + 1, grid, template, variables, claimed)
            for name, values in origin["binding"]["fixed"].items():
                claimed.setdefault(name, values)
            panels.append(panel)
            provenance.append(origin)
            diagnostics.extend(f"panel {index + 1}: {note}" for note in notes)
        return {"panels": panels, "variables": claimed}, provenance, diagnostics

    # ------------------------------------------------------------------ files
    def _draft_dir(self, request_id: str) -> Path:
        if not REQUEST_ID.match(request_id):
            raise AnalyticsValidationError("Invalid draft request id")
        path = (self.root / request_id).resolve()
        if path.parent != self.root:
            raise AnalyticsValidationError("Draft path escapes the draft root")
        return path

    def build(self, request: Mapping[str, Any], context: AnalyticsContext, now: Optional[datetime] = None,
              request_id: Optional[str] = None) -> Dict[str, Any]:
        """Compile and validate a draft in memory (no files, no network). Raises when validation fails."""
        now = now or datetime.now(timezone.utc)
        check_request_keys(request)
        for panel in request.get("panels") or []:
            if isinstance(panel, dict):
                check_request_keys(panel)
        template = self.template()
        compiled, provenance, diagnostics = self.compile(request, context, template)
        ttl = max(1, min(int(request.get("ttl_hours") or DEFAULT_TTL_HOURS), MAX_TTL_HOURS))
        request_id = request_id or (uuid.uuid4().hex[:12] + "-" + now.strftime("%Y%m%d"))
        title = str(request.get("title") or (compiled["panels"][0]["title"] if len(compiled["panels"]) == 1 else "Atlas draft"))
        days = self._default_days(request)
        dashboard = {
            "title": f"[Draft] {title}"[:120], "uid": UID_PREFIX + request_id[:28],
            "description": "Ephemeral Atlas draft. Not provisioned. Review, then copy into the maintained dashboards folder to promote.",
            "tags": ["atlas-draft"], **copy.deepcopy(template.settings),
            "time": {"from": f"now-{days}d", "to": "now"} if days else dict(template.time),
            "templating": {"list": self._variables(template, compiled["variables"])},
            "panels": compiled["panels"],
        }
        metadata = {
            "schema": DRAFT_SCHEMA, "request_id": request_id, "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=ttl)).isoformat(), "team_id": context.team_id,
            "created_by": context.user_id, "provisioned": False, "promotion": "manual",
            "promotion_instructions": "Atlas never publishes drafts. To keep it, copy dashboard.json into "
                                      "infra/monitoring/grafana/dashboards/ and import it yourself.",
            "datasource": dict(DATASOURCE), "panels": provenance, "diagnostics": diagnostics,
            "template": {"source": template.source, "variables": template.variable_names},
        }
        report = self.validate(dashboard, metadata, context)
        if report["errors"]:
            raise AnalyticsValidationError("Draft failed validation: " + "; ".join(report["errors"]))
        metadata["validation"] = report
        return {"dashboard": dashboard, "metadata": metadata, "validation": report, "diagnostics": diagnostics}

    @staticmethod
    def _variables(template: DashboardTemplate, fixed: Mapping[str, List[str]]) -> List[Dict[str, Any]]:
        """The template's variables; a value the user fixed becomes the selection, so it stays visible and changeable."""
        variables = copy.deepcopy(list(template.variables))
        for variable in variables:
            if variable.get("name") in fixed:
                variable["current"] = _current(list(fixed[variable["name"]]))
        return variables

    def create(self, request: Mapping[str, Any], context: AnalyticsContext, now: Optional[datetime] = None,
               request_id: Optional[str] = None) -> Dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        check_request_keys(request)
        removed = self.cleanup_expired(now)
        if request.get("prefer_existing", True) is not False:
            existing = self.find_maintained(request)
            if existing:
                return {"status": "reused", "maintained": existing, "draft_path": None, "expired_drafts_removed": removed,
                        "message": "A maintained dashboard panel already shows this; no draft was created."}
        fixed_id = request_id
        built = self.build(request, context, now, request_id)
        dashboard, metadata, report, diagnostics = built["dashboard"], built["metadata"], built["validation"], built["diagnostics"]
        request_id = metadata["request_id"]
        target = self._draft_dir(request_id)
        self.root.mkdir(parents=True, exist_ok=True)
        target.mkdir(exist_ok=bool(fixed_id))
        (target / "dashboard.json").write_text(json.dumps(dashboard, indent=2, sort_keys=True), encoding="utf-8")
        (target / "draft.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        relative = target.relative_to(PROJECT_ROOT) if PROJECT_ROOT in target.parents else target
        return {"status": "draft", "draft_path": str(relative / "dashboard.json"), "request_id": request_id,
                "expires_at": metadata["expires_at"], "diagnostics": diagnostics, "validation": report,
                "expired_drafts_removed": removed, "dashboard": dashboard, "metadata": metadata,
                "message": "Draft written to a temporary folder. It is not provisioned; promote it manually if you keep it."}

    def validate(self, dashboard: Mapping[str, Any], metadata: Mapping[str, Any], context: AnalyticsContext) -> Dict[str, Any]:
        """Schema, provisioning, datasource, secret, SQL-safety and provenance checks."""
        errors: List[str] = []
        unknown = set(dashboard) - DASHBOARD_KEYS
        if unknown:
            errors.append(f"unexpected dashboard keys {sorted(unknown)}")
        for key in ("title", "uid", "panels", "schemaVersion", "templating"):
            if key not in dashboard:
                errors.append(f"missing {key}")
        if "id" in dashboard:
            errors.append("provisioned dashboards must not carry an id")
        if not str(dashboard.get("uid", "")).startswith(UID_PREFIX) or len(str(dashboard.get("uid", ""))) > 40:
            errors.append("draft uid must use the atlas-draft- prefix and fit Grafana's 40 characters")

        def walk(node: Any, path: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if SECRET_KEY.search(str(key)):
                        errors.append(f"credential-like key at {path}.{key}")
                    if key == "datasource" and value != DATASOURCE:
                        errors.append(f"datasource at {path} is not the configured VirtualPyTest datasource")
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")
        walk(dashboard, "dashboard")

        template = self.template()
        variables = (dashboard.get("templating") or {}).get("list") or []
        origins_for_vars = [item for item in metadata.get("panels") or [] if isinstance(item, dict)]
        fixed: Dict[str, List[str]] = {}
        for item in origins_for_vars:
            for name, values in ((item.get("binding") or {}).get("fixed") or {}).items():
                fixed.setdefault(name, list(values))
        expected = self._variables(template, fixed)
        if len(variables) != len(expected) or any(
                not isinstance(have, dict) or _variable_identity(have) != _variable_identity(want) or have.get("current") != want.get("current")
                for have, want in zip(variables, expected)):
            errors.append("dashboard variables must be exactly the template's variables: " + ", ".join(template.variable_names))
        allowed_filters = template.filter_variables()
        for item in origins_for_vars:
            for filter_name, variable in ((item.get("binding") or {}).get("variables") or {}).items():
                if allowed_filters.get(filter_name) != variable:
                    errors.append(f"panel {item.get('panel_id')} binds {filter_name} to {variable}, which the template does not declare")

        panels = dashboard.get("panels") or []
        origins = {item.get("panel_id"): item for item in metadata.get("panels") or []}
        if len(origins) != len(panels):
            errors.append("every panel needs provenance")
        for panel in panels:
            if panel.get("type") not in PANEL_TYPES:
                errors.append(f"panel type {panel.get('type')} is not a core allowlisted panel")
            for forbidden in ("libraryPanel", "pluginVersion", "transformations"):
                if forbidden in panel:
                    errors.append(f"panel {panel.get('id')} carries {forbidden}")
            targets = panel.get("targets") or []
            if len(targets) != 1:
                errors.append(f"panel {panel.get('id')} must have exactly one query")
                continue
            sql = str(targets[0].get("rawSql") or "")
            bare = _strip_literals(sql)
            if ";" in bare or "--" in bare or "/*" in bare:
                errors.append(f"panel {panel.get('id')} SQL has a statement separator or comment")
            if not re.match(r"^\s*(WITH|SELECT)\b", bare, re.IGNORECASE):
                errors.append(f"panel {panel.get('id')} SQL is not a SELECT")
            if WRITE_SQL.search(bare):
                errors.append(f"panel {panel.get('id')} SQL contains a non-read keyword")
            origin = origins.get(panel.get("id"))
            if not origin:
                continue
            try:
                expected = self._recompile(origin, context, template)
            except AnalyticsValidationError as exc:
                errors.append(f"panel {panel.get('id')} provenance does not compile: {exc}")
                continue
            if _sha(sql) != origin.get("sql_sha256") or _sha(expected) != origin.get("sql_sha256"):
                errors.append(f"panel {panel.get('id')} SQL does not match its catalog template")
        return {"errors": errors, "checks": ["schema", "provisioning", "datasource-allowlist", "no-credentials",
                                             "read-only-sql", "sql-template-provenance", "core-panels-only"]}

    def _recompile(self, origin: Mapping[str, Any], context: AnalyticsContext, template: DashboardTemplate) -> str:
        """Rebuild a panel's SQL from its recorded catalog inputs."""
        source_id = origin.get("source_id")
        if source_id not in ANALYTICS_SOURCES:
            raise AnalyticsValidationError("unknown source")
        query = dict(origin.get("query") or {})
        if query.get("source_id") != source_id:
            raise AnalyticsValidationError("source mismatch")
        if query.get("time_grain") not in (None, *TIME_GRAINS):
            raise AnalyticsValidationError("bad time grain")
        grid = {"x": 0, "y": 0, "w": 24, "h": 9}
        # The recorded binding decides which filters were variables (a panel that disagreed with another stayed literal).
        bound = dict((origin.get("binding") or {}).get("variables") or {})
        panel, _, _ = self._panel({**query, "mark": origin.get("mark")}, context, int(origin.get("panel_id") or 1), grid,
                                  template, bound)
        return panel["targets"][0]["rawSql"]

    def cleanup_expired(self, now: Optional[datetime] = None) -> int:
        """Delete expired draft folders; anything that is not a recognisable draft is left alone."""
        now = now or datetime.now(timezone.utc)
        if not self.root.is_dir():
            return 0
        removed = 0
        for child in self.root.iterdir():
            if child.is_symlink() or not child.is_dir() or not REQUEST_ID.match(child.name):
                continue
            if {item.name for item in child.iterdir()} - {"dashboard.json", "draft.json"}:
                continue
            try:
                metadata = json.loads((child / "draft.json").read_text(encoding="utf-8"))
                expires = datetime.fromisoformat(str(metadata["expires_at"]))
            except (OSError, ValueError, KeyError):
                continue
            if metadata.get("schema") == DRAFT_SCHEMA and expires <= now:
                shutil.rmtree(child)
                removed += 1
        return removed
