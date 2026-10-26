"""Claude on the owner's Anthropic keys only (owner rule 2026-10-20, BUG-0721).

- the chain steps over a disabled hop instead of stopping there (AngelStreet key -> Individual key (off) -> MiniMax);
- a Claude model on OpenRouter is never a usable hop;
- an Anthropic user key (sk-ant-usr) works as is when workspace-scoped, and sends anthropic-workspace-id when that secret exists;
- each ai_calls row says which hop served it (hop_index);
- Responses-API usage (input_tokens / output_tokens) is read, not counted as 0.

Run: pytest tests/shared/test_ai_claude_chain.py -q
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, endpoint, install_routing, profile, route  # noqa: E402
from shared.src.lib.ai import call_log, provider_client, router  # noqa: E402


def _snapshot(individual_enabled=False):
    endpoints = [
        endpoint("e-as", "anthropic", preset="anthropic", base_url=None, secret_name="anthropic"),
        endpoint("e-ind", "anthropic-individual", preset="anthropic", base_url=None,
                 secret_name="anthropic-individual", enabled=individual_enabled),
        endpoint("e-mm", "minimax", preset="minimax", base_url=None, secret_name="minimax"),
        endpoint("e-or", "openrouter", preset="openrouter", base_url=None, secret_name="openrouter"),
    ]
    profiles = [
        profile("p-sonnet", "claude-sonnet-5-5", model="claude-sonnet-5-5", endpoint_id="e-as",
                fallback_profile_id="p-sonnet-ind"),
        profile("p-sonnet-ind", "claude-sonnet-5-5-individual", model="claude-sonnet-5-5", endpoint_id="e-ind",
                fallback_profile_id="p-m3"),
        profile("p-m3", "minimax-m3", model="minimax-m3", endpoint_id="e-mm", fallback_profile_id="p-or-m3"),
        profile("p-or-m3", "openrouter-minimax-m3", model="minimax/minimax-m3", endpoint_id="e-or"),
        profile("p-or-claude", "openrouter-claude-sonnet-5-5", model="anthropic/claude-sonnet-5.5",
                endpoint_id="e-or", fallback_profile_id="p-m3"),
    ]
    routes = [route("r-agent", "agent", "p-sonnet"), route("r-vision", "vision", "p-or-m3"),
              route("r-text", "text", "p-or-m3"), route("r-or", "text.plan", "p-or-claude")]
    return {"endpoints": {e["id"]: e for e in endpoints}, "profiles": {p["id"]: p for p in profiles},
            "routes": routes}


@pytest.fixture
def install(monkeypatch):
    def _install(**kw):
        install_routing(monkeypatch, snapshot=_snapshot(**kw))
    yield _install
    clear_routing()


def test_disabled_individual_hop_is_stepped_over_not_the_end(install):
    install(individual_enabled=False)
    hops = [h.profile_name for h in router.resolve("agent").hops]
    assert hops == ["claude-sonnet-5-5", "minimax-m3", "openrouter-minimax-m3"]


def test_enabled_individual_hop_is_the_second_hop_and_minimax_the_third(install):
    install(individual_enabled=True)
    resolution = router.resolve("agent")
    assert [h.endpoint_name for h in resolution.hops] == ["anthropic", "anthropic-individual", "minimax"]
    assert [resolution.hop_index(h) for h in resolution.hops] == [0, 1, 2]


def test_claude_on_openrouter_is_never_usable(install):
    install()
    # The route points at a Claude-on-OpenRouter profile: it is skipped like a disabled one, the route
    # falls through to the parent key (text -> openrouter-minimax-m3), never to OpenRouter's Claude.
    assert all(not router.is_claude_model(h.model) or h.preset == "anthropic"
               for h in router.resolve("text.plan").hops)
    assert router.claude_off_anthropic({"model": "anthropic/claude-haiku-5.5"}, {"preset": "openrouter"})
    assert router.claude_off_anthropic({"model": "claude-haiku-5-5"}, {"preset": "openrouter"})
    assert not router.claude_off_anthropic({"model": "claude-haiku-5-5"}, {"preset": "anthropic"})
    assert not router.claude_off_anthropic({"model": "minimax/minimax-m3"}, {"preset": "openrouter"})


def test_user_key_works_without_workspace_and_sends_it_when_stored(monkeypatch):
    # A workspace-scoped user key needs no id (2026-10-20: two such keys answered without the header).
    secrets = {"anthropic-individual": "sk-ant-usr-xyz"}
    monkeypatch.setattr(router, "get_secret", lambda name: secrets.get(name))
    hop = router.Hop(profile={"id": "p", "name": "p", "model": "claude-sonnet-5-5"},
                     endpoint={"id": "e", "name": "anthropic-individual", "preset": "anthropic",
                               "secret_name": "anthropic-individual"})
    assert hop.has_credentials()
    assert "anthropic-workspace-id" not in hop.client()._client._custom_headers
    secrets["anthropic-individual-workspace"] = "wrkspc_test"
    assert hop.has_credentials()
    client = hop.client()
    assert client._client._custom_headers.get("anthropic-workspace-id") == "wrkspc_test"


def test_org_key_sends_no_workspace_header(monkeypatch):
    monkeypatch.setattr(router, "get_secret", lambda name: {"anthropic": "sk-ant-api-xyz"}.get(name))
    hop = router.Hop(profile={"id": "p", "name": "p", "model": "claude-haiku-5-5"},
                     endpoint={"id": "e", "name": "anthropic", "preset": "anthropic", "secret_name": "anthropic"})
    assert hop.has_credentials()
    assert "anthropic-workspace-id" not in hop.client()._client._custom_headers


def test_row_records_the_hop_that_served(install):
    install(individual_enabled=True)
    resolution = router.resolve("agent")
    row = call_log.build_row(resolution, resolution.hops[2], ok=True, ms=5, tokens_in=10, tokens_out=2,
                             fallback=resolution.is_fallback(resolution.hops[2]))
    assert row["hop_index"] == 2 and row["fallback_used"] is True and row["endpoint"] == "minimax"


def test_responses_api_usage_shape_is_counted():
    used = provider_client.openai_call_usage({
        "input_tokens": 1200, "output_tokens": 300,
        "input_tokens_details": {"cached_tokens": 200}, "output_tokens_details": {"reasoning_tokens": 256},
    })
    assert (used.tokens_in, used.tokens_out, used.cache_read, used.reasoning) == (1200, 300, 200, 256)
    chat = provider_client.openai_call_usage({"prompt_tokens": 50, "completion_tokens": 7, "cost": 0.001})
    assert (chat.tokens_in, chat.tokens_out, chat.cost) == (50, 7, 0.001)


def test_zero_token_audit_flags_only_billed_endpoints():
    from shared.src.lib.ai import call_audit
    endpoints = [{"name": "openrouter", "preset": "openrouter"}, {"name": "minimax-vlm", "preset": "minimax_vlm"},
                 {"name": "lmstudio-pc", "preset": "openai_compatible"}, {"name": "anthropic", "preset": "anthropic"}]
    rows = [
        {"endpoint": "openrouter", "ok": True, "outcome": "served", "tokens_in": 0, "tokens_out": 0},   # flagged
        {"endpoint": "openrouter", "ok": False, "outcome": "served", "tokens_in": 0, "tokens_out": 0},  # refused: free
        {"endpoint": "anthropic", "ok": True, "outcome": "avoided", "tokens_in": 0, "tokens_out": 0},   # cache hit
        {"endpoint": "minimax-vlm", "ok": True, "outcome": "served", "tokens_in": 0, "tokens_out": 0},  # flat plan
        {"endpoint": "lmstudio-pc", "ok": True, "outcome": "served", "tokens_in": 0, "tokens_out": 0},  # local
        {"endpoint": "anthropic", "ok": True, "outcome": "served", "tokens_in": 9, "tokens_out": 1},
    ]
    assert call_audit.zero_token_suspects(rows, endpoints) == [rows[0]]
