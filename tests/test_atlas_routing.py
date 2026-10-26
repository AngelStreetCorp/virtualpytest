from types import SimpleNamespace

from backend_server.src.agent.atlas_routing import build_catalog, routing_mode, validate_selection, resolve_tool, shadow_route, should_escalate_to_jev


def skill(name="device-control", tools=("press",), platform=None, context=()):
    return SimpleNamespace(name=name, tools=list(tools), platform=platform,
                           required_context=list(context), requires_device=True,
                           description="A valid skill description")


def test_catalog_is_deterministic_and_fails_closed_for_unknown_tools():
    catalog = build_catalog([skill("z", ("known",)), skill("a", ("missing",))], {"known"})
    assert [r.skill_id for r in catalog.routes] == ["z"]
    assert catalog.errors == ("a: unknown MCP tools: missing",)


def test_catalog_filters_platform_and_authorized_tools():
    catalog = build_catalog([skill("mobile", ("known",), "mobile"), skill("web", ("known",), "web")], {"known"})
    assert [r.skill_id for r in catalog.for_context(platform="mobile", allowed_tools={"known"})] == ["mobile"]
    assert catalog.for_context(platform="mobile", allowed_tools=set()) == ()


def test_routing_mode_defaults_off_and_rejects_invalid_values(monkeypatch):
    monkeypatch.delenv("ATLAS_JEV_ROUTING_MODE", raising=False)
    assert routing_mode() == "off"
    monkeypatch.setenv("ATLAS_JEV_ROUTING_MODE", "unexpected")
    assert routing_mode() == "off"
    monkeypatch.setenv("ATLAS_JEV_ROUTING_MODE", "shadow")
    assert routing_mode() == "shadow"


def test_selection_rejects_unknown_and_unauthorized_routes():
    catalog = build_catalog([skill("safe", ("known",))], {"known"})
    assert validate_selection("skill:missing", 0.99, {"skill:missing": 1}, catalog=catalog).action == "plan"
    route = catalog.routes[0]
    assert validate_selection(route.route_id, 0.99, {route.route_id: 1}, catalog=catalog,
                              allowed_tools=set()).reason == "unauthorized_tools"


def test_selection_clarifies_ambiguous_or_low_confidence_choices():
    catalog = build_catalog([skill("safe", ("known",))], {"known"})
    route = catalog.routes[0]
    assert validate_selection(route.route_id, 0.99, {route.route_id: 1}, catalog=catalog,
                              facts={"target_ambiguous": True}).action == "clarify"
    assert validate_selection(route.route_id, 0.60, {route.route_id: .6, "other": .4}, catalog=catalog).reason == "planner_only"


def test_tool_resolution_uses_real_tool_ids_and_never_invents_defaults():
    read_only = SimpleNamespace(name="health", tools=["get_device_info"], platform=None,
                                required_context=[], requires_device=True,
                                description="Read device health")
    catalog = build_catalog([read_only], {"get_device_info"})
    route = catalog.routes[0]
    schemas = {"get_device_info": {"input_schema": {"properties": {"device_id": {}}, "required": []}}}
    proposal = resolve_tool(route, "check whether device TV-1 is online", tool_schemas=schemas)
    assert proposal.tool_id == "get_device_info"
    assert proposal.action == "route"
    assert proposal.parameters["device_id"] == "TV-1"
    assert resolve_tool(route, "do something with the device", tool_schemas=schemas).action == "plan"
    assert resolve_tool(route, "check if device Samsung is online", tool_schemas=schemas).action == "clarify"
    assert resolve_tool(route, "check whether the Samsung TV is online", tool_schemas=schemas).action == "clarify"
    assert resolve_tool(route, "check whether device TV-1 is online", tool_schemas={}).reason == "schema_unavailable"


def test_gated_shadow_route_reaches_jev_and_validates_proposal(monkeypatch):
    from backend_server.src.agent import atlas_routing
    catalog = build_catalog([SimpleNamespace(name="health", tools=["get_device_info"], platform=None,
                     required_context=[], requires_device=True, description="Read device health")], {"get_device_info"})
    monkeypatch.setenv("ATLAS_JEV_ROUTING_MODE", "gated")
    monkeypatch.setattr(atlas_routing.decisions, "enabled", lambda usage: True)
    monkeypatch.setattr(atlas_routing.router, "resolve", lambda *args, **kwargs: object())
    monkeypatch.setattr(atlas_routing.decisions, "choose", lambda *args, **kwargs: {
        "choice": "skill:health", "confidence": .99, "probabilities": {"skill:health": .99, "clarify": .01},
        "decision_id": "dry-test", "success": True})
    result = shadow_route("check whether device TV-1 is online", catalog=catalog, team_id="test",
                          allowed_tools={"get_device_info"}, tool_schemas={"get_device_info": {
                              "input_schema": {"properties": {"device_id": {}}, "required": []}}})
    assert result["validated_action"] == "route"
    assert result["tool_proposal"]["tool_id"] == "get_device_info"
    assert result["tool_proposal"]["parameters"] == {"device_id": "TV-1"}


def test_selective_escalation_requires_two_unambiguous_triggers():
    item = SimpleNamespace(name="health")
    assert should_escalate_to_jev([])
    assert should_escalate_to_jev([(item, 10, 1)])
    assert should_escalate_to_jev([(item, 10, 2), (item, 9, 2)])
    assert not should_escalate_to_jev([(item, 10, 2), (item, 6, 2)])


def test_extracted_node_key_matches_the_tool_schema():
    from backend_server.src.agent.atlas_routing import _extract_parameters
    assert set(_extract_parameters("navigate to the Settings node", "navigate_to_node")) == {"target_node_label"}
    assert set(_extract_parameters("go to Home", "verify_node")) == {"node_label"}
    # a device tool must not gain a node key
    assert "node_label" not in _extract_parameters("check whether device TV-1 is online", "get_device_info")


def test_gated_route_abstains_on_provider_error(monkeypatch):
    from backend_server.src.agent import atlas_routing
    catalog = build_catalog([SimpleNamespace(name="health", tools=["get_device_info"], platform=None,
                     required_context=[], requires_device=True, description="Read device health")], {"get_device_info"})
    monkeypatch.setenv("ATLAS_JEV_ROUTING_MODE", "gated")
    monkeypatch.setattr(atlas_routing.decisions, "enabled", lambda usage: True)
    monkeypatch.setattr(atlas_routing.router, "resolve", lambda *args, **kwargs: (_ for _ in ()).throw(
        TimeoutError("provider timeout")))
    result = shadow_route("is device TV-1 online", catalog=catalog, team_id="test",
                          allowed_tools={"get_device_info"})
    assert result["abstained"] is True
    assert result["reason"] == "provider_error"
    assert "tool_proposal" not in result
