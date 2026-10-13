"""AI gateway + provider presets (TASK-30): fallback, empty retries, params, hygiene.

Fake provider clients only — no network, no keys, no DB.

Run: pytest tests/shared/test_ai_gateway.py -v
"""
import os
import sys
from types import SimpleNamespace

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, endpoint, install_routing, profile, route  # noqa: E402
from shared.src.lib.ai import gateway, router  # noqa: E402
from shared.src.lib.ai.provider_client import (  # noqa: E402
    AnthropicProviderClient,
    GoogleProviderClient,
    OpenAICompatibleProviderClient,
    create_client,
    strip_reasoning,
)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    clear_routing()


def test_complete_uses_routed_model_and_params(monkeypatch):
    snap = {
        "endpoints": {"ep-local": endpoint()},
        "profiles": {"p": profile("p", "banner-gpu", model="qwen3-vl-8b-instruct", max_tokens_cap=256)},
        "routes": [route("r1", "vision", "p"), route("r2", "agent", "p"), route("r3", "text", "p")],
    }
    calls = install_routing(monkeypatch, '{"banner_detected": false}', snapshot=snap)
    result = gateway.complete("vision.banner", "read the banner", image_b64="aGVsbG8=", max_tokens=600)
    assert result["success"] is True
    assert result["profile"] == "banner-gpu" and result["via"] == "vision"
    call = calls[0]
    assert call["model"] == "qwen3-vl-8b-instruct"
    assert call["max_tokens"] == 256
    assert call["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert call["messages"][0]["content"][1]["type"] == "image"


def test_fallback_on_error_then_success(monkeypatch):
    snap = {
        "endpoints": {"ep-local": endpoint()},
        "profiles": {"p1": profile("p1", "primary", fallback_profile_id="p2"), "p2": profile("p2", "backup")},
        "routes": [route("r1", "text", "p1"), route("r2", "agent", "p1"), route("r3", "vision", "p1")],
    }
    calls = install_routing(monkeypatch, [RuntimeError("GPU down"), "translated"], snapshot=snap)
    result = gateway.complete("text.translation", "hola")
    assert result["success"] is True and result["content"] == "translated"
    assert result["profile"] == "backup" and result["fallback_used"] is True
    assert len(calls) == 2


def test_empty_answer_retries_then_fails_over(monkeypatch):
    snap = {
        "endpoints": {"ep-local": endpoint()},
        "profiles": {"p1": profile("p1", "primary", fallback_profile_id="p2"), "p2": profile("p2", "backup")},
        "routes": [route("r1", "text", "p1"), route("r2", "agent", "p1"), route("r3", "vision", "p1")],
    }
    calls = install_routing(monkeypatch, ["", "", "", "ok"], snapshot=snap)
    result = gateway.complete("text", "x")
    assert result["content"] == "ok" and result["profile"] == "backup"
    assert len(calls) == gateway.EMPTY_RETRIES + 2


def _refusal(text=""):
    return SimpleNamespace(text=lambda: text, stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"),
                           usage=SimpleNamespace(input_tokens=3, output_tokens=0))


def test_refusal_fails_over_without_retrying_the_same_hop(monkeypatch):
    snap = {
        "endpoints": {"ep-local": endpoint()},
        "profiles": {"p1": profile("p1", "primary", fallback_profile_id="p2"), "p2": profile("p2", "backup")},
        "routes": [route("r1", "text", "p1"), route("r2", "agent", "p1"), route("r3", "vision", "p1")],
    }
    calls = install_routing(monkeypatch, [_refusal("partial"), "ok"], snapshot=snap)
    result = gateway.complete("text", "x")
    assert result["content"] == "ok" and result["profile"] == "backup" and result["fallback_used"] is True
    assert len(calls) == 2


def test_refusal_on_every_hop_is_a_failed_result(monkeypatch):
    snap = {
        "endpoints": {"ep-local": endpoint()},
        "profiles": {"p1": profile("p1", "primary", fallback_profile_id="p2"), "p2": profile("p2", "backup")},
        "routes": [route("r1", "text", "p1"), route("r2", "agent", "p1"), route("r3", "vision", "p1")],
    }
    install_routing(monkeypatch, [_refusal(), _refusal()], snapshot=snap)
    result = gateway.complete("text", "x")
    assert result["success"] is False and "model refused (category: cyber)" in result["error"]


def test_all_hops_fail_reports_every_error(monkeypatch):
    calls = install_routing(monkeypatch, RuntimeError("refused"))
    result = gateway.complete("text", "x")
    assert result["success"] is False and "refused" in result["error"]
    assert len(calls) == 1


def test_host_reach_endpoint_skipped_on_server(monkeypatch):
    snap = {
        "endpoints": {"lan": endpoint("lan", "lan-gpu", reach="host"), "ep-local": endpoint()},
        "profiles": {"p1": profile("p1", "lan", endpoint_id="lan", fallback_profile_id="p2"),
                     "p2": profile("p2", "server-side")},
        "routes": [route("r1", "vision", "p1"), route("r2", "agent", "p2"), route("r3", "text", "p2")],
    }
    install_routing(monkeypatch, "fine", snapshot=snap)
    result = gateway.complete("vision.ask", "q", image_b64="aGVsbG8=")
    assert result["success"] is True and result["profile"] == "server-side"


def test_unknown_usage_is_a_failed_result_not_an_exception(monkeypatch):
    install_routing(monkeypatch)
    result = gateway.complete("vision.unknown", "x")
    assert result["success"] is False and "Unknown AI usage" in result["error"]


def test_is_available_needs_credentials(monkeypatch):
    snap = {
        "endpoints": {"e": endpoint("e", "cloud", preset="openrouter", secret_name="missing-secret")},
        "profiles": {"p": profile("p", endpoint_id="e")},
        "routes": [route("r1", "vision", "p"), route("r2", "agent", "p"), route("r3", "text", "p")],
    }
    install_routing(monkeypatch, snapshot=snap)
    monkeypatch.setattr(router, "get_secret", lambda name: None)
    assert gateway.is_available("vision.banner") is False
    monkeypatch.setattr(router, "get_secret", lambda name: "sk-test")
    assert gateway.is_available("vision.banner") is True


# ------------------------------------------------------------------ provider presets
def test_create_client_per_preset():
    local = create_client("openai_compatible", None, base_url="http://10.0.0.5:1234/v1", timeout=45)
    assert isinstance(local, OpenAICompatibleProviderClient)
    assert local.base_url == "http://10.0.0.5:1234/v1" and local.timeout == 45
    router_client = create_client("openrouter", "sk")
    assert router_client.base_url == "https://openrouter.ai/api/v1"
    assert router_client.extra_headers["X-Title"] == "VirtualPyTest"
    assert isinstance(create_client("minimax", "k"), AnthropicProviderClient)
    assert isinstance(create_client("google", "k"), GoogleProviderClient)


def test_create_client_requires_key_and_base_url():
    with pytest.raises(ValueError):
        create_client("anthropic", None)
    with pytest.raises(ValueError):
        create_client("openai_compatible", None)
    with pytest.raises(ValueError):
        create_client("nope", "k")


def test_strip_reasoning():
    assert strip_reasoning("<think>hmm</think>\n{\"a\": 1}") == '{"a": 1}'
    assert strip_reasoning("<think>never closed") == ""
    assert strip_reasoning("plain") == "plain"


def test_openai_payload_flags(monkeypatch):
    sent = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "<think>x</think>{}"}}], "usage": {}}

    def fake_post(url, headers, json, timeout):
        sent.update(json)
        return _Resp()

    import shared.src.lib.ai.provider_client as pc
    monkeypatch.setattr(pc.requests, "post", fake_post)
    client = create_client("openai", "sk")
    resp = client.create(model="gpt-5.5", max_tokens=16000, system=[], messages=[{"role": "user", "content": "x"}],
                         tools=[], temperature=0.0,
                         extra_body={"max_tokens_param": "max_completion_tokens", "omit_temperature": True,
                                     "reasoning_effort": "medium"})
    assert sent["max_completion_tokens"] == 16000 and "max_tokens" not in sent
    assert "temperature" not in sent and sent["reasoning_effort"] == "medium"
    assert resp.text() == "{}"


