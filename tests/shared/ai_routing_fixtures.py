"""Test helpers for AI routing (TASK-30): a fixed routing snapshot and a fake provider.

No DB, no network, no keys: ``install_routing`` puts a working set straight into the
resolver cache, marks the process as a server (local routing), replaces every hop's
client with a fake that records calls, and silences stats recording.
"""
from types import SimpleNamespace

from shared.src.lib.ai import gateway, router

ENDPOINT_ID = "ep-local"
PROFILE_ID = "pf-default"


class FakeMessages:
    def __init__(self, calls, answer):
        self.calls = calls
        self.answer = answer

    def create(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.answer.pop(0) if isinstance(self.answer, list) else self.answer
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, SimpleNamespace):  # a full scripted response (e.g. a refusal)
            return answer
        return SimpleNamespace(
            text=lambda: answer,
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
        )


def endpoint(eid=ENDPOINT_ID, name="local", preset="openai_compatible", **extra):
    return {"id": eid, "name": name, "preset": preset, "base_url": "http://gpu.test:1234/v1",
            "secret_name": None, "reach": "server", "timeout_s": 30, "max_concurrency": None,
            "allowed_team_ids": None, "enabled": True, **extra}


def profile(pid=PROFILE_ID, name="default", model="qwen3-vl-8b", endpoint_id=ENDPOINT_ID, **extra):
    return {"id": pid, "name": name, "endpoint_id": endpoint_id, "model": model, "temperature": None,
            "max_tokens_cap": None, "thinking": "auto", "image_max_edge": None, "extra": {},
            "fallback_profile_id": None, "capabilities": [], "enabled": True, **extra}


def route(rid, usage_key, profile_id=PROFILE_ID, team_id=None, **extra):
    return {"id": rid, "team_id": team_id, "usage_key": usage_key, "profile_id": profile_id,
            "host_name": None, "device_model": None, "userinterface_name": None, "split_profile_id": None,
            "split_percent": None, "priority": 100, "enabled": True, **extra}


def default_snapshot():
    return {
        "endpoints": {ENDPOINT_ID: endpoint()},
        "profiles": {PROFILE_ID: profile()},
        "routes": [route("r-agent", "agent"), route("r-vision", "vision"), route("r-text", "text")],
    }


def install_routing(monkeypatch, answer='{"ok": true}', snapshot=None):
    """Install ``snapshot`` (default: one local endpoint serving the three roots).

    Returns the list of recorded ``messages.create`` kwargs; ``calls.clients`` lists
    the (profile name) of the hop each call went to.
    """
    calls = []
    fake = SimpleNamespace(messages=FakeMessages(calls, answer))
    router.set_snapshot_for_tests(snapshot or default_snapshot())
    router.reset_health_for_tests()
    monkeypatch.setattr(router, "CACHE_TTL_S", 10 ** 9)
    monkeypatch.setattr(router.Hop, "client", lambda self, timeout=None: fake)
    monkeypatch.setattr(router, "record", lambda *a, **k: None)
    monkeypatch.setattr(gateway, "_local_routing", True)
    monkeypatch.setattr(gateway, "RETRY_SLEEP_S", 0)
    return calls


def clear_routing():
    router.set_snapshot_for_tests(None)
    router.reset_health_for_tests()
