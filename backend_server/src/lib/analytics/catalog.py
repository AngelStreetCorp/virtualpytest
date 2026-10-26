"""Allowlisted analytics sources and reusable artifact templates.

SQL fragments in this module are application code, never model input.  The public
catalog returned to Atlas deliberately omits the fragments and credentials.

Two query-scoped CTEs are available to every fragment:

* ``ads(device_key)`` — the caller's ``grafana_device_scope`` result (``'*'``, ``'-'``
  or ``host:device`` keys), materialized once per query.
* ``b(range_from, range_to)`` — the trusted time bounds of a time-bounded source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class Field:
    expression: str
    kind: str = "string"
    filterable: bool = True
    unit: Optional[str] = None


@dataclass(frozen=True)
class Metric:
    expression: str
    unit: Optional[str] = None
    kind: str = "number"
    # "lower" / "higher" when a change in one direction is a regression whatever the caller says.
    better: Optional[str] = None

    @property
    def preferred(self) -> Optional[str]:
        if self.better:
            return self.better
        return "lower" if self.unit in {"ms", "s", "min"} else None


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    description: str
    relation: str
    time_expression: Optional[str]
    dimensions: Mapping[str, Field]
    metrics: Mapping[str, Metric]
    team_expression: Optional[str]
    host_expression: Optional[str]
    device_expression: Optional[str]
    device_key_kind: Optional[str] = "name"
    default_dimensions: Tuple[str, ...] = field(default_factory=tuple)
    default_metrics: Tuple[str, ...] = field(default_factory=tuple)
    dashboard_refs: Tuple[str, ...] = field(default_factory=tuple)
    live: bool = False
    family: str = ""
    # Static predicates that define the dataset (e.g. one network test family).
    base_predicates: Tuple[str, ...] = field(default_factory=tuple)
    # Overrides the default ``time >= range_from AND time <= range_to`` (interval overlap).
    time_predicate: Optional[str] = None
    # Infrastructure-wide tables with no tenant or device column are admin-only.
    required_role: Optional[str] = None
    # Server-level tables are narrowed to the selected server by name.
    server_expression: Optional[str] = None


def _f(expression: str, kind: str = "string", *, unit: Optional[str] = None) -> Field:
    return Field(expression, kind, True, unit)


def _opaque(expression: str, kind: str = "string") -> Field:
    """Selectable but not filterable (free text, JSON or URLs)."""
    return Field(expression, kind, False)


def _rate(predicate: str) -> Metric:
    return Metric(f"ROUND(100.0 * COUNT(*) FILTER (WHERE {predicate}) / NULLIF(COUNT(*), 0), 2)", "%", better="higher")


def _avg_meta(alias: str, key: str, unit: str, digits: int = 2) -> Metric:
    return Metric(f"ROUND(AVG(NULLIF({alias}.metadata->>'{key}', '')::numeric), {digits})", unit)


def _scope_key(host: str, device: str) -> str:
    return f"EXISTS (SELECT 1 FROM ads WHERE ads.device_key = '*' OR ads.device_key = {host} || ':' || {device})"


# KPI labels follow the KPI Measurement dashboard: display label, then the action-set
# KPI name, then the edge label, then the raw action-set id.
_KPI_RELATION = (
    "execution_results er JOIN navigation_trees nt ON nt.id = er.tree_id AND nt.team_id = er.team_id "
    "JOIN userinterfaces ui ON ui.id = nt.userinterface_id AND ui.team_id = er.team_id "
    "LEFT JOIN script_results sr ON sr.id = er.script_result_id AND sr.team_id = er.team_id "
    "LEFT JOIN device_info_corrected dic ON dic.team_id = er.team_id AND dic.host_name = er.host_name "
    "AND dic.device_name = er.device_name "
    "LEFT JOIN LATERAL (SELECT a->>'label' edge_label, a->>'kpi_name' kpi_name, "
    "NULLIF(a->>'threshold', '')::int threshold "
    "FROM navigation_edges ne, jsonb_array_elements(ne.action_sets) a "
    "WHERE ne.tree_id = er.tree_id AND ne.edge_id = regexp_replace(er.edge_id, '_reverse$', '') "
    "AND a->>'id' = er.action_set_id LIMIT 1) lbl ON true"
)

_EXECUTION_DIMENSIONS = {
    "time": _f("er.executed_at", "time"), "variant": _f("COALESCE(er.variant, 'Base')"),
    "action_set_id": _f("er.action_set_id"),
    "kpi_name": _f("COALESCE(NULLIF(er.kpi_display_label, ''), NULLIF(lbl.kpi_name, ''), NULLIF(lbl.edge_label, ''), er.action_set_id)"),
    "userinterface_name": _f("ui.name"), "device_model": _f("COALESCE(er.device_model, 'unknown')"),
    "host_name": _f("er.host_name"), "device_name": _f("er.device_name"),
    "environment": _f("sr.environment"), "success": _f("er.success", "boolean"),
    "is_test": _f("er.is_test", "boolean"), "execution_type": _f("er.execution_type"),
    "stb_model": _f("COALESCE(dic.info_corrected->>'serial_number_stb', dic.info_corrected->>'seriennummer_stb')"),
    "stb_software": _f("COALESCE(dic.info_corrected->>'software_version', dic.info_corrected->>'softwareversion')"),
}

# Gateway enrichment mirrors the network dashboards: the newest scoped gateway info row
# of the same host, ``Unknown`` when there is none.
_GATEWAY_RELATION = (
    "script_results sr LEFT JOIN LATERAL (SELECT g.technology, g.network_type, g.modem_name, g.firmware_version "
    "FROM gw_info_latest g WHERE g.team_id = sr.team_id AND g.host_name = sr.host_name AND "
    + _scope_key("g.host_name", "g.device_name")
    + " ORDER BY g.started_at DESC LIMIT 1) gw ON true"
)


def _network_dimensions(**extra: Field) -> Dict[str, Field]:
    dims = {
        "time": _f("sr.started_at", "time"), "host_name": _f("sr.host_name"), "device_name": _f("sr.device_name"),
        "environment": _f("sr.environment"), "success": _f("sr.success", "boolean"),
        "gateway_technology": _f("COALESCE(gw.technology, 'Unknown')"),
        "gateway_network_type": _f("COALESCE(gw.network_type, 'Unknown')"),
        "gateway_model": _f("COALESCE(gw.modem_name, 'Unknown')"),
        "gateway_firmware": _f("COALESCE(gw.firmware_version, 'Unknown')"),
    }
    dims.update(extra)
    return dims


_NETWORK_COUNTS = {
    "test_count": Metric("COUNT(*)"), "failure_count": Metric("COUNT(*) FILTER (WHERE sr.success = false)"),
    "success_rate": _rate("sr.success"),
}


ANALYTICS_SOURCES: Dict[str, Source] = {
    "script_results": Source(
        "script_results", "Script and testcase results",
        "Script/testcase outcomes, durations and review state.", "script_results sr",
        "sr.started_at",
        {"time": _f("sr.started_at", "time"), "script_name": _f("sr.script_name"),
         "script_type": _f("sr.script_type"), "userinterface_name": _f("sr.userinterface_name"),
         "variant": _f("COALESCE(sr.metadata->>'variant', 'base')"), "host_name": _f("sr.host_name"),
         "device_name": _f("sr.device_name"), "environment": _f("sr.environment"),
         "success": _f("sr.success", "boolean"), "checked": _f("sr.checked", "boolean"),
         "discard": _f("sr.discard", "boolean"), "error_message": _opaque("sr.error_msg")},
        {"run_count": Metric("COUNT(*)"), "pass_count": Metric("COUNT(*) FILTER (WHERE sr.success)"),
         "failure_count": Metric("COUNT(*) FILTER (WHERE NOT sr.success)"),
         "pass_rate": _rate("sr.success"),
         "avg_duration_ms": Metric("ROUND(AVG(sr.execution_time_ms))", "ms"),
         "total_duration_min": Metric("ROUND(SUM(sr.execution_time_ms)::numeric / 60000, 2)", "min"),
         "last_run_at": Metric("MAX(sr.started_at)", kind="time")},
        "sr.team_id", "sr.host_name", "sr.device_name", "name", ("device_name",),
        ("run_count", "pass_rate"), ("script-results.json", "TestReports.tsx", "virtualpytest-self-test.json",
                                     "game-2048.json", "discard-scripts-reviewed.json"),
        family="script"),
    "campaign_results": Source(
        "campaign_results", "Campaign results", "Campaign run outcomes and duration.", "campaign_executions ce",
        "ce.started_at",
        {"time": _f("ce.started_at", "time"), "campaign_name": _f("COALESCE(ce.campaign_name, 'No Campaign')"),
         "userinterface_name": _f("ce.userinterface_name"), "host_name": _f("ce.host_name"),
         "device_name": _f("ce.device_name"), "status": _f("ce.status"),
         "success": _f("ce.success", "boolean")},
        {"run_count": Metric("COUNT(*)"), "pass_count": Metric("COUNT(*) FILTER (WHERE ce.success)"),
         "failure_count": Metric("COUNT(*) FILTER (WHERE NOT ce.success)"),
         "pass_rate": _rate("ce.success"),
         "avg_duration_ms": Metric("ROUND(AVG(ce.execution_time_ms))", "ms"),
         "last_run_at": Metric("MAX(ce.started_at)", kind="time")},
        "ce.team_id", "ce.host_name", "ce.device_name", "name", ("campaign_name",),
        ("run_count", "pass_rate"), ("campaign-results.json", "TestReports.tsx"), family="script"),
    "deployment_results": Source(
        "deployment_results", "Deployment results", "Scheduled deployment execution outcomes.",
        "deployment_executions de JOIN deployments d ON d.id = de.deployment_id", "COALESCE(de.started_at, de.scheduled_at)",
        {"time": _f("COALESCE(de.started_at, de.scheduled_at)", "time"), "deployment_name": _f("d.name"),
         "script_name": _f("d.script_name"), "userinterface_name": _f("d.userinterface_name"),
         "host_name": _f("d.host_name"), "device_id": _f("d.device_id"),
         "environment": _f("d.environment"), "status": _f("de.status"), "success": _f("de.success", "boolean"),
         "skip_reason": _opaque("de.skip_reason")},
        {"run_count": Metric("COUNT(*)"), "pass_count": Metric("COUNT(*) FILTER (WHERE de.success)"),
         "failure_count": Metric("COUNT(*) FILTER (WHERE de.success = false)"),
         "skipped_count": Metric("COUNT(*) FILTER (WHERE de.status = 'skipped')"),
         "pass_rate": _rate("de.success"),
         "avg_duration_s": Metric("ROUND(AVG(EXTRACT(EPOCH FROM (de.completed_at - de.started_at)))::numeric, 1)", "s"),
         "last_run_at": Metric("MAX(COALESCE(de.started_at, de.scheduled_at))", kind="time")},
        "d.team_id", "d.host_name", "d.device_id", "id", ("deployment_name",), ("run_count", "pass_rate"),
        ("deployment-table.json",), family="script"),
    "execution_metrics": Source(
        "execution_metrics", "Navigation execution metrics",
        "Per-step navigation outcomes and durations (all steps, with or without a KPI).",
        _KPI_RELATION, "er.executed_at", _EXECUTION_DIMENSIONS,
        {"sample_count": Metric("COUNT(*)"), "success_count": Metric("COUNT(*) FILTER (WHERE er.success)"),
         "failure_count": Metric("COUNT(*) FILTER (WHERE NOT er.success)"),
         "success_rate": _rate("er.success"),
         "avg_duration_ms": Metric("ROUND(AVG(er.execution_time_ms))", "ms")},
        "er.team_id", "er.host_name", "er.device_name", "name", ("userinterface_name",),
        ("sample_count", "success_rate"), ("navigation-metrics.json",), family="kpi"),
    "kpi_measurements": Source(
        "kpi_measurements", "Visual KPI measurements",
        "Measured KPI timings per user interface, KPI, variant and model (KPI Measurement semantics).",
        _KPI_RELATION, "er.executed_at", _EXECUTION_DIMENSIONS,
        {"sample_count": Metric("COUNT(*)"), "success_count": Metric("COUNT(*) FILTER (WHERE er.success)"),
         "failure_count": Metric("COUNT(*) FILTER (WHERE NOT er.success)"),
         "success_rate": _rate("er.success"),
         "avg_kpi_ms": Metric("ROUND(AVG(er.kpi_measurement_ms))", "ms"),
         "min_kpi_ms": Metric("MIN(er.kpi_measurement_ms)", "ms"), "max_kpi_ms": Metric("MAX(er.kpi_measurement_ms)", "ms"),
         # The dashboard's KPI identity is the action set; its label is aggregated per group.
         "kpi_label": Metric("COALESCE(MAX(NULLIF(er.kpi_display_label, '')), MAX(NULLIF(lbl.kpi_name, '')), "
                             "MAX(NULLIF(lbl.edge_label, '')), MAX(er.action_set_id))", kind="string"),
         "p90_kpi_ms": Metric("ROUND((percentile_cont(0.9) WITHIN GROUP (ORDER BY er.kpi_measurement_ms))::numeric)", "ms"),
         "threshold_ms": Metric("MAX(lbl.threshold)", "ms"),
         "over_threshold_count": Metric("COUNT(*) FILTER (WHERE er.success AND COALESCE(lbl.threshold, 0) > 0 "
                                        "AND er.kpi_measurement_ms > lbl.threshold)")},
        "er.team_id", "er.host_name", "er.device_name", "name", ("kpi_name", "variant"),
        ("avg_kpi_ms", "sample_count"), ("kpi-measurement.json", "kpi-test-report.json"),
        family="kpi", base_predicates=("er.kpi_measurement_ms IS NOT NULL",)),
    "zapping": Source(
        "zapping", "Zapping", "Channel-zap timings and blackscreen/freeze/audio observations.", "zap_results zr",
        "zr.created_at",
        {"time": _f("zr.created_at", "time"),
         "host_name": _f("zr.host_name"), "device_name": _f("zr.device_name"),
         "device_model": _f("zr.device_model"), "userinterface_name": _f("zr.userinterface_name"),
         "channel_name": _f("zr.channel_name"), "channel_number": _f("zr.channel_number"),
         "transition_type": _f("zr.transition_type"), "detection_method": _f("zr.detection_method"),
         "blackscreen_freeze_detected": _f("zr.blackscreen_freeze_detected", "boolean")},
        {"zap_count": Metric("COUNT(*)"), "avg_zap_ms": Metric("ROUND(AVG(zr.total_zap_duration_ms))", "ms"),
         "avg_transition_ms": Metric("ROUND(AVG(zr.blackscreen_freeze_duration_seconds * 1000))", "ms"),
         "avg_audio_silence_s": Metric("ROUND(AVG(zr.audio_silence_duration)::numeric, 2)", "s"),
         "freeze_count": Metric("COUNT(*) FILTER (WHERE zr.blackscreen_freeze_detected)")},
        "zr.team_id", "zr.host_name", "zr.device_name", "name", ("device_name",), ("zap_count", "avg_zap_ms"),
        ("all-zapping-events.json", "fullzap-results.json"), family="script"),
    "alerts": Source(
        "alerts", "Alerts and incidents", "Active/resolved device monitoring incidents.", "alerts a", "a.start_time",
        {"time": _f("a.start_time", "time"), "host_name": _f("a.host_name"), "device_id": _f("a.device_id"),
         "device_name": _f("a.device_name"), "incident_type": _f("a.incident_type"), "status": _f("a.status"),
         "checked": _f("a.checked", "boolean"), "discard": _f("a.discard", "boolean")},
        {"incident_count": Metric("COUNT(*)"), "active_count": Metric("COUNT(*) FILTER (WHERE a.status = 'active')"),
         "resolved_count": Metric("COUNT(*) FILTER (WHERE a.status = 'resolved')"),
         "avg_duration_s": Metric("ROUND(AVG(EXTRACT(EPOCH FROM (COALESCE(a.end_time, NOW()) - a.start_time))))", "s"),
         "last_started_at": Metric("MAX(a.start_time)", kind="time")},
        None, "a.host_name", "a.device_id", "id", ("incident_type", "status"), ("incident_count",),
        ("device-alerts-dashboard.json", "discard-incidents-reviewed.json"), family="alerts"),
    "fleet_health": Source(
        "fleet_health", "Fleet health history", "Historical nightly/live device health verdicts.",
        "fleet_health fh", "fh.generated_at",
        {"time": _f("fh.generated_at", "time"), "server": _f("fh.server"), "host_name": _f("fh.host_name"),
         "device_id": _f("fh.device_id"), "device_name": _f("COALESCE(fh.device_name, fh.device_id)"),
         "device_model": _f("fh.device_model"), "verdict": _f("fh.verdict"), "run_kind": _f("fh.run_kind")},
        {"device_count": Metric("COUNT(*)"), "degraded_count": Metric("COUNT(*) FILTER (WHERE fh.verdict = 'DEGRADED')"),
         "down_count": Metric("COUNT(*) FILTER (WHERE fh.verdict = 'DOWN')"),
         "healthy_rate": _rate("fh.verdict IN ('OK','IDLE')")},
        None, "fh.host_name", "fh.device_id", "id", ("verdict",), ("device_count",), ("vpt-fleet-health.json",),
        family="alerts"),
    # Latest verdicts: rows of the newest scoped check per run kind, as the dashboard's
    # "Live — per device" / "Last night — per device" panels.
    "fleet_health_latest": Source(
        "fleet_health_latest", "Latest fleet health", "Device verdicts from the newest live/nightly fleet check.",
        "(SELECT f.*, max(f.generated_at) OVER (PARTITION BY f.run_kind) AS latest_generated_at "
        "FROM fleet_health f WHERE " + _scope_key("f.host_name", "f.device_id") + ") fh",
        None,
        {"server": _f("fh.server"), "host_name": _f("fh.host_name"), "device_id": _f("fh.device_id"),
         "device_name": _f("COALESCE(fh.device_name, fh.device_id)"), "device_model": _f("fh.device_model"),
         "verdict": _f("fh.verdict"), "run_kind": _f("fh.run_kind"), "reason": _opaque("fh.reason"),
         "checked_at": _opaque("fh.generated_at", "time"), "issue_since": _opaque("fh.issue_since", "time")},
        {"device_count": Metric("COUNT(*)"), "ok_count": Metric("COUNT(*) FILTER (WHERE fh.verdict = 'OK')"),
         "idle_count": Metric("COUNT(*) FILTER (WHERE fh.verdict = 'IDLE')"),
         "degraded_count": Metric("COUNT(*) FILTER (WHERE fh.verdict = 'DEGRADED')"),
         "down_count": Metric("COUNT(*) FILTER (WHERE fh.verdict = 'DOWN')"),
         "unknown_count": Metric("COUNT(*) FILTER (WHERE fh.verdict = 'UNKNOWN')")},
        None, "fh.host_name", "fh.device_id", "id", ("verdict",), ("device_count",), ("vpt-fleet-health.json",),
        family="alerts", base_predicates=("fh.generated_at = fh.latest_generated_at",)),
    "device_occupancy": Source(
        "device_occupancy", "Device occupancy", "Durable manual/script/deployment device lock sessions.",
        "device_control_sessions dcs", "dcs.started_at",
        {"time": _f("dcs.started_at", "time"), "host_name": _f("dcs.host_name"), "device_id": _f("dcs.device_id"),
         "device": _f("dcs.host_name || ':' || dcs.device_id"), "owner_type": _f("dcs.owner_type"),
         "end_reason": _f("dcs.end_reason"), "open": _f("dcs.ended_at IS NULL", "boolean")},
        {"session_count": Metric("COUNT(*)"),
         "occupied_seconds": Metric("ROUND(EXTRACT(EPOCH FROM SUM(LEAST(COALESCE(dcs.ended_at, NOW()), b.range_to) "
                                    "- GREATEST(dcs.started_at, b.range_from))))", "s"),
         "occupancy_percent": Metric("ROUND((100.0 * EXTRACT(EPOCH FROM SUM(LEAST(COALESCE(dcs.ended_at, NOW()), b.range_to) "
                                     "- GREATEST(dcs.started_at, b.range_from))) / NULLIF(EXTRACT(EPOCH FROM "
                                     "(MAX(b.range_to) - MAX(b.range_from))), 0))::numeric, 2)", "%"),
         "open_count": Metric("COUNT(*) FILTER (WHERE dcs.ended_at IS NULL)")},
        None, "dcs.host_name", "dcs.device_id", "id", ("device",), ("occupancy_percent",),
        ("device-occupancy.json",), family="occupancy",
        time_predicate="dcs.started_at < b.range_to AND COALESCE(dcs.ended_at, NOW()) > b.range_from"),
    "device_information": Source(
        "device_information", "Latest device information",
        "Latest device_get_info payloads with corrected model/software fields.",
        "device_info_latest di LEFT JOIN device_info_corrected dic ON dic.team_id = di.team_id "
        "AND dic.host_name = di.host_name AND dic.device_name = di.device_name "
        "AND dic.userinterface_name IS NOT DISTINCT FROM di.userinterface_name",
        "di.started_at",
        {"time": _f("di.started_at", "time"), "host_name": _f("di.host_name"), "device_name": _f("di.device_name"),
         "userinterface_name": _f("di.userinterface_name"),
         "model": _f("COALESCE(dic.info_corrected->>'model', dic.info_corrected->>'serial_number_stb', "
                     "dic.info_corrected->>'seriennummer_stb')"),
         "software_version": _f("COALESCE(dic.info_corrected->>'software_version', dic.info_corrected->>'softwareversion')"),
         "corrected": _f("COALESCE(dic.has_override, false)", "boolean"),
         "info": _opaque("COALESCE(dic.info_corrected, di.info)", "json")},
        {"device_count": Metric("COUNT(*)"), "last_scanned_at": Metric("MAX(di.started_at)", kind="time")},
        "di.team_id", "di.host_name", "di.device_name", "name",
        ("device_name",), ("device_count",), ("device-information-get-info.json",), family="occupancy"),
    "ookla_speedtest": Source(
        "ookla_speedtest", "Ookla speed tests", "Download/upload/latency results of ookla_speedtest runs.",
        _GATEWAY_RELATION, "sr.started_at",
        _network_dimensions(server_location=_f("sr.metadata->>'server_location'")),
        {**_NETWORK_COUNTS, "avg_download_mbps": _avg_meta("sr", "download_mbps", "Mbps"),
         "avg_upload_mbps": _avg_meta("sr", "upload_mbps", "Mbps"),
         "avg_latency_ms": _avg_meta("sr", "ping_latency_ms", "ms"),
         "avg_jitter_ms": _avg_meta("sr", "ping_jitter_ms", "ms"),
         "avg_packet_loss_percent": _avg_meta("sr", "packet_loss_percent", "%")},
        "sr.team_id", "sr.host_name", "sr.device_name", "name", ("host_name",),
        ("test_count", "avg_download_mbps"), ("ookla-speedtest.json", "home-dashboard.json"),
        family="network", base_predicates=("sr.script_name = 'ookla_speedtest'",)),
    "dns_lookup": Source(
        "dns_lookup", "DNS lookups", "Lookup time and success of dns_lookuptime runs.",
        _GATEWAY_RELATION, "sr.started_at",
        _network_dimensions(domain=_f("sr.metadata->>'domain'"), dns_server=_f("sr.metadata->>'dns_server'")),
        {**_NETWORK_COUNTS, "avg_lookup_ms": _avg_meta("sr", "lookup_time_ms", "ms", 1),
         "min_lookup_ms": Metric("ROUND(MIN(NULLIF(sr.metadata->>'lookup_time_ms', '')::numeric), 1)", "ms"),
         "max_lookup_ms": Metric("ROUND(MAX(NULLIF(sr.metadata->>'lookup_time_ms', '')::numeric), 1)", "ms")},
        "sr.team_id", "sr.host_name", "sr.device_name", "name", ("domain",),
        ("test_count", "success_rate"), ("dns-lookup.json", "home-dashboard.json"),
        family="network", base_predicates=("sr.script_name = 'dns_lookuptime'",)),
    "superping": Source(
        "superping", "Superping", "Round-trip, loss, jitter and score of superping runs.",
        _GATEWAY_RELATION, "sr.started_at",
        _network_dimensions(target=_f("sr.metadata->>'target'"), protocol=_f("sr.metadata->>'protocol'")),
        {**_NETWORK_COUNTS, "avg_score": _avg_meta("sr", "superping_score", "", 1),
         "avg_rtt_ms": _avg_meta("sr", "rtt_avg_ms", "ms"),
         "min_rtt_ms": Metric("ROUND(MIN(NULLIF(sr.metadata->>'rtt_min_ms', '')::numeric), 2)", "ms"),
         "max_rtt_ms": Metric("ROUND(MAX(NULLIF(sr.metadata->>'rtt_max_ms', '')::numeric), 2)", "ms"),
         "avg_jitter_ms": _avg_meta("sr", "jitter_ms", "ms"),
         "avg_packet_loss_percent": _avg_meta("sr", "packet_loss_percent", "%"),
         "reachable_rate": _rate("(sr.metadata->>'service_reachability')::boolean")},
        "sr.team_id", "sr.host_name", "sr.device_name", "name", ("target",),
        ("test_count", "avg_rtt_ms"), ("superping.json", "home-dashboard.json"),
        family="network", base_predicates=("sr.script_name = 'superping'",)),
    "historical_system_metrics": Source(
        "historical_system_metrics", "Historical host metrics", "Host CPU, memory, disk, network and temperature history.",
        "system_metrics sm", "sm.timestamp",
        {"time": _f("sm.timestamp", "time"), "server_name": _f("sm.server_name"), "host_name": _f("sm.host_name"),
         "platform": _f("sm.platform")},
        {"sample_count": Metric("COUNT(*)"), "avg_cpu_percent": Metric("ROUND(AVG(sm.cpu_percent)::numeric, 2)", "%"),
         "avg_memory_percent": Metric("ROUND(AVG(sm.memory_percent)::numeric, 2)", "%"),
         "avg_disk_percent": Metric("ROUND(AVG(sm.disk_percent)::numeric, 2)", "%"),
         "avg_temperature_c": Metric("ROUND(AVG(sm.cpu_temperature_celsius)::numeric, 2)", "C"),
         "avg_load_1m": Metric("ROUND(AVG(sm.load_average_1m)::numeric, 2)"),
         "avg_download_mbps": Metric("ROUND(AVG(sm.download_mbps)::numeric, 2)", "Mbps"),
         "avg_upload_mbps": Metric("ROUND(AVG(sm.upload_mbps)::numeric, 2)", "Mbps")},
        None, "sm.host_name", None, None, ("host_name",), ("avg_cpu_percent", "avg_memory_percent"),
        ("system-server-monitoring.json",), family="system"),
    "device_system_metrics": Source(
        "device_system_metrics", "Historical device host metrics",
        "Per-device host CPU, memory, disk, temperature and capture-service history.",
        "system_device_metrics sdm", "sdm.timestamp",
        {"time": _f("sdm.timestamp", "time"), "host_name": _f("sdm.host_name"), "device_id": _f("sdm.device_id"),
         "device_name": _f("sdm.device_name"), "device_model": _f("sdm.device_model"),
         "ffmpeg_status": _f("sdm.ffmpeg_status"), "monitor_status": _f("sdm.monitor_status")},
        {"sample_count": Metric("COUNT(*)"), "avg_cpu_percent": Metric("ROUND(AVG(sdm.cpu_percent)::numeric, 2)", "%"),
         "avg_memory_percent": Metric("ROUND(AVG(sdm.memory_percent)::numeric, 2)", "%"),
         "avg_disk_percent": Metric("ROUND(AVG(sdm.disk_percent)::numeric, 2)", "%"),
         "avg_temperature_c": Metric("ROUND(AVG(sdm.cpu_temperature_celsius)::numeric, 2)", "C"),
         "max_uptime_s": Metric("MAX(sdm.uptime_seconds)", "s")},
        None, "sdm.host_name", "sdm.device_id", "id", ("host_name",), ("avg_cpu_percent",),
        ("system-host-monitoring.json",), family="system",
        base_predicates=("sdm.host_name <> 'server'",)),
    "service_status": Source(
        "service_status", "Current platform service status",
        "Latest status of each monitored platform component (STALE after 3 minutes without a report).",
        "service_status_current ssc", None,
        {"server_name": _f("ssc.server_name"), "vm": _f("ssc.vm"), "component": _f("ssc.component"),
         "state": _f("CASE WHEN ssc.checked_at < now() - interval '3 minutes' THEN 'STALE' ELSE upper(ssc.status) END"),
         "detail": _opaque("ssc.detail"), "since": _opaque("ssc.since", "time"),
         "checked_at": _opaque("ssc.checked_at", "time")},
        {"component_count": Metric("COUNT(*)"),
         "not_ok_count": Metric("COUNT(*) FILTER (WHERE ssc.checked_at < now() - interval '3 minutes' "
                                "OR upper(ssc.status) <> 'OK')")},
        None, None, None, None, ("vm", "component", "state"), ("component_count",),
        ("system-service-status.json",), family="system", required_role="admin",
        server_expression="ssc.server_name"),
    "service_availability": Source(
        "service_availability", "Platform service availability",
        "Per-component availability over the range from status-change history (silent components count as down).",
        "(SELECT e.server_name, e.vm, e.component, e.status, "
        "GREATEST(e.t, b.range_from) AS span_from, "
        "LEAST(COALESCE(lead(e.t) OVER (PARTITION BY e.server_name, e.vm, e.component ORDER BY e.t), now()), "
        "b.range_to, now()) AS span_to "
        "FROM (SELECT server_name, vm, component, checked_at AS t, status FROM service_status "
        "UNION ALL SELECT server_name, vm, component, checked_at + interval '1 minute', 'down' "
        "FROM service_status_current WHERE checked_at < now() - interval '3 minutes') e, b "
        "WHERE e.t < b.range_to) sa",
        "sa.span_to",
        {"server_name": _f("sa.server_name"), "vm": _f("sa.vm"), "component": _f("sa.component"),
         "status": _f("sa.status")},
        {"availability_percent": Metric("ROUND((100.0 * COALESCE(SUM(EXTRACT(EPOCH FROM sa.span_to - sa.span_from)) "
                                        "FILTER (WHERE sa.status = 'ok'), 0) / NULLIF(SUM(EXTRACT(EPOCH FROM "
                                        "sa.span_to - sa.span_from)), 0))::numeric, 2)", "%", better="higher"),
         "minutes_not_ok": Metric("ROUND((COALESCE(SUM(EXTRACT(EPOCH FROM sa.span_to - sa.span_from)) "
                                  "FILTER (WHERE sa.status <> 'ok'), 0) / 60)::numeric)", "min"),
         "times_not_ok": Metric("COUNT(*) FILTER (WHERE sa.status <> 'ok')")},
        None, None, None, None, ("vm", "component"), ("availability_percent",),
        ("system-service-status.json",), family="system", required_role="admin",
        server_expression="sa.server_name",
        base_predicates=("sa.span_to > sa.span_from", "sa.status NOT IN ('unknown', 'stopped')"),
        time_predicate="sa.span_to > b.range_from"),
    "live_system_status": Source(
        "live_system_status", "Live server, host, device and service status",
        "Current registry/status path; this is not historical PostgreSQL data.", "", None,
        {"host_name": _f("", "string"), "host_status": _f("", "string"),
         "device_id": _f("", "string"), "device_name": _f("", "string"),
         "device_model": _f("", "string"), "device_status": _f("", "string")},
        {}, None, None, None,
        None, dashboard_refs=("Dashboard.tsx", "system-service-status.json"), live=True, family="system"),

    # ---------------------------------------------------------------------------
    # TASK-115: matcher history (match_runs) + the auto-classify counter
    # (screen_fingerprints).  Three sources, all read-only, all the
    # operator-facing views of the live matcher's behaviour.
    # ---------------------------------------------------------------------------
    "match_runs": Source(
        "match_runs", "Matcher history (verify, localize, monitor)",
        "One row per matcher run across all sources.  Carries the top-3 candidates, "
        "the runner-up margin, the previous event on the same device and the dhash of "
        "the captured frame.  Use the 'uncertain' metric (runner_up_margin < 0.05) to "
        "spot borderline matches; the 'matched' metric for the confident wins.",
        "match_runs mr",
        "mr.started_at",
        {"time": _f("mr.started_at", "time"),
         "userinterface_name": _f("mr.userinterface_name"),
         "host_name": _f("mr.host_name"),
         "device_id": _f("mr.device_id"),
         "device_name": _f("mr.device_name"),
         "device_model": _f("mr.device_model"),
         "source": _f("mr.source"),
         "variant": _f("mr.variant"),
         "verdict": _f("mr.verdict"),
         "matched_node_id": _f("mr.matched_node_id"),
         "matched_node_label": _f("(mr.candidates_top_3->0->>'label')"),
         "runner_up_node_label": _f("(mr.candidates_top_3->1->>'label')"),
         "floor_hit": _f("mr.candidate_floor_hit", "boolean")},
        {"run_count": Metric("COUNT(*)"),
         "matched_count": Metric("COUNT(*) FILTER (WHERE mr.verdict = 'known_node')"),
         "unknown_count": Metric("COUNT(*) FILTER (WHERE mr.verdict = 'unknown')"),
         "low_confidence_count": Metric("COUNT(*) FILTER (WHERE mr.verdict = 'low_confidence')"),
         "no_signal_count": Metric("COUNT(*) FILTER (WHERE mr.verdict = 'no_signal')"),
         "uncertain_count": Metric("COUNT(*) FILTER (WHERE mr.runner_up_margin < 0.05 AND mr.verdict = 'known_node')"),
         "avg_confidence": Metric("ROUND(AVG(mr.matched_confidence)::numeric, 3)"),
         "avg_runner_up_margin": Metric("ROUND(AVG(mr.runner_up_margin)::numeric, 3)"),
         "avg_elapsed_ms": Metric("ROUND(AVG(mr.elapsed_ms))", "ms"),
         "last_run_at": Metric("MAX(mr.started_at)", kind="time")},
        "mr.team_id", "mr.host_name", "mr.device_name", "id",
        ("userinterface_name", "source"),
        ("run_count", "matched_count", "uncertain_count"),
        ("fingerprints.json",), family="matcher"),
    "node_transitions": Source(
        "node_transitions", "Node transition matrix (P to_node | from_node)",
        "Aggregated by v_node_transitions: the number of times a matcher run on "
        "from_node_id was followed by a match on to_node_id, on the same device and "
        "userinterface.  Drives prediction ('where is this device going next?') and "
        "highlights never-observed transitions for the operator to fingerprint.",
        "v_node_transitions vt",
        "vt.last_seen_at",
        {"time": _f("vt.last_seen_at", "time"),
         "userinterface_name": _f("vt.userinterface_name"),
         "from_node_id": _f("vt.from_node_id"),
         "to_node_id": _f("vt.to_node_id")},
        {"occurrences": Metric("SUM(vt.occurrences)"),
         "uncertain_occurrences": Metric("SUM(vt.uncertain_occurrences)"),
         "last_seen_at": Metric("MAX(vt.last_seen_at)", kind="time")},
        "vt.team_id", "vt.device_id", None, None,
        ("from_node_id", "to_node_id"),
        ("occurrences",),
        ("fingerprints.json",), family="matcher"),
    "screen_fingerprints_counter": Source(
        "screen_fingerprints_counter", "Unknown screen counter (the 'big counter' rule)",
        "The screen_fingerprints rows fed by the live matcher, with the auto-classify "
        "scheduler's view.  verdict='unknown' is the backlog; seen_count is the "
        "'big counter' (rows above the auto-classify threshold get a name proposed); "
        "classification_attempts bounds how many times the AI tried before giving up.",
        "screen_fingerprints sf",
        "sf.last_seen",
        {"time": _f("sf.last_seen", "time"),
         "scope": _f("sf.scope"),
         "verdict": _f("sf.verdict"),
         "dhash": _f("sf.dhash")},
        {"row_count": Metric("COUNT(*)"),
         "above_threshold": Metric("COUNT(*) FILTER (WHERE sf.seen_count >= 5)"),
         "exhausted_attempts": Metric("COUNT(*) FILTER (WHERE sf.classification_attempts >= 3)"),
         "total_seen": Metric("SUM(sf.seen_count)"),
         "last_seen_at": Metric("MAX(sf.last_seen)", kind="time")},
        "sf.team_id", "split_part(sf.scope, '/', 1)", None, None,
        ("verdict",),
        ("row_count", "above_threshold"),
        ("fingerprints.json",), family="matcher",
        base_predicates=("sf.merged_into IS NULL",)),
}


# Presets are dashboard-equivalent templates over the catalog above; they only choose
# fields, defaults and a mark, so they share every guardrail of a dynamic artifact.
# Keys: source, title, description, mark, dimensions, metrics, optional required_filters,
# default_filters, time_grain, sort, limit, time_range_days, category, series,
# max_categories, max_series, overflow/rank_by (radar top-N reduction), dashboard_ref
# and dashboard_panel.
ARTIFACT_PRESETS: Dict[str, Dict[str, Any]] = {
    # --- KPI ---------------------------------------------------------------------------
    "kpi_radar": {
        "source": "kpi_measurements", "title": "KPI Measurement radar", "mark": "radar",
        "description": "Average KPI per action set (labelled), one series per variant.",
        "dimensions": ["action_set_id", "variant"], "metrics": ["kpi_label", "avg_kpi_ms", "sample_count"],
        "category": "kpi_label", "series": "variant", "default_filters": {"environment": ["dev", "test", "prod"]},
        "required_filters": ["userinterface_name"], "max_categories": 20, "max_series": 6,
        "overflow": "top", "rank_by": "sample_count",
        "dashboard_ref": "kpi-measurement.json", "dashboard_panel": "<ui> radar",
    },
    "kpi_trend": {
        "source": "kpi_measurements", "title": "KPI evolution", "mark": "line",
        "description": "Daily average KPI per action set for one user interface.",
        "dimensions": ["time", "action_set_id"], "metrics": ["kpi_label", "avg_kpi_ms", "sample_count"],
        "series": "kpi_label", "time_grain": "day", "default_filters": {"environment": ["dev", "test", "prod"]},
        "required_filters": ["userinterface_name"], "sort": [{"field": "time", "direction": "asc"}],
        "dashboard_ref": "kpi-measurement.json", "dashboard_panel": "<ui> - KPI Evolution",
    },
    "kpi_slowest": {
        "source": "kpi_measurements", "title": "Slowest KPIs", "mark": "table",
        "description": "KPIs ranked by average measurement with threshold breaches.",
        "dimensions": ["action_set_id", "variant", "device_model"],
        "metrics": ["kpi_label", "avg_kpi_ms", "max_kpi_ms", "threshold_ms", "over_threshold_count", "sample_count"],
        "default_filters": {"environment": ["dev", "test", "prod"]},
        "required_filters": ["userinterface_name"], "sort": [{"field": "avg_kpi_ms", "direction": "desc"}],
        "limit": 20, "dashboard_ref": "kpi-measurement.json", "dashboard_panel": "<ui> - Top Slowest",
    },
    # --- script / campaign / deployment ----------------------------------------------
    "failing_testcases": {
        "source": "script_results", "title": "Failing testcases", "mark": "table",
        "description": "Failed scripts/testcases with failure counts and last failure time.",
        "dimensions": ["script_name", "userinterface_name", "host_name", "device_name"],
        "metrics": ["failure_count", "last_run_at"], "default_filters": {"success": [False]},
        "sort": [{"field": "failure_count", "direction": "desc"}],
        "dashboard_ref": "script-results.json", "dashboard_panel": "Script results (FAIL)",
    },
    "pass_rate_by_device": {
        "source": "script_results", "title": "Pass rate by device", "mark": "bar",
        "default_filters": {"success": [True, False]},
        "description": "Pass rate per device with run counts.",
        "dimensions": ["device_name"], "metrics": ["pass_rate", "run_count"], "max_categories": 30,
        "sort": [{"field": "device_name", "direction": "asc"}], "dashboard_ref": "script-results.json",
    },
    "pass_rate_by_script": {
        "source": "script_results", "title": "Pass rate by script", "mark": "bar",
        "default_filters": {"success": [True, False]},
        "description": "Pass rate per script with run counts.",
        "dimensions": ["script_name"], "metrics": ["pass_rate", "run_count"], "max_categories": 30,
        "sort": [{"field": "run_count", "direction": "desc"}], "dashboard_ref": "script-results.json",
    },
    "pass_rate_trend": {
        "source": "script_results", "title": "Pass rate trend", "mark": "line",
        "default_filters": {"success": [True, False]},
        "description": "Daily pass rate with run counts.",
        "dimensions": ["time"], "metrics": ["pass_rate", "run_count"], "time_grain": "day",
        "sort": [{"field": "time", "direction": "asc"}],
        "dashboard_ref": "script-results.json", "dashboard_panel": "Success Trend Over Time per Script",
    },
    "duration_trend": {
        "source": "script_results", "title": "Duration trend", "mark": "line",
        "default_filters": {"success": [True, False]},
        "description": "Daily average script duration with run counts.",
        "dimensions": ["time"], "metrics": ["avg_duration_ms", "run_count"], "time_grain": "day",
        "sort": [{"field": "time", "direction": "asc"}], "dashboard_ref": "script-results.json",
    },
    "script_summary": {
        "source": "script_results", "title": "Script results summary", "mark": "stat",
        "default_filters": {"success": [True, False]},
        "description": "Run, failure, pass-rate and duration totals.",
        "dimensions": [], "metrics": ["run_count", "failure_count", "pass_rate", "total_duration_min", "avg_duration_ms"],
        "dashboard_ref": "script-results.json", "dashboard_panel": "summary stats",
    },
    "campaign_pass_rate": {
        "source": "campaign_results", "title": "Campaign pass rate", "mark": "bar",
        "default_filters": {"success": [True, False]},
        "description": "Pass rate, duration and volume per campaign.",
        "dimensions": ["campaign_name"], "metrics": ["pass_rate", "avg_duration_ms", "run_count"],
        "sort": [{"field": "run_count", "direction": "desc"}],
        "dashboard_ref": "campaign-results.json", "dashboard_panel": "By Campaign",
    },
    "campaign_trend": {
        "source": "campaign_results", "title": "Campaign success trend", "mark": "line",
        "default_filters": {"success": [True, False]},
        "description": "Daily pass rate per campaign.",
        "dimensions": ["time", "campaign_name"], "metrics": ["pass_rate", "run_count"], "time_grain": "day",
        "sort": [{"field": "time", "direction": "asc"}],
        "dashboard_ref": "campaign-results.json", "dashboard_panel": "Success Trend Over Time per Campaign",
    },
    "deployment_outcomes": {
        "source": "deployment_results", "title": "Deployment outcomes", "mark": "stacked-bar",
        "description": "Execution status counts per deployment.",
        "dimensions": ["deployment_name", "status"], "metrics": ["run_count"], "time_range_days": 7,
        "sort": [{"field": "deployment_name", "direction": "asc"}], "dashboard_ref": "deployment-table.json",
    },
    "deployment_timeline": {
        "source": "deployment_results", "title": "Deployment timeline", "mark": "state-timeline",
        "description": "Hourly execution status per deployment.",
        "dimensions": ["time", "deployment_name", "status"], "metrics": ["run_count"], "time_grain": "hour",
        "time_range_days": 1, "sort": [{"field": "time", "direction": "asc"}],
        "dashboard_ref": "deployment-table.json", "dashboard_panel": "Script Execution Timeline by Device (24h)",
    },
    # --- alerts / fleet -------------------------------------------------------------
    "active_alerts_by_device": {
        "source": "alerts", "title": "Active alerts by device", "mark": "bar",
        "description": "Currently active incidents per device.",
        "dimensions": ["device_name"], "metrics": ["incident_count"], "default_filters": {"status": ["active"]},
        "time_range_days": 3650, "sort": [{"field": "incident_count", "direction": "desc"}],
        "dashboard_ref": "device-alerts-dashboard.json", "dashboard_panel": "Active Alerts by Device",
    },
    "alerts_by_type": {
        "source": "alerts", "title": "Incidents by type", "mark": "pie",
        "description": "Incident count per incident type.",
        "dimensions": ["incident_type"], "metrics": ["incident_count", "active_count"],
        "dashboard_ref": "device-alerts-dashboard.json",
    },
    "incidents_over_time": {
        "source": "alerts", "title": "Incidents over time", "mark": "line",
        "description": "Daily new incidents per incident type.",
        "dimensions": ["time", "incident_type"], "metrics": ["incident_count"], "time_grain": "day",
        "sort": [{"field": "time", "direction": "asc"}],
        "dashboard_ref": "device-alerts-dashboard.json", "dashboard_panel": "Incidents Overtime",
    },
    "degraded_hosts": {
        "source": "fleet_health_latest", "title": "Degraded fleet", "mark": "table",
        "description": "Devices whose newest live fleet check is DEGRADED or DOWN.",
        "dimensions": ["host_name", "device_name", "device_model", "verdict", "reason", "checked_at"],
        "metrics": [], "default_filters": {"verdict": ["DEGRADED", "DOWN"], "run_kind": ["live"]},
        "sort": [{"field": "host_name", "direction": "asc"}],
        "dashboard_ref": "vpt-fleet-health.json", "dashboard_panel": "Live — per device",
    },
    "fleet_verdicts": {
        "source": "fleet_health_latest", "title": "Fleet verdicts", "mark": "stat",
        "description": "Verdict counts of the newest live fleet check.",
        "dimensions": [], "metrics": ["ok_count", "degraded_count", "down_count", "unknown_count"],
        "default_filters": {"run_kind": ["live"]},
        "dashboard_ref": "vpt-fleet-health.json", "dashboard_panel": "OK / DEGRADED / DOWN / UNKNOWN",
    },
    "fleet_verdicts_over_time": {
        "source": "fleet_health", "title": "Fleet verdicts over time", "mark": "stacked-bar",
        "description": "Nightly verdict counts per day.",
        "dimensions": ["time", "verdict"], "metrics": ["device_count"], "time_grain": "day",
        "default_filters": {"run_kind": ["nightly"]}, "sort": [{"field": "time", "direction": "asc"}],
        "dashboard_ref": "vpt-fleet-health.json", "dashboard_panel": "Fleet verdicts over time",
    },
    # --- occupancy / device info ----------------------------------------------------
    "occupancy_by_device": {
        "source": "device_occupancy", "title": "Occupancy by device", "mark": "bar",
        "description": "Share of the range each device was locked.",
        "dimensions": ["device"], "metrics": ["occupancy_percent", "session_count"],
        "sort": [{"field": "occupancy_percent", "direction": "desc"}], "time_range_days": 7,
        "dashboard_ref": "device-occupancy.json", "dashboard_panel": "Occupancy % by device",
    },
    "occupancy_by_owner": {
        "source": "device_occupancy", "title": "Occupied time by owner type", "mark": "pie",
        "description": "Locked seconds per owner type.",
        "dimensions": ["owner_type"], "metrics": ["occupied_seconds"], "time_range_days": 7,
        "dashboard_ref": "device-occupancy.json", "dashboard_panel": "Occupied time by owner type",
    },
    "device_info_latest": {
        "source": "device_information", "title": "Latest device information", "mark": "table",
        "description": "Newest device information per device with corrected model/software.",
        "dimensions": ["host_name", "device_name", "userinterface_name", "model", "software_version", "corrected"],
        "metrics": ["last_scanned_at"], "time_range_days": 3650,
        "sort": [{"field": "device_name", "direction": "asc"}],
        "dashboard_ref": "device-information-get-info.json", "dashboard_panel": "Latest Device Info",
    },
    # --- gateway / network ----------------------------------------------------------
    "ookla_speed_trend": {
        "source": "ookla_speedtest", "title": "Ookla download over time", "mark": "line",
        "description": "Daily average download speed per host.",
        "dimensions": ["time", "host_name"], "metrics": ["avg_download_mbps", "avg_upload_mbps", "test_count"],
        "time_grain": "day", "sort": [{"field": "time", "direction": "asc"}],
        "dashboard_ref": "ookla-speedtest.json", "dashboard_panel": "Ookla Download Speedtest over Time",
    },
    "ookla_by_gateway": {
        "source": "ookla_speedtest", "title": "Speed by gateway technology", "mark": "bar",
        "description": "Average download/upload/latency per gateway technology.",
        "dimensions": ["gateway_technology"],
        "metrics": ["avg_download_mbps", "avg_upload_mbps", "avg_latency_ms", "test_count"],
        "dashboard_ref": "ookla-speedtest.json",
    },
    "dns_success_trend": {
        "source": "dns_lookup", "title": "DNS success rate", "mark": "line",
        "description": "Hourly DNS lookup success rate.",
        "dimensions": ["time"], "metrics": ["success_rate", "test_count"], "time_grain": "hour",
        "time_range_days": 2, "sort": [{"field": "time", "direction": "asc"}],
        "dashboard_ref": "dns-lookup.json", "dashboard_panel": "DNS Success Rate Over Time (Hourly %)",
    },
    "dns_by_domain": {
        "source": "dns_lookup", "title": "DNS performance by domain", "mark": "table",
        "description": "Lookup time and success per domain.",
        "dimensions": ["domain"], "metrics": ["avg_lookup_ms", "min_lookup_ms", "max_lookup_ms", "success_rate", "test_count"],
        "sort": [{"field": "avg_lookup_ms", "direction": "desc"}],
        "dashboard_ref": "dns-lookup.json", "dashboard_panel": "Domain Performance Comparison",
    },
    "superping_rtt_trend": {
        "source": "superping", "title": "Superping round trip", "mark": "line",
        "description": "Daily average round-trip time per target.",
        "dimensions": ["time", "target"], "metrics": ["avg_rtt_ms", "test_count"], "time_grain": "day",
        "sort": [{"field": "time", "direction": "asc"}],
        "dashboard_ref": "superping.json", "dashboard_panel": "Superping Round Trip Delay over Time",
    },
    "superping_by_target": {
        "source": "superping", "title": "Superping by target", "mark": "table",
        "description": "Score, RTT, loss and reachability per target.",
        "dimensions": ["target"],
        "metrics": ["avg_score", "avg_rtt_ms", "avg_packet_loss_percent", "reachable_rate", "test_count"],
        "sort": [{"field": "avg_rtt_ms", "direction": "desc"}],
        "dashboard_ref": "superping.json", "dashboard_panel": "Target Performance Comparison",
    },
    # --- historical system / service ------------------------------------------------
    "host_cpu_trend": {
        "source": "device_system_metrics", "title": "Host CPU usage", "mark": "line",
        "description": "Hourly average CPU per host.",
        "dimensions": ["time", "host_name"], "metrics": ["avg_cpu_percent"], "time_grain": "hour",
        "time_range_days": 1, "sort": [{"field": "time", "direction": "asc"}],
        "dashboard_ref": "system-host-monitoring.json", "dashboard_panel": "CPU Usage",
    },
    "host_resources": {
        "source": "device_system_metrics", "title": "Host resources", "mark": "table",
        "description": "Average CPU, memory, disk and temperature per host.",
        "dimensions": ["host_name"],
        "metrics": ["avg_cpu_percent", "avg_memory_percent", "avg_disk_percent", "avg_temperature_c"],
        "time_range_days": 1, "sort": [{"field": "avg_cpu_percent", "direction": "desc"}],
        "dashboard_ref": "system-host-monitoring.json", "dashboard_panel": "Host Metrics",
    },
    "server_resources_trend": {
        "source": "historical_system_metrics", "title": "Server resources over time", "mark": "line",
        "description": "Hourly CPU per server host.",
        "dimensions": ["time", "host_name"], "metrics": ["avg_cpu_percent", "avg_memory_percent"], "time_grain": "hour",
        "time_range_days": 1, "sort": [{"field": "time", "direction": "asc"}],
        "dashboard_ref": "system-server-monitoring.json",
    },
    "service_status_current": {
        "source": "service_status", "title": "Platform components", "mark": "table",
        "description": "Current state of every monitored platform component (admin).",
        "dimensions": ["server_name", "vm", "component", "state", "detail", "since", "checked_at"], "metrics": [],
        "sort": [{"field": "state", "direction": "desc"}],
        "dashboard_ref": "system-service-status.json", "dashboard_panel": "Components — current status",
    },
    "service_availability": {
        "source": "service_availability", "title": "Service availability", "mark": "table",
        "description": "Availability %, minutes and times not OK per component (admin).",
        "dimensions": ["vm", "component"], "metrics": ["availability_percent", "minutes_not_ok", "times_not_ok"],
        "time_range_days": 7, "sort": [{"field": "availability_percent", "direction": "asc"}],
        "dashboard_ref": "system-service-status.json", "dashboard_panel": "Availability over the selected range",
    },
}
