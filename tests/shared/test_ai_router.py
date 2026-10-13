"""AI usage resolver (TASK-30 §3.4): key walk, layers, scope, split, fallback chain.

Pure in-memory: the routing snapshot is installed directly, no DB.

Run: pytest tests/shared/test_ai_router.py -v
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, endpoint, install_routing, profile, route  # noqa: E402
from shared.src.lib.ai import router, usages  # noqa: E402

TEAM = "team-qa-fr"
OTHER_TEAM = "team-other"


def snapshot(routes, profiles=None, endpoints=None):
    profiles = profiles or [
        profile("p-gpu", "local-gpu"),
        profile("p-qwen", "qwen-openrouter", endpoint_id="e-cloud"),
        profile("p-claude", "claude", endpoint_id="e-cloud"),
    ]
    endpoints = endpoints or [endpoint(), endpoint("e-cloud", "cloud", preset="openrouter")]
    return {"endpoints": {e["id"]: e for e in endpoints},
            "profiles": {p["id"]: p for p in profiles},
            "routes": routes}


@pytest.fixture
def install(monkeypatch):
    def _install(routes, **kw):
        install_routing(monkeypatch, snapshot=snapshot(routes, **kw))
    yield _install
    clear_routing()


ROOTS = [route("r-agent", "agent", "p-claude"), route("r-vision", "vision", "p-qwen"),
         route("r-text", "text", "p-qwen")]


def test_child_usage_inherits_root(install):
    install(ROOTS)
    res = router.resolve("vision.banner")
    assert res.via_key == "vision" and res.layer == "default"
    assert res.primary.profile_name == "qwen-openrouter"


def test_specific_key_beats_team_root(install):
    # The worked example from TASK-30 §3.4.
    install(ROOTS + [route("r-banner", "vision.banner", "p-gpu"),
                     route("r-team-vision", "vision", "p-claude", team_id=TEAM)])
    banner = router.resolve("vision.banner", TEAM)
    assert (banner.primary.profile_name, banner.layer, banner.via_key) == ("local-gpu", "default", "vision.banner")
    ask = router.resolve("vision.ask", TEAM)
    assert (ask.primary.profile_name, ask.layer, ask.via_key) == ("claude", "team", "vision")
    # Monitoring call (no team) never sees the team override.
    assert router.resolve("vision.ask").primary.profile_name == "qwen-openrouter"


def test_team_beats_default_at_same_key(install):
    install(ROOTS + [route("r-team-text", "text", "p-gpu", team_id=TEAM)])
    assert router.resolve("text.translation", TEAM).primary.profile_name == "local-gpu"
    assert router.resolve("text.translation", OTHER_TEAM).primary.profile_name == "qwen-openrouter"


def test_scope_specificity_then_priority(install):
    install(ROOTS + [
        route("r-host", "vision.banner", "p-gpu", host_name="pi1"),
        route("r-host-model", "vision.banner", "p-claude", host_name="pi1", device_model="stb-x"),
        route("r-model", "vision.banner", "p-qwen", device_model="stb-y", priority=5),
    ])
    assert router.resolve("vision.banner", context={"host_name": "pi1", "device_model": "stb-x"}) \
        .primary.profile_name == "claude"
    assert router.resolve("vision.banner", context={"host_name": "pi1"}).primary.profile_name == "local-gpu"
    # A scoped route never matches a call without that context: falls to the root.
    assert router.resolve("vision.banner").via_key == "vision"


def test_priority_breaks_ties(install):
    install(ROOTS + [route("r-a", "text.plan", "p-gpu", host_name="h", priority=50),
                     route("r-b", "text.plan", "p-claude", device_model="m", priority=10)])
    res = router.resolve("text.plan", context={"host_name": "h", "device_model": "m"})
    assert res.primary.profile_name == "claude"


def test_split_is_deterministic_per_request(install):
    install(ROOTS + [route("r-split", "vision.menu", "p-qwen", split_profile_id="p-gpu", split_percent=50)])
    arms = {rid: router.resolve("vision.menu", request_id=rid) for rid in (f"req-{i}" for i in range(200))}
    b_share = sum(1 for r in arms.values() if r.split_arm == "b") / len(arms)
    assert 0.3 < b_share < 0.7
    for rid, res in arms.items():
        again = router.resolve("vision.menu", request_id=rid)
        assert again.split_arm == res.split_arm
        expected = "local-gpu" if res.split_arm == "b" else "qwen-openrouter"
        assert res.primary.profile_name == expected


def test_fallback_chain_depth_and_cycles(install):
    profiles = [
        profile("p1", "one", fallback_profile_id="p2"),
        profile("p2", "two", fallback_profile_id="p3"),
        profile("p3", "three", fallback_profile_id="p4"),
        profile("p4", "four", fallback_profile_id="p1"),
    ]
    install([route("r-agent", "agent", "p1"), route("r-vision", "vision", "p3"), route("r-text", "text", "p1")],
            profiles=profiles)
    assert [h.profile_name for h in router.resolve("text").hops] == ["one", "two", "three"]
    # p3 -> p4 -> p1 -> p2: capped at MAX_CHAIN, and a cycle back to p3 is cut.
    assert [h.profile_name for h in router.resolve("vision").hops] == ["three", "four", "one"]


def test_disabled_profile_or_endpoint_is_skipped(install):
    profiles = [profile("p-gpu", "local-gpu", enabled=False), profile("p-qwen", "qwen", endpoint_id="e-cloud")]
    install([route("r-vision", "vision", "p-qwen"), route("r-banner", "vision.banner", "p-gpu"),
             route("r-agent", "agent", "p-qwen"), route("r-text", "text", "p-qwen")], profiles=profiles)
    assert router.resolve("vision.banner").primary.profile_name == "qwen"


def test_endpoint_restricted_to_teams(install):
    endpoints = [endpoint(allowed_team_ids=[TEAM]), endpoint("e-cloud", "cloud", preset="openrouter")]
    install(ROOTS + [route("r-team", "vision", "p-gpu", team_id=OTHER_TEAM)], endpoints=endpoints)
    assert router.resolve("vision.ask", OTHER_TEAM).primary.profile_name == "qwen-openrouter"


def test_agent_and_skill_usages(install):
    install(ROOTS + [route("r-atlas", "agent.atlas", "p-qwen"),
                     route("r-skill", "agent.atlas.skill.build-tree-stb", "p-gpu")])
    assert usages.agent_usage("assistant") == "agent.atlas"
    assert usages.agent_usage("monitor", "check-system-health") == "agent.nightwatch.skill.check-system-health"
    assert router.resolve("agent.atlas.skill.build-tree-stb").primary.profile_name == "local-gpu"
    assert router.resolve("agent.atlas.skill.device-control").primary.profile_name == "qwen-openrouter"
    assert router.resolve("agent.nightwatch").primary.profile_name == "claude"
    assert router.resolve("agent.custom-bot").via_key == "agent"


def test_unknown_usage_rejected(install):
    install(ROOTS)
    with pytest.raises(usages.UnknownUsageError):
        router.resolve("vision.nope")
    with pytest.raises(usages.UnknownUsageError):
        router.resolve("banner")


def test_no_route_raises(install):
    install([route("r-agent", "agent", "p-claude")])
    with pytest.raises(router.AIRoutingError):
        router.resolve("vision.banner")
    assert router.is_available("vision.banner") is False


def test_usage_needs_and_json_output_default_thinking_off():
    assert usages.needs("agent.atlas.skill.x") == frozenset({"tools"})
    assert usages.needs("vision.banner") == frozenset({"vision"})
    assert usages.effective("vision.banner", "thinking") == "off"
    assert usages.effective("vision.ask", "thinking") == "auto"
    assert usages.lineage("vision.banner") == ["vision.banner", "vision"]


def test_thinking_off_sends_chat_template_flag_for_local_only(install):
    install(ROOTS)
    local = router.Hop(profile=profile(), endpoint=endpoint())
    assert local.extra_body("vision.banner") == {"chat_template_kwargs": {"enable_thinking": False}}
    assert local.extra_body("vision.ask") == {}
    cloud = router.Hop(profile=profile(), endpoint=endpoint("e", "cloud", preset="openrouter"))
    assert cloud.extra_body("vision.banner") == {}


def test_profile_caps_and_overrides():
    hop = router.Hop(profile=profile(max_tokens_cap=100, temperature=0.4, thinking="on"), endpoint=endpoint())
    assert hop.max_tokens(600) == 100 and hop.max_tokens(50) == 50
    assert hop.temperature(0.0) == 0.4
    assert hop.extra_body("vision.banner") == {}  # profile says thinking on


# ---- resolve_profile: one pinned profile, no fallback (TASK-27 step 5 scoring) ----------

def _pinned_setup(install, **kw):
    profiles = [profile("p-gpu", "local-gpu", fallback_profile_id="p-qwen"),
                profile("p-qwen", "qwen-openrouter", endpoint_id="e-cloud"),
                profile("p-off", "off", enabled=False)]
    install(ROOTS, profiles=profiles, **kw)


def test_resolve_profile_by_name_or_id_has_one_hop_and_no_fallback(install):
    _pinned_setup(install)
    for ref in ("local-gpu", "p-gpu"):
        res = router.resolve_profile(ref, "vision.banner")
        assert [h.profile_name for h in res.hops] == ["local-gpu"]  # fallback chain dropped
        assert (res.layer, res.via_key, res.split_arm) == ("pinned", "profile:local-gpu", "")
        assert res.is_fallback(res.primary) is False
    # resolve() for the same profile would still carry the fallback: default unchanged.
    install(ROOTS + [route("r-banner", "vision.banner", "p-gpu")],
            profiles=[profile("p-gpu", "local-gpu", fallback_profile_id="p-qwen"),
                      profile("p-qwen", "qwen-openrouter", endpoint_id="e-cloud")])
    assert [h.profile_name for h in router.resolve("vision.banner").hops] == ["local-gpu", "qwen-openrouter"]


def test_resolve_profile_refuses_unknown_disabled_or_foreign(install):
    _pinned_setup(install, endpoints=[endpoint(allowed_team_ids=[TEAM]),
                                      endpoint("e-cloud", "cloud", preset="openrouter")])
    with pytest.raises(router.AIRoutingError):
        router.resolve_profile("nope", "vision")
    with pytest.raises(router.AIRoutingError):
        router.resolve_profile("off", "vision")
    with pytest.raises(router.AIRoutingError):
        router.resolve_profile("local-gpu", "vision", OTHER_TEAM)  # endpoint restricted to TEAM
    assert router.resolve_profile("local-gpu", "vision", TEAM).primary.profile_name == "local-gpu"
    with pytest.raises(usages.UnknownUsageError):
        router.resolve_profile("local-gpu", "vision.nope")


def test_pinned_profile_failure_never_reaches_the_fallback(install, monkeypatch):
    from shared.src.lib.ai import gateway
    _pinned_setup(install)
    monkeypatch.setattr(gateway.tracing, "trace_call", lambda **k: None)
    calls = []

    class _Boom:
        class messages:
            @staticmethod
            def create(**kw):
                calls.append(kw)
                raise RuntimeError("endpoint offline")

    monkeypatch.setattr(router.Hop, "client", lambda self: _Boom)
    result = gateway.execute(router.resolve_profile("local-gpu", "vision"), "hi")
    assert result["success"] is False and result["fallback_used"] is False
    assert result["profile"] == "local-gpu" and len(calls) == 1