def test_minimax_vlm_client_sends_prompt_and_image(monkeypatch):
    sent = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"content": "(a) View: Home"}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, **json)
        return _Resp()

    import shared.src.lib.ai.provider_client as pc
    monkeypatch.setattr(pc.requests, "post", fake_post)
    client = create_client("minimax_vlm", "mm")
    resp = pc.single_completion(client, model="minimax-vlm", prompt="describe", image_b64="QUJD", system="be brief")
    assert sent["url"] == "https://api.minimax.io/v1/coding_plan/vlm"
    assert sent["prompt"] == "be brief\n\ndescribe"
    assert sent["image_url"] == "data:image/jpeg;base64,QUJD"
    assert resp.text() == "(a) View: Home"
    with pytest.raises(ValueError):
        client.create(model="m", max_tokens=10, system=[], messages=[{"role": "user", "content": "x"}],
                      tools=[{"name": "t"}])


# ------------------------------------------------------------------ endpoint failover
def _pc_snapshot():
    """Route vision -> PC (local LM Studio) with a cloud fallback, like a home-GPU setup."""
    return {
        "endpoints": {"pc": endpoint("pc", "lmstudio-pc"), "cloud": endpoint("cloud", "openrouter", preset="openrouter")},
        "profiles": {"p-pc": profile("p-pc", "qwen-pc", endpoint_id="pc", fallback_profile_id="p-cloud"),
                     "p-cloud": profile("p-cloud", "qwen-cloud", endpoint_id="cloud")},
        "routes": [route("r1", "vision", "p-pc"), route("r2", "agent", "p-cloud"), route("r3", "text", "p-cloud")],
    }


