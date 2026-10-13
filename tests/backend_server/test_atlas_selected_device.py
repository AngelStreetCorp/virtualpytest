"""BUG-0405: "my/selected/this device(s)" deterministically means the chat's Target device."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from backend_server.src.lib.analytics.named_devices import refers_to_selected_device, selected_device_state
from backend_server.src.mcp.tools import analytics_tools
from tests.backend_server.test_atlas_analytics import REQ, _named_tools

SELECTED = {"host_name": "host-clone-1", "device_id": "host", "device_name": "host"}
CTX = {"_context_team_id": "t", "_context_refers_to_selected_device": True, "_context_selected_device": SELECTED,
       "_context_host_name": "host-clone-1", "_context_device_id": "host"}
NOTE = "Limited to your selected device host (host-clone-1)"

@pytest.mark.parametrize("text", [
    "Build a canvas for my selected devices: pass rate by device", "pass rate on my device",
    "failures on this device", "what about the current device", "for the target", "Selected Device only",
    "my devices last week", "the selected device"])
def test_phrases_that_refer_to_the_target(text):
    assert refers_to_selected_device(text)

@pytest.mark.parametrize("text", [
    "pass rate by device", "devices list", "show all devices", "pass rate per device and host", "",
    "my deviceless setup", "targets met this week"])
def test_generic_device_words_do_not_trigger(text):
    assert not refers_to_selected_device(text)

def test_state_requires_a_target_on_the_selected_server():
    ctx = {"host_name": "host-clone-1", "device_id": "host", "selected_server_hosts": ["host-clone-1", "x"],
           "available_devices": [{"host_name": "host-clone-1", "device_id": "host", "device_name": "host"}]}
    on = selected_device_state("my selected devices", ctx)
    assert on["refers_to_selected_device"] and on["selected_device"]["device_name"] == "host"
    foreign = selected_device_state("my selected devices", {**ctx, "selected_server_hosts": ["labox-tv"]})
    assert not foreign["refers_to_selected_device"] and foreign["selected_device_foreign"]
    assert not selected_device_state("my selected devices", {**ctx, "device_id": ""})["refers_to_selected_device"]
    assert selected_device_state("pass rate by device", ctx) == {
        "refers_to_selected_device": False, "selected_device": None, "selected_device_foreign": False}

def test_single_request_gets_current_device_scope_for_query_render_export():
    captured = []
    tools = _named_tools([{"device_name": "host", "run_count": 1}], captured)
    for call in (tools.query_analytics_data, tools.render_analytics_artifact, tools.export_analytics_data):
        reply = call({**REQ, **CTX})
        assert captured[-1]["scope"] == "current_device", call
        assert NOTE in reply["content"][0]["text"]

def test_explicit_visible_scope_is_overridden_but_a_device_filter_is_kept():
    captured = []
    tools = _named_tools([{"device_name": "host", "run_count": 1}], captured)
    tools.query_analytics_data({**REQ, "scope": "visible", **CTX})
    assert captured[-1]["scope"] == "current_device"
    tools.query_analytics_data({**REQ, "filters": {"device_name": ["stb3"]}, **CTX})
    assert captured[-1].get("scope") is None and captured[-1]["filters"] == {"device_name": ["stb3"]}

def test_canvas_gets_scope_at_top_level_and_every_unfiltered_panel():
    request, note = analytics_tools.enforce_selected_device(
        {"panels": [REQ, {**REQ, "scope": "visible"}, {**REQ, "filters": {"host_name": "h"}}]}, CTX, [])
    assert request["scope"] == "current_device"
    assert [p["scope"] for p in request["panels"]] == ["current_device", "current_device", "visible"]
    assert note == NOTE

def test_canvas_render_runs_every_panel_on_the_target():
    captured = []
    tools = _named_tools([{"device_name": "host", "run_count": 1}], captured)
    reply = tools.render_analytics_artifact({"panels": [REQ, REQ], **CTX})
    assert [c["scope"] for c in captured] == ["current_device", "current_device"]
    assert NOTE in reply["content"][0]["text"]

def test_grafana_draft_carries_the_scope():
    seen = {}

    class Drafts:
        def create(self, request, context):
            seen["request"], seen["context"] = request, context
            return {"status": "reused", "maintained": {"dashboard_title": "d", "panel_title": "p"}}

    tools = analytics_tools.AnalyticsTools()
    tools.drafts = Drafts()
    tools.service.resolve_draft_request = lambda request, context: (request, context)
    reply = tools.create_grafana_draft({"panels": [REQ, REQ], **CTX})
    assert seen["request"]["scope"] == "current_device"
    assert all(p["scope"] == "current_device" for p in seen["request"]["panels"])
    assert seen["context"].device_name == "host"
    assert reply["isError"] is False

def test_named_devices_win_over_the_selected_device():
    captured = []
    tools = _named_tools([{"device_name": "S21x", "run_count": 1}], captured)
    tools.query_analytics_data({**REQ, **CTX, "_context_named_devices": [{"name": "S21x", "on_server": True}]})
    assert captured[-1]["filters"] == {"device_name": ["S21x"]} and "scope" not in captured[-1]

def test_foreign_target_keeps_the_visible_scope_and_says_so():
    captured = []
    tools = _named_tools([{"device_name": "host", "run_count": 1}], captured)
    reply = tools.query_analytics_data({**REQ, "_context_team_id": "t", "_context_selected_device_foreign": True})
    assert "scope" not in captured[-1]
    assert "selected device is not on this server" in reply["content"][0]["text"]

def test_no_reference_means_no_change():
    captured = []
    tools = _named_tools([], captured)
    reply = tools.query_analytics_data({**REQ, "_context_team_id": "t", "_context_selected_device": SELECTED})
    assert "scope" not in captured[-1] and "Limited to" not in reply["content"][0]["text"]
