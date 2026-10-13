"""Small MCP surface over the trusted, read-only analytics semantic layer."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

from backend_server.src.lib.analytics import ANALYTICS_SOURCES, ARTIFACT_PRESETS, AnalyticsContext, AnalyticsService
from backend_server.src.lib.analytics.grafana_drafts import FILTER_VARIABLES, GrafanaDraftService
from backend_server.src.lib.analytics.grafana_push import GrafanaDraftPublisher, GrafanaPushError, is_canvas, link_for_reply
from backend_server.src.lib.analytics.named_devices import find_mentions, split_named
from backend_server.src.lib.analytics.service import IDENTITY_FILTERS, AnalyticsValidationError

logger = logging.getLogger(__name__)

EXPORT_TEXT_LIMIT = 6000
SHOWN_DATA_ROWS = 30
SHOWN_COMPARISON_ROWS = 60
COMPARISON_HELP_TEXT = ("object with baseline and candidate values of the series field, e.g. variant v1 and v2; "
                        "optional regression_over_percent; direction comes from the metric (timings lower-is-better, "
                        "rates higher-is-better), set it only for counts; align_by, series_field, metric default to "
                        "the chart's category, series and first metric")

# ToolBridge injects trusted caller context (the private `_context_*` keys) into exactly
# these tools; none of them exposes those keys in its public schema.
ANALYTICS_TOOL_NAMES = frozenset({
    "list_analytics_sources", "describe_analytics_source", "query_analytics_data",
    "render_analytics_artifact", "export_analytics_data", "create_grafana_draft", "query_kpi_radar",
})


def _context(params: Dict[str, Any]) -> AnalyticsContext:
    """Build context only from private keys injected by ToolBridge."""
    return AnalyticsContext(
        team_id=str(params.get("_context_team_id") or ""),
        user_id=str(params.get("_context_user_id") or ""),
        user_email=str(params.get("_context_user_email") or ""),
        user_role=str(params.get("_context_user_role") or "viewer"),
        workspace_id=str(params.get("_context_workspace_id") or ""),
        selected_server=str(params.get("_context_selected_server") or ""),
        selected_server_name=str(params.get("_context_selected_server_name") or ""),
        selected_server_hosts=tuple(str(value) for value in (params.get("_context_selected_server_hosts") or []) if value),
        host_name=str(params.get("_context_host_name") or ""),
        device_id=str(params.get("_context_device_id") or ""),
        userinterface_name=str(params.get("_context_userinterface_name") or ""),
        # the Target's registry name, known when the message referred to it (BUG-0405)
        device_name=str((params.get("_context_selected_device") or {}).get("device_name") or "")
        if params.get("_context_refers_to_selected_device") else "",
    )


def _request(params: Dict[str, Any]) -> Dict[str, Any]:
    """The model-facing request: private context keys never reach the compiler."""
    return {key: value for key, value in params.items() if not key.startswith("_context_")}


def _dashboard_summary(result: Dict[str, Any]) -> str:
    """What the answer must say about the built dashboard: panels, variables, preselected filters."""
    dashboard, metadata = result.get("dashboard") or {}, result.get("metadata") or {}
    variables = [v for v in (dashboard.get("templating") or {}).get("list") or [] if v.get("hide") != 2]
    fixed: Dict[str, list] = {}
    literal = []
    for origin in metadata.get("panels") or []:
        binding = origin.get("binding") or {}
        fixed.update(binding.get("fixed") or {})
        if binding.get("mode") == "literal" and (origin.get("query") or {}).get("filters"):
            literal.append(str(origin.get("panel_id")))
    labels = {v.get("name"): v.get("label") or v.get("name") for v in variables}
    parts = [" Panels: " + "; ".join(f"{p.get('title')} ({p.get('type')})" for p in dashboard.get("panels") or []) + "."]
    parts.append(" Dashboard variables: " + ", ".join(str(v.get("label") or v.get("name")) for v in variables) + ".")
    if fixed:
        parts.append(" Preselected filters (only values the user asked for): "
                     + ", ".join(f"{labels.get(name, name)}={'/'.join(values)}" for name, values in fixed.items()) + ".")
    else:
        parts.append(" Preselected filters: none. Every variable starts on All (Workspace keeps its normal default); "
                     "do not say any filter was preselected to the current context.")
    limited = [str(o.get("panel_id")) for o in metadata.get("panels") or [] if (o.get("query") or {}).get("scope") == "current_device"]
    if limited:
        parts.append(f" Panel(s) {', '.join(limited)} are limited to the current device in the query (not a variable).")
    bound_names = {name: set(((o.get("binding") or {}).get("variables") or {}).values()) for name, o in
                   ((o.get("panel_id"), o) for o in metadata.get("panels") or [])}
    titles = {p.get("id"): p.get("title") for p in dashboard.get("panels") or []}
    unaffected = []
    for variable in variables:
        name = variable.get("name")
        if name not in FILTER_VARIABLES.values():
            continue
        skipped = [f"{pid} ({titles.get(pid)})" for pid, names in bound_names.items() if name not in names]
        if skipped:
            unaffected.append(f"{variable.get('label') or name}: panel {', '.join(skipped)}")
    if unaffected:
        parts.append(" Variables that do not affect a panel (its source has no such column): " + "; ".join(unaffected) + ".")
    if literal:
        parts.append(f" Filters fixed in the query (not variables) on panel(s) {', '.join(literal)}: they conflict with a value another panel preselected.")
    return "".join(parts)


def _draft_note(exc: Exception) -> str:
    """A short, user-facing reason for a failed draft (never the model-facing retry instructions)."""
    text = re.sub(r"Missing preset filters", "missing required filter", str(exc), flags=re.IGNORECASE)
    text = text.split(" Do not ")[0].split(". ")[0].rstrip(".")
    return text[:140]


def _ok(payload: Dict[str, Any], message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": False, **payload}


def _named(params: Dict[str, Any]) -> list:
    return [d for d in (params.get("_context_named_devices") or []) if isinstance(d, dict) and d.get("name")]


def enforce_selected_device(request: Dict[str, Any], params: Dict[str, Any], named: list):
    """The user said "my/selected/this device(s)": scope every unfiltered request to the chat's Target (BUG-0405).

    Returns ``(request, note)``. Sets ``scope='current_device'`` (a canvas at the top level, and on each
    panel that would otherwise run unscoped) and discloses it. Devices the user named win, and an explicit
    device/host filter from the model is left alone. A Target on another server changes nothing but says so.
    """
    if not isinstance(request, dict) or named:
        return request, ""
    if params.get("_context_selected_device_foreign"):
        return request, ("Your selected device is not on this server, so its data is not here; showing the "
                         "visible devices of this server instead")
    selected = params.get("_context_selected_device") or {}
    if not params.get("_context_refers_to_selected_device") or not selected.get("host_name"):
        return request, ""
    panels = request.get("panels")
    leaves = [(p, request) for p in panels if isinstance(p, dict)] if isinstance(panels, list) else [(request, {})]

    def applicable(leaf, shared):
        source = _leaf_source(leaf)
        return bool(source and source.host_expression and source.device_expression and _eligible(leaf, shared))

    targets = [leaf for leaf, shared in leaves if applicable(leaf, shared)]
    if not targets:
        return request, ""
    patched = dict(request)
    if isinstance(panels, list):
        patched["scope"] = "current_device"
        patched["panels"] = [({**p, "scope": "current_device"} if any(p is t for t in targets) else
                              ({**p, "scope": p.get("scope") or "visible"} if isinstance(p, dict) else p))
                             for p in panels]
    else:
        patched["scope"] = "current_device"
    label = f"{selected.get('device_name')} ({selected['host_name']})" if selected.get("device_name") else selected["host_name"]
    return patched, f"Limited to your selected device {label}"


def _leaf_source(leaf: Dict[str, Any]):
    preset = ARTIFACT_PRESETS.get(str(leaf.get("preset") or ""))
    return ANALYTICS_SOURCES.get(str((preset or {}).get("source") or leaf.get("source_id") or ""))


def _eligible(leaf: Dict[str, Any], shared: Dict[str, Any]) -> bool:
    """A request the named-device rule applies to: its source has a device_name dimension, it is not
    scoped to the current device, and it carries no explicit device/host filter."""
    source = _leaf_source(leaf)
    if source is None or "device_name" not in source.dimensions:
        return False
    if (leaf.get("scope") or shared.get("scope")) == "current_device":
        return False
    merged = {**(shared.get("filters") or {}), **(leaf.get("filters") or {})}
    return not any(merged.get(name) not in (None, "", [], {}) for name in IDENTITY_FILTERS)


def enforce_named_devices(request: Dict[str, Any], named: list):
    """Apply the devices the user named to a query/render/export request (BUG-0355).

    Returns ``(request, note, blocked)``. Requests without any device/host filter get
    ``filters.device_name`` = the named devices that are on this server; when none is, ``blocked`` is
    the message to return instead of any data, so other devices are never charted under that request.
    An explicit device/host filter from the model is left alone (a deliberate, labelled overview).
    """
    on, off = split_named(named)
    if not named or not isinstance(request, dict):
        return request, "", ""
    panels = request.get("panels")
    leaves = [(p, request) for p in panels if isinstance(p, dict)] if isinstance(panels, list) else [(request, {})]
    targets = [leaf for leaf, shared in leaves if _eligible(leaf, shared)]
    if not targets:
        return request, "", ""
    if not on:
        return request, "", (
            f"The devices you named ({', '.join(repr(n) for n in off)}) are not on this server; nothing was "
            "substituted and no chart or data was produced. Tell the user these devices are not on the "
            "selected server (they can switch server) and do not chart other devices for this request.")
    patched = dict(request)
    if isinstance(panels, list):
        patched["panels"] = [({**p, "filters": {**(p.get("filters") or {}), "device_name": list(on)}}
                              if any(p is t for t in targets) else p) for p in panels]
    else:
        patched["filters"] = {**(request.get("filters") or {}), "device_name": list(on)}
    note = f"Filtered to the devices you named: {', '.join(on)}"
    if off:
        note += f"; not on this server and left out (nothing substituted): {', '.join(off)}"
    return patched, note, ""


def _effective_device_names(leaf: Dict[str, Any], shared: Dict[str, Any]) -> set:
    merged = {**(shared.get("filters") or {}), **(leaf.get("filters") or {})}
    raw = merged.get("device_name")
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    return {str(v).lower() for v in values if v not in (None, "")}


def sanitize_titles(artifact: Dict[str, Any], request: Dict[str, Any], known: list) -> list:
    """Replace any title that names a known device outside its effective device_name filter with a
    neutral one. Returns the device names that were removed (for disclosure)."""
    if not known:
        return []
    spec = artifact["content_data"]["artifact_spec"]
    panels_in = request.get("panels") if isinstance(request.get("panels"), list) else None
    removed: list = []

    def neutral(title: str, allowed: set, fallback: str) -> str:
        bad = [n for n in find_mentions(title, known) if n.lower() not in allowed]
        if not bad:
            return title
        removed.extend(bad)
        return fallback

    if spec.get("kind") == "canvas":
        allowed_all: set = set()
        for index, panel in enumerate(spec["panels"]):
            leaf = panels_in[index] if panels_in and index < len(panels_in) and isinstance(panels_in[index], dict) else {}
            allowed = _effective_device_names(leaf, request)
            allowed_all |= allowed
            panel["title"] = neutral(str(panel.get("title") or ""), allowed, f"Panel {index + 1}")
        spec["title"] = neutral(str(spec.get("title") or ""), allowed_all, "Analytics canvas")
    else:
        preset = ARTIFACT_PRESETS.get(str(request.get("preset") or ""))
        spec["title"] = neutral(str(spec.get("title") or ""), _effective_device_names(request, {}),
                                (preset or {}).get("title") or "Analytics")
    artifact["title"] = spec["title"]
    return removed


def _with_note(message: str, notes: list) -> str:
    notes = [n for n in notes if n]
    return (" ".join(n.rstrip(".") + "." for n in notes) + " " + message) if notes else message


def _unmatched_note(unmatched: Any) -> str:
    """Plain words for identity filters that matched nothing, so the model reports it instead of substituting."""
    if not unmatched:
        return ""
    return "; " + "; ".join(
        f"{name} {', '.join(repr(v) for v in values)} matched nothing on this server — tell the user; "
        "do not substitute other devices or drop the filter" for name, values in unmatched.items())


def _shown(artifact: Dict[str, Any], grafana_base: str = "") -> str:
    """Tell the model the user already sees the artifact, with the rows it needs to summarise it.

    Comparison rows are given in full (bounded): a sample made Atlas report one KPI regression
    out of five.
    """
    spec = artifact["content_data"]["artifact_spec"]
    panels = spec["panels"] if spec.get("kind") == "canvas" else [spec]
    parts = []
    for panel in panels:
        data = panel["data"]
        rows = data["rows"]
        note = f"{panel['title']}: {panel['mark']}, {data['row_count']} rows"
        note += _unmatched_note(panel["options"].get("unmatched_filters"))
        if panel["options"].get("defaulted_filters_note"):
            note += f" ({panel['options']['defaulted_filters_note']}; state this interface in your answer)"
        if panel["options"].get("time_grain_note"):
            note += f" ({panel['options']['time_grain_note']})"
        if not rows:
            scope = panel["options"].get("scope_note")
            parts.append(note + " — NO DATA matched (filters, scope or time range)"
                         + (f"; {scope}, so data from other servers' hosts is not included" if scope else "")
                         + "; tell the user nothing matched, do not substitute other devices. "
                         + (panel["options"].get("availability_note") or "")
                         + " Answer now; do not run more queries for this question.")
            continue
        if panel["options"].get("fallback_applied"):
            note += f" (shown as {panel['mark']}: {panel['options'].get('fallback_reason')})"
        comparison = panel.get("comparison")
        if comparison:
            compared = comparison["rows"][:SHOWN_COMPARISON_ROWS]
            note += (f"; comparison {comparison['baseline']} -> {comparison['candidate']} on {comparison['metric']} "
                     f"({comparison['direction']}"
                     + (f", only regressions over {comparison['regression_over_percent']}%" if comparison.get("regression_over_percent") is not None else "")
                     + f"): {sum(1 for r in comparison['rows'] if r.get('regression'))} regressions, "
                     + f"{sum(1 for r in comparison['rows'] if r.get('missing'))} with one side missing (not regressions, "
                     + "no data to compare); "
                     + f"{len(comparison['rows'])} rows, all listed{'' if len(comparison['rows']) <= SHOWN_COMPARISON_ROWS else ' up to ' + str(SHOWN_COMPARISON_ROWS)} "
                     + json.dumps(compared, default=str))
        else:
            shown = rows[:SHOWN_DATA_ROWS]
            note += f"; {'all rows' if len(shown) == len(rows) else f'first {len(shown)} of {len(rows)} rows'} " + json.dumps(shown, default=str)
        parts.append(note)
    grafana = spec.get("grafana")
    grafana_note = ""
    if grafana:
        grafana_note = (f" Grafana {'dashboard' if grafana['reused'] else 'draft'}: {link_for_reply(grafana['path'], grafana_base)}"
                        + (f" (expires {grafana['expires_at']})" if grafana.get("expires_at") else "")
                        + " - mention this link once.")
    hint = (" If the user asked for several charts, render them together in ONE call with panels=[...]."
            if len(panels) == 1 else "")
    return ("Displayed to the user in the chat panel — do not render it again. Summarise it from these rows only. "
            + " | ".join(parts) + hint + grafana_note)


def _exported(export: Dict[str, Any]) -> str:
    """Give the model the real file content so it never has to invent rows."""
    content = export["content"]
    shown = content if len(content) <= EXPORT_TEXT_LIMIT else content[:EXPORT_TEXT_LIMIT] + "\n…(cut; the file has all rows)"
    note = " (truncated at 500 rows)" if export["truncated"] else ""
    return (f"Exported {export['row_count']} rows as {export['format'].upper()} ({export['filename']}){note}. "
            "Show or summarise ONLY the content below; never invent rows. Charts in the chat also have a CSV/JSON "
            f"download button.\n{shown}")


def _error(exc: Exception) -> Dict[str, Any]:
    # Do not return SQL, DSNs, or driver details to the model.
    message = str(exc) if isinstance(exc, AnalyticsValidationError) else "Analytics query failed."
    return {"content": [{"type": "text", "text": message}], "isError": True}


class AnalyticsTools:
    """Allowlisted analytics catalog, queries, comparisons, artifacts, exports and Grafana drafts."""

    def __init__(self, api_client=None):
        self.service = AnalyticsService(api_client=api_client)
        self.drafts = GrafanaDraftService(self.service)
        self.publisher = GrafanaDraftPublisher(self.service, self.drafts)

    def list_analytics_sources(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List trusted analytics sources and dashboard-equivalent presets (no SQL, no credentials).
        Start here for any chart, KPI, pass-rate, alert, fleet, occupancy, network or system-history question.

        Args:
            params: {} (no parameters required)

        Returns:
            Sources (fields, metrics, units, dashboard references) and presets (title, mark, required filters).
        """
        sources = self.service.list_sources()
        presets = self.service.list_presets()
        return _ok({"sources": sources, "presets": presets},
                   f"Found {len(sources)} analytics sources and {len(presets)} presets.")

    def describe_analytics_source(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Describe one analytics source before querying it.

        Example: describe_analytics_source(source_id='kpi_measurements')

        Args:
            params: {
                'source_id': str (REQUIRED - one of: SOURCE_IDS)
            }

        Returns:
            Allowed dimensions, metrics, filters, units and the presets built on the source.
        """
        try:
            source = self.service.describe_source(str(params.get("source_id") or ""))
            return _ok({"source": source}, f"Described analytics source {source['id']}.")
        except Exception as exc:
            return _error(exc)

    def query_analytics_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query normalized analytics rows using allowlisted fields and trusted caller scope.
        Never accepts SQL, team_id, user identity, role, workspace membership, or credentials.
        Use scope='current_device' for questions about 'this device' (the device selected in the app).

        Example: query_analytics_data(source_id='script_results', dimensions=['device_name'], metrics=['pass_rate','run_count'], time_range_days=30)

        Args:
            params: {
                'source_id': str (OPTIONAL - required unless preset is given; one of: SOURCE_IDS),
                'preset': str (OPTIONAL - dashboard-equivalent template, preferred when one fits: PRESET_IDS),
                'dimensions': list (OPTIONAL - allowlisted grouping fields),
                'metrics': list (OPTIONAL - allowlisted aggregate metrics),
                'filters': dict (OPTIONAL - exact/in filters keyed by allowlisted dimension),
                'scope': str (OPTIONAL - visible (default) or current_device),
                'time_grain': str (OPTIONAL - hour, day, week or month bucket for time dimensions),
                'from_time': str (OPTIONAL - ISO-8601 lower bound),
                'to_time': str (OPTIONAL - ISO-8601 upper bound),
                'time_range_days': int (OPTIONAL - trailing days, default 30, maximum 3650),
                'sort': list (OPTIONAL - up to three entries with field and direction asc/desc),
                'limit': int (OPTIONAL - maximum 500),
                'offset': int (OPTIONAL - pagination offset, maximum 10000),
                'comparison': dict (OPTIONAL - COMPARISON_HELP)
            }

        Returns:
            analytics-tabular-v1 rows, and analytics-comparison-v1 rows when requested.
        """
        try:
            request, note, blocked = enforce_named_devices(_request(params), _named(params))
            if blocked:
                return _ok({"named_devices_blocked": True}, blocked)
            request, selected_note = enforce_selected_device(request, params, _named(params))
            note = _with_note("", [note, selected_note]).strip()
            result = self.service.query(request, _context(params))
            if request.get("comparison"):
                result["comparison"] = self.service.compare(result, request["comparison"],
                                                            self.service.comparison_defaults(request, result))
            message = f"Returned {result['row_count']} analytics rows from {result['source_id']}."
            if result.get("time_grain_defaulted"):
                message += f" No time_grain was given; defaulted to '{result['time_grain']}' from the time range."
            if not result["row_count"]:
                message += (" NO DATA matched. " + (result.get("availability_note") or "")
                            + " Answer now; do not run more queries for this question.")
            return _ok({"data": result}, _with_note(message + _unmatched_note(result.get("unmatched_filters")), [note]))
        except Exception as exc:
            return _error(exc)

    def render_analytics_artifact(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Render a preset or dynamically composed safe chart/table/canvas artifact; it is shown to the user immediately.
        A canvas, dashboard or several charts in one request is ONE call with panels=[...] (1-6 panels), never one call per chart: the user sees only the latest artifact. Use a preset when one fits; otherwise choose allowlisted source fields and a mark.
        A canvas is 1-6 panel requests in 'panels'; shared filters/time/scope apply to every panel.

        Example: render_analytics_artifact(preset='kpi_radar', filters={'userinterface_name':'stb_tv'}, time_range_days=30)

        Args:
            params: {
                'preset': str (OPTIONAL - dashboard-equivalent template, preferred when one fits: PRESET_IDS),
                'source_id': str (OPTIONAL - required when preset and panels are omitted; one of: SOURCE_IDS),
                'dimensions': list (OPTIONAL - allowlisted fields),
                'metrics': list (OPTIONAL - allowlisted metrics),
                'filters': dict (OPTIONAL - allowlisted filters),
                'scope': str (OPTIONAL - visible (default) or current_device),
                'time_grain': str (OPTIONAL - hour, day, week or month),
                'mark': str (OPTIONAL - radar, line, area, bar, stacked-bar, pie, scatter, heatmap, stat, state-timeline or table),
                'category': str (OPTIONAL - category/x dimension),
                'series': str (OPTIONAL - series dimension),
                'title': str (OPTIONAL - chart title),
                'comparison': dict (OPTIONAL - COMPARISON_HELP),
                'panels': list (OPTIONAL - 1 to 6 child requests for a multi-panel canvas),
                'columns': int (OPTIONAL - canvas columns 1-3),
                'from_time': str (OPTIONAL - ISO-8601 lower bound),
                'to_time': str (OPTIONAL - ISO-8601 upper bound),
                'time_range_days': int (OPTIONAL - trailing days),
                'max_categories': int (OPTIONAL - readability ceiling),
                'max_series': int (OPTIONAL - readability ceiling)
            }

        Returns:
            Agent Chat artifact using the vpt-artifact/v1 declarative grammar.
        """
        try:
            request, note, blocked = enforce_named_devices(_request(params), _named(params))
            if blocked:
                return _ok({"named_devices_blocked": True}, blocked)
            request, selected_note = enforce_selected_device(request, params, _named(params))
            note = _with_note("", [note, selected_note]).strip()
            artifact = self.service.render(request, _context(params))
            removed = sanitize_titles(artifact, request, params.get("_context_known_device_names") or [])
            grafana_error = self._attach_grafana(artifact, request, params)
            notes = [note, grafana_error, (f"The title named devices that are not in the filter ({', '.join(removed)}); it was "
                            "replaced with a neutral one") if removed else ""]
            return _ok({"artifact": artifact}, _with_note(_shown(artifact, params.get("_context_grafana_base_url") or ""), notes))
        except Exception as exc:
            return _error(exc)

    def _attach_grafana(self, artifact: Dict[str, Any], request: Dict[str, Any], params: Dict[str, Any]) -> str:
        """Canvas only (2+ panels): create + push the matching Grafana draft. Never raises; returns a note on failure."""
        spec = artifact["content_data"]["artifact_spec"]
        if spec.get("kind") != "canvas" or not is_canvas(request):
            return ""
        try:
            context = _context(params)
            resolved = [(panel.get("provenance") or {}).get("resolved_request") for panel in spec.get("panels") or []]
            if not resolved or not all(isinstance(item, dict) for item in resolved):
                raise AnalyticsValidationError("the canvas carries no resolved panels")
            # The draft is built from what the render resolved (presets, defaulted interface, named
            # devices, scope), plus the current device resolved here, so no server re-resolves anything.
            context = self.service.resolve_current_device(resolved, context)
            spec["grafana"] = self.publisher.publish({"title": spec.get("title"), "panels": resolved}, context)
            return ""
        except (AnalyticsValidationError, GrafanaPushError) as exc:
            return f"Grafana draft not created: {_draft_note(exc)}"
        except Exception as exc:
            logger.warning("[analytics] Grafana draft failed: %s", type(exc).__name__)
            return f"Grafana draft not created: {type(exc).__name__}"

    def export_analytics_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Export a bounded analytics result (max 500 rows) as CSV or JSON text, with the same scope as queries.
        CSV cells that a spreadsheet would evaluate are neutralized.

        Example: export_analytics_data(preset='failing_testcases', format='csv', time_range_days=7)

        Args:
            params: {
                'format': str (OPTIONAL - csv (default) or json),
                'preset': str (OPTIONAL - dashboard-equivalent template: PRESET_IDS),
                'source_id': str (OPTIONAL - required when preset is omitted; one of: SOURCE_IDS),
                'dimensions': list (OPTIONAL - allowlisted fields),
                'metrics': list (OPTIONAL - allowlisted metrics),
                'filters': dict (OPTIONAL - allowlisted filters),
                'scope': str (OPTIONAL - visible (default) or current_device),
                'time_grain': str (OPTIONAL - hour, day, week or month),
                'from_time': str (OPTIONAL - ISO-8601 lower bound),
                'to_time': str (OPTIONAL - ISO-8601 upper bound),
                'time_range_days': int (OPTIONAL - trailing days),
                'sort': list (OPTIONAL - up to three field/direction entries),
                'limit': int (OPTIONAL - maximum 500),
                'comparison': dict (OPTIONAL - export the aligned comparison rows instead; COMPARISON_HELP)
            }

        Returns:
            filename, mime_type and content text.
        """
        try:
            request, note, blocked = enforce_named_devices(_request(params), _named(params))
            if blocked:
                return _ok({"named_devices_blocked": True}, blocked)
            request, selected_note = enforce_selected_device(request, params, _named(params))
            note = _with_note("", [note, selected_note]).strip()
            export = self.service.export(request, _context(params))
            return _ok({"export": export}, _with_note(_exported(export), [note]))
        except Exception as exc:
            return _error(exc)

    def create_grafana_draft(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare a temporary Grafana dashboard draft. ONLY when the user explicitly asks for Grafana or to create a dashboard; never for a chart request. Filters and scope='current_device' only when the user asked for them (devices named, or 'my/this device'): otherwise omit them so every dashboard variable starts on All.
        First reuses a maintained dashboard panel if one already answers the request. Otherwise writes
        tmp/atlas-grafana/<request-id>/dashboard.json from catalog queries only and pushes it into the temporary
        'Atlas drafts' Grafana folder (returns the link). Never provisions: the user keeps it manually. Drafts expire (default 24 h).
        Canvases (2+ panels) get this automatically from render_analytics_artifact; do not call this for them. The
        grafana-dashboard skill calls it ONCE with title and panels=[...] (shared filters/time_range_days at the top
        level); the draft starts from the platform dashboard template and filters on device/host/userinterface/
        environment/tag become dashboard variables.

        Example: create_grafana_draft(source_id='script_results', dimensions=['device_name'], metrics=['pass_rate','run_count'], mark='bar')

        Args:
            params: {
                'preset': str (OPTIONAL - dashboard-equivalent template: PRESET_IDS),
                'source_id': str (OPTIONAL - required when preset and panels are omitted; one of: SOURCE_IDS),
                'dimensions': list (OPTIONAL - allowlisted fields),
                'metrics': list (OPTIONAL - allowlisted metrics),
                'filters': dict (OPTIONAL - allowlisted filters),
                'scope': str (OPTIONAL - visible (default) or current_device),
                'time_grain': str (OPTIONAL - hour, day, week or month),
                'mark': str (OPTIONAL - chart mark; radar/heatmap/scatter fall back to core panels),
                'title': str (OPTIONAL - dashboard title),
                'panels': list (OPTIONAL - 1 to 6 panel requests),
                'time_range_days': int (OPTIONAL - default dashboard range),
                'ttl_hours': int (OPTIONAL - draft lifetime, default 24, maximum 168),
                'prefer_existing': bool (OPTIONAL - default true; false always writes a draft)
            }

        Returns:
            Either the maintained dashboard to reuse, or the draft path, expiry, validation and diagnostics.
        """
        try:
            request, named_note, blocked = enforce_named_devices(_request(params), _named(params))
            if blocked:
                return _ok({"named_devices_blocked": True}, blocked)
            request, selected_note = enforce_selected_device(request, params, _named(params))
            named_note = _with_note("", [named_note, selected_note]).strip()
            context = _context(params)
            request, context = self.service.resolve_draft_request(request, context)
            result = self.drafts.create(request, context)
            if result["status"] == "reused":
                maintained = result["maintained"]
                return _ok({"draft": result}, f"Reuse maintained dashboard {maintained['dashboard_title']} → {maintained['panel_title']}.")
            message = f"Grafana draft written to {result['draft_path']} (expires {result['expires_at']})."
            try:
                # Push the dashboard that was just validated; the file stays as the manual-promotion copy.
                pushed = self.publisher.publish({**request, "prefer_existing": False}, context)
                result["grafana"] = pushed
                message += f" Open in Grafana: {link_for_reply(pushed['path'], params.get('_context_grafana_base_url'))} (expires {pushed.get('expires_at') or result['expires_at']})."
                message += _dashboard_summary(result)
            except (AnalyticsValidationError, GrafanaPushError) as exc:
                message += f" Grafana draft not pushed: {_draft_note(exc)}"
            return _ok({"draft": result}, _with_note(message, [named_note]))
        except Exception as exc:
            return _error(exc)

    def query_kpi_radar(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Shortcut for the KPI Measurement radar; equivalent to render_analytics_artifact(preset='kpi_radar').

        Example: query_kpi_radar(userinterface_name='stb_tv', time_range_days=30, variants=['Base','variant1'])

        Args:
            params: {
                'userinterface_name': str (REQUIRED - user interface name),
                'time_range_days': int (OPTIONAL - trailing days),
                'from_time': str (OPTIONAL - ISO-8601 lower bound),
                'to_time': str (OPTIONAL - ISO-8601 upper bound),
                'variants': list (OPTIONAL - variant series; exactly two = baseline then candidate, compared automatically),
                'device_models': list (OPTIONAL - device models),
                'action_sets': list (OPTIONAL - action-set ids),
                'environments': list (OPTIONAL - dev, test, prod),
                'flags': list (OPTIONAL - device flags),
                'comparison': dict (OPTIONAL - COMPARISON_HELP)
            }

        Returns:
            KPI radar artifact using the same semantic source and grammar as dynamic charts.
        """
        filters = {"userinterface_name": params.get("userinterface_name")}
        for incoming, field in (("variants", "variant"), ("device_models", "device_model"),
                                ("action_sets", "action_set_id"), ("environments", "environment"), ("flags", "flags")):
            if params.get(incoming):
                filters[field] = params[incoming]
        request = {key: params[key] for key in ("time_range_days", "from_time", "to_time", "comparison") if params.get(key)}
        variants = params.get("variants") or []
        if isinstance(variants, list) and len(variants) == 2:
            # Two variants asked for = a comparison; hand the model computed deltas instead of
            # letting it diff the radar rows by hand (live: it missed a +99% regression), and
            # fill a partial comparison (live: only a threshold was sent).
            given = request.get("comparison") if isinstance(request.get("comparison"), dict) else {}
            request["comparison"] = {"baseline": variants[0], "candidate": variants[1], **given}
        request.update({"preset": "kpi_radar", "filters": filters})
        try:
            artifact = self.service.render(request, _context(params))
            data = artifact["content_data"]["artifact_spec"]["data"]
            return _ok({"rows": data["rows"], "artifact": artifact}, _shown(artifact))
        except Exception as exc:
            return _error(exc)


# The model-facing schema names every valid preset and source, generated from the catalog,
# so Atlas does not guess ids such as "test_results" before listing the catalog.
_IDS = {"PRESET_IDS": ", ".join(ARTIFACT_PRESETS), "SOURCE_IDS": ", ".join(ANALYTICS_SOURCES),
        "COMPARISON_HELP": COMPARISON_HELP_TEXT}
for _name in ANALYTICS_TOOL_NAMES:
    _method = getattr(AnalyticsTools, _name)
    for _token, _value in _IDS.items():
        _method.__doc__ = _method.__doc__.replace(_token, _value)