def test_unreachable_endpoint_is_skipped_until_it_recovers(monkeypatch):
    import requests
    calls = install_routing(monkeypatch, [requests.exceptions.ConnectionError("PC off"), "cloud answer",
                                          "cloud again", "pc back"], snapshot=_pc_snapshot())
    first = gateway.complete("vision.ask", "q", image_b64="aGVsbG8=")
    assert first["profile"] == "qwen-cloud" and first["fallback_used"] is True
    assert router.endpoint_down_for("pc") > 50

    # While the PC is marked down the cloud profile is tried first: no second connect attempt.
    second = gateway.complete("vision.ask", "q", image_b64="aGVsbG8=")
    assert second["profile"] == "qwen-cloud" and second["fallback_used"] is True
    assert len(calls) == 3

    # After the pause the PC is tried again and a success clears the mark.
    monkeypatch.setattr(router.time, "time", lambda: 10 ** 12)
    third = gateway.complete("vision.ask", "q", image_b64="aGVsbG8=")
    assert third["profile"] == "qwen-pc" and third["fallback_used"] is False
    assert router.endpoint_down_for("pc") == 0


def test_http_errors_do_not_mark_the_endpoint_down(monkeypatch):
    calls = install_routing(monkeypatch, [RuntimeError("500 model crashed"), "cloud answer"], snapshot=_pc_snapshot())
    assert gateway.complete("vision.ask", "q", image_b64="aGVsbG8=")["profile"] == "qwen-cloud"
    assert router.endpoint_down_for("pc") == 0
    assert len(calls) == 2


class _NoCredit(Exception):
    status_code = 402


def test_no_credit_pauses_the_endpoint_for_every_usage_until_a_probe_answers(monkeypatch):
    # BUG-0492: a 402 was retried on every request (117k failed alert-triage calls a day, Jev localize too).
    real_record = router.record
    calls = install_routing(monkeypatch, [_NoCredit("402"), "cloud", "cloud", "cloud", _NoCredit("402"), "cloud",
                                          "pc back"], snapshot=_pc_snapshot())
    monkeypatch.setattr(router, "record", real_record)
    from shared.src.lib.ai import call_log
    monkeypatch.setattr(call_log, "submit", lambda row: None)
    now = [1000.0]
    monkeypatch.setattr(router.time, "time", lambda: now[0])

    assert gateway.complete("vision.ask", "q", image_b64="aGVsbG8=")["profile"] == "qwen-cloud"
    assert router.no_credit_for("pc") == router.NO_CREDIT_START_S
    # Paused: no request reaches the PC endpoint, from this usage or any other one routed to it.
    for usage in ("vision.ask", "vision.alert_triage"):
        res = gateway.complete(usage, "q", image_b64="aGVsbG8=")
        assert res["profile"] == "qwen-cloud" and res["fallback_used"] is True
    assert len(calls) == 4  # 1 failed probe + 3 cloud answers

    # Pause over: one probe, still 402 -> the pause doubles.
    now[0] += router.NO_CREDIT_START_S + 1
    gateway.complete("vision.ask", "q", image_b64="aGVsbG8=")
    assert router.no_credit_for("pc") == router.NO_CREDIT_STEPS_S[1] and len(calls) == 6

    # Credit is back: the next probe answers and ends the pause.
    now[0] += router.NO_CREDIT_STEPS_S[1] + 1
    assert gateway.complete("vision.ask", "q", image_b64="aGVsbG8=")["profile"] == "qwen-pc"
    assert router.no_credit_for("pc") == 0


