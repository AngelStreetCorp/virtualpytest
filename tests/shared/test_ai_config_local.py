"""Tests for the "local" AI provider (any OpenAI-compatible server the operator runs).

shared/src/lib/ai/config.py resolves it from LOCAL_AI_BASE_URL / LOCAL_AI_MODEL /
LOCAL_AI_API_KEY instead of the fixed per-provider tables, and
provider_client.create_provider_client() builds an OpenAICompatibleProviderClient
on that base URL with a long timeout. Pure config tests, no network.

Run: pytest tests/shared/test_ai_config_local.py -v
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.ai import config  # noqa: E402

LOCAL_ENVS = (
    "AI_PROVIDER", "AI_AGENT_PROVIDER", "AI_AGENT_MODEL", "AI_VISION_PROVIDER", "AI_VISION_MODEL",
    "AI_TEXT_PROVIDER", "AI_TEXT_MODEL", "LOCAL_AI_BASE_URL", "LOCAL_AI_MODEL", "LOCAL_AI_API_KEY",
    "LOCAL_AI_TIMEOUT",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in LOCAL_ENVS:
        monkeypatch.delenv(name, raising=False)


def _configure(monkeypatch, base_url="http://10.10.10.10:8000/v1/", model="glm-5.2"):
    monkeypatch.setenv("AI_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_AI_BASE_URL", base_url)
    monkeypatch.setenv("LOCAL_AI_MODEL", model)


def test_local_is_a_supported_provider():
    assert config.normalize_provider("local") == "local"
    assert config.normalize_provider("LOCAL ") == "local"


def test_resolves_every_task_without_a_key(monkeypatch):
    _configure(monkeypatch)
    for task in config.TASK_TYPES:
        cfg = config.resolve_task(task)
        assert cfg == {"provider": "local", "model": "glm-5.2", "api_key": config.LOCAL_AI_PLACEHOLDER_KEY}
        assert config.is_task_available(task)


def test_explicit_key_is_used_when_set(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("LOCAL_AI_API_KEY", "vllm-secret")
    assert config.get_provider_api_key("local") == "vllm-secret"


def test_per_task_model_override_and_slash_kept(monkeypatch):
    # vLLM model ids are HuggingFace paths; the "provider/" strip must not touch them.
    _configure(monkeypatch, model="Qwen/Qwen3-8B")
    monkeypatch.setenv("AI_VISION_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
    assert config.get_active_model(task="agent") == "Qwen/Qwen3-8B"
    assert config.get_active_model(task="vision") == "Qwen/Qwen2.5-VL-7B-Instruct"


def test_missing_base_url_is_not_configured(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_AI_MODEL", "glm-5.2")
    with pytest.raises(ValueError, match="LOCAL_AI_BASE_URL"):
        config.get_provider_api_key("local")
    assert not config.is_task_available("agent")


def test_missing_model_falls_back_per_task_and_names_the_env(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_AI_BASE_URL", "http://10.10.10.10:8000/v1")
    # AI_PROVIDER=local cannot serve any task without LOCAL_AI_MODEL -> per-task default provider.
    assert config.get_active_provider("agent") == config.DEFAULT_PROVIDER_BY_TASK["agent"]
    with pytest.raises(ValueError, match="LOCAL_AI_MODEL"):
        config.get_default_model("local", "agent")


def test_provider_models_matrix_reflects_env(monkeypatch):
    assert config.get_provider_models()["local"] == {"agent": None, "vision": None, "text": None}
    _configure(monkeypatch, model="qwen3:8b")
    assert config.get_provider_models()["local"] == {"agent": "qwen3:8b", "vision": "qwen3:8b", "text": "qwen3:8b"}
    # The static table is untouched.
    assert config.PROVIDER_MODELS["local"]["agent"] is None


def test_active_settings_report_base_url_as_the_config(monkeypatch):
    _configure(monkeypatch)
    settings = config.get_active_ai_settings()
    assert settings["provider"] == "local"
    assert settings["api_key_env"] == "LOCAL_AI_BASE_URL"
    assert settings["api_key_configured"] is True
    assert settings["supports_prompt_caching"] is False


def test_validate_provider_model_accepts_any_local_name():
    assert config.validate_provider_model("local", "anything-goes") is None


def test_client_factory_uses_base_url_and_long_timeout(monkeypatch):
    pytest.importorskip("anthropic")
    from shared.src.lib.ai.provider_client import OpenAICompatibleProviderClient, create_provider_client

    _configure(monkeypatch)
    client = create_provider_client("local", config.get_provider_api_key("local"))
    assert isinstance(client, OpenAICompatibleProviderClient)
    assert client.base_url == "http://10.10.10.10:8000/v1"  # trailing slash stripped
    assert client.api_key == config.LOCAL_AI_PLACEHOLDER_KEY
    assert client.timeout == config.LOCAL_AI_DEFAULT_TIMEOUT

    monkeypatch.setenv("LOCAL_AI_TIMEOUT", "45")
    assert create_provider_client("local", "k").timeout == 45

    monkeypatch.delenv("LOCAL_AI_BASE_URL")
    with pytest.raises(ValueError, match="LOCAL_AI_BASE_URL"):
        create_provider_client("local", "k")
