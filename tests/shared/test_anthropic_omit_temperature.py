"""Anthropic profile flags must not leak into the request body.

`claude-haiku-5-5` rejects `temperature` entirely; the profile's
`extra.omit_temperature` flag must be consumed by the client, not sent.
"""
from shared.src.lib.ai.provider_client import (
    _SDK_ACCEPTS_TEMPERATURE,
    AnthropicProviderClient,
)


class _Messages:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return {"ok": True}


class _Client:
    def __init__(self):
        self.messages = _Messages()


def _client():
    client = AnthropicProviderClient(api_key="test-key")
    client._client = _Client()
    return client


def test_omit_temperature_is_consumed_and_temperature_dropped():
    client = _client()
    client.create(model="claude-haiku-5-5", max_tokens=16, temperature=0.0,
                  extra_body={"omit_temperature": True, "output_config": {"effort": "low"}})
    sent = client._client.messages.kwargs
    assert "temperature" not in sent
    assert sent["extra_body"] == {"output_config": {"effort": "low"}}


def test_without_the_flag_temperature_still_sent():
    client = _client()
    client.create(model="claude-sonnet-4", max_tokens=16, temperature=0.2,
                  extra_body={"output_config": {"effort": "low"}})
    sent = client._client.messages.kwargs
    # On the PINNED SDK (<1.0) `Messages.create` still takes `temperature`, so it is sent unchanged.
    # SDK 1.x rewrote `create()` with an explicit keyword-only signature and dropped the parameter, so
    # sending it would raise TypeError before the request; the client feature-detects and omits it.
    if _SDK_ACCEPTS_TEMPERATURE:
        assert sent["temperature"] == 0.2
    else:
        assert "temperature" not in sent
    assert sent["extra_body"] == {"output_config": {"effort": "low"}}


def test_empty_extra_body_is_dropped():
    client = _client()
    client.create(model="claude-sonnet-4", max_tokens=16, extra_body={"omit_temperature": True})
    sent = client._client.messages.kwargs
    assert "extra_body" not in sent