def test_no_credit_with_no_fallback_fails_fast_without_a_request(monkeypatch):
    real_record = router.record
    snap = {"endpoints": {"or": endpoint("or", "openrouter", preset="openrouter")},
            "profiles": {"p": profile("p", "jev", endpoint_id="or")},
            "routes": [route("r1", "text", "p"), route("r2", "agent", "p"), route("r3", "vision", "p")]}
    calls = install_routing(monkeypatch, [_NoCredit("402")], snapshot=snap)
    monkeypatch.setattr(router, "record", real_record)
    from shared.src.lib.ai import call_log
    monkeypatch.setattr(call_log, "submit", lambda row: None)
    assert gateway.complete("text.translation", "q")["success"] is False
    res = gateway.complete("text.translation", "q")
    assert res["success"] is False and "no credit" in res["error"] and len(calls) == 1


def test_everything_down_still_tries_in_chain_order(monkeypatch):
    install_routing(monkeypatch, "late answer", snapshot=_pc_snapshot())
    for eid in ("pc", "cloud"):
        router.mark_down(router.Hop(profile={}, endpoint={"id": eid, "name": eid}))
    res = router.resolve("vision.ask")
    assert [h.profile_name for h in res.hops] == ["qwen-pc", "qwen-cloud"]


def test_connection_error_classification_and_timeouts():
    import anthropic
    import httpx
    import requests
    from shared.src.lib.ai.provider_client import http_timeout, is_connection_error
    assert is_connection_error(requests.exceptions.ConnectionError("refused"))
    assert is_connection_error(requests.exceptions.ConnectTimeout("slow connect"))
    assert not is_connection_error(requests.exceptions.ReadTimeout("slow model"))
    assert not is_connection_error(RuntimeError("HTTP 500"))
    assert is_connection_error(anthropic.APIConnectionError(request=httpx.Request("POST", "http://x")))
    assert http_timeout(300) == (5, 300) and http_timeout(3) == (3, 3)


def _or_snapshot(usage="text.decision.localize"):
    return {"endpoints": {"or": endpoint("or", "openrouter", preset="openrouter")},
            "profiles": {"p": profile("p", "jev", endpoint_id="or")},
            "routes": [route("r1", "text", "p"), route("r2", "agent", "p"), route("r3", "vision", "p")]}


def _paused_setup(monkeypatch):
    """Pause the openrouter endpoint with one 402; returns (calls, clock, recorded rows)."""
    real_record = router.record
    calls = install_routing(monkeypatch, [_NoCredit("402")] + ["answer"] * 5, snapshot=_or_snapshot())
    rows = []
    monkeypatch.setattr(router, "record", real_record)
    from shared.src.lib.ai import call_log
    monkeypatch.setattr(call_log, "submit", lambda row: rows.append(row))
    now = [1000.0]
    monkeypatch.setattr(router.time, "time", lambda: now[0])
    assert gateway.complete("text.translation", "q")["success"] is False
    assert router.no_credit_for("or") == router.NO_CREDIT_STEPS_S[0]
    return calls, now, rows


def test_pause_ends_by_a_free_credit_check_without_a_paid_call(monkeypatch):
    calls, now, _ = _paused_setup(monkeypatch)
    now[0] += router.NO_CREDIT_STEPS_S[0] + 1
    monkeypatch.setattr(router, "credit_available", lambda hop: False)
    res = gateway.complete("text.translation", "q")
    # still no credit: the wait grew 5 -> 15 min and no request was sent
    assert res["success"] is False and len(calls) == 1
    assert router.no_credit_for("or") == router.NO_CREDIT_STEPS_S[1]
    now[0] += router.NO_CREDIT_STEPS_S[1] + 1
    monkeypatch.setattr(router, "credit_available", lambda hop: True)
    assert gateway.complete("text.translation", "q")["success"] is True
    assert router.no_credit_for("or") == 0


def test_shadow_usage_is_skipped_counted_and_never_the_probe(monkeypatch):
    calls, now, rows = _paused_setup(monkeypatch)
    rows.clear()
    monkeypatch.setattr(router, "credit_available", lambda hop: None)  # balance unreadable
    now[0] += router.NO_CREDIT_STEPS_S[0] + 1
    # shadow usage waits even after the wait is over: it must not spend a call to find out
    for _ in range(2):
        assert gateway.complete("text.decision.sherlock", "q")["success"] is False
    assert len(calls) == 1
    skipped = [r for r in rows if r.get("outcome") == "skipped"]
    assert len(skipped) == 2 and skipped[0]["stop_reason"] == router.PAUSED_REASON
    # a normal usage is the probe and ends the pause when it answers
    assert gateway.complete("text.translation", "q")["success"] is True
    assert router.no_credit_for("or") == 0
