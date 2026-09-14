"""
Provider-aware AI client compatibility layer, shared by the agent runtime and
the verification (vision/text) path.

The agent keeps Anthropic-style turn history and tool-loop semantics; this module
adapts every supported provider to that internal shape. Content blocks use the
Anthropic shape internally:
- text:  {"type": "text", "text": ...}
- image: {"type": "image", "source": {"type": "base64", "media_type": ..., "data": ...}}
- tool_use / tool_result as per the agent manager.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import requests

import anthropic

from .config import (
    LOCAL_AI_PLACEHOLDER_KEY,
    LOCAL_PROVIDER,
    get_local_ai_base_url,
    get_local_ai_timeout,
    normalize_provider,
)


@dataclass
class ProviderBlock:
    type: str
    text: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[dict[str, Any]] = None


def _block_as_dict(block: Any) -> dict[str, Any]:
    """Normalize a content block to a dict for provider conversion.

    Assistant turns are stored in history as ``list[ProviderBlock]`` (see
    manager._run_turn), while tool_result/image turns are plain dicts. The compat
    converters use dict access, so coerce ProviderBlock into a dict here.
    """
    if isinstance(block, ProviderBlock):
        return {
            "type": block.type,
            "text": block.text,
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    return block


@dataclass
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class ProviderResponse:
    content: list[ProviderBlock]
    usage: ProviderUsage
    stop_reason: str = "end_turn"
    model: str = ""

    def text(self) -> str:
        """Concatenate all text blocks (convenience for non-agent callers)."""
        return "".join(b.text for b in self.content if b.type == "text" and b.text)


class BaseProviderClient:
    """Base compatibility client with Anthropic-like `.messages.create(...)`."""

    def __init__(self, provider: str, api_key: str):
        self.provider = normalize_provider(provider)
        self.api_key = api_key
        self.messages = self

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: Optional[dict[str, Any]] = None,
        temperature: Optional[float] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> ProviderResponse:
        raise NotImplementedError


class AnthropicProviderClient(BaseProviderClient):
    def __init__(self, api_key: str, base_url: Optional[str] = None, provider: str = "anthropic"):
        super().__init__(provider, api_key)
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**client_kwargs)

    def create(self, **kwargs: Any) -> Any:
        # The Anthropic SDK rejects empty `tools`/`system`, a `tool_choice` without tools,
        # and None-valued kwargs. Drop them so text/vision calls (no tools) work too.
        if not kwargs.get("tools"):
            kwargs.pop("tools", None)
            kwargs.pop("tool_choice", None)
        if not kwargs.get("system"):
            kwargs.pop("system", None)
        if kwargs.get("extra_headers") is None:
            kwargs.pop("extra_headers", None)
        if kwargs.get("temperature") is None:
            kwargs.pop("temperature", None)
        return self._client.messages.create(**kwargs)


class OpenAICompatibleProviderClient(BaseProviderClient):
    """OpenAI-style tool calling + multimodal for OpenAI, OpenRouter and local servers."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        extra_headers: Optional[dict[str, str]] = None,
        timeout: int = 60,
    ):
        super().__init__(provider, api_key)
        self.base_url = base_url.rstrip("/")
        self.extra_headers = extra_headers or {}
        self.timeout = timeout

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: Optional[dict[str, Any]] = None,
        temperature: Optional[float] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> ProviderResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(system, messages),
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = self._convert_tools(tools)
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = False
        if temperature is not None:
            payload["temperature"] = temperature

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
            **(extra_headers or {}),
        }

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        blocks: list[ProviderBlock] = []

        text_content = message.get("content")
        if isinstance(text_content, str) and text_content.strip():
            blocks.append(ProviderBlock(type="text", text=text_content))
        elif isinstance(text_content, list):
            for part in text_content:
                text = part.get("text") if isinstance(part, dict) else None
                if text:
                    blocks.append(ProviderBlock(type="text", text=text))

        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            arguments = function.get("arguments") or "{}"
            try:
                parsed_arguments = json.loads(arguments)
            except json.JSONDecodeError:
                parsed_arguments = {"raw": arguments}
            blocks.append(
                ProviderBlock(
                    type="tool_use",
                    id=tool_call.get("id") or f"tool_{uuid.uuid4().hex[:8]}",
                    name=function.get("name"),
                    input=parsed_arguments,
                )
            )

        usage = data.get("usage") or {}
        finish_reason = choice.get("finish_reason") or "stop"
        stop_reason = "tool_use" if finish_reason == "tool_calls" else finish_reason
        return ProviderResponse(
            content=blocks,
            usage=ProviderUsage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            ),
            stop_reason=stop_reason,
            model=data.get("model") or model,
        )

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted = []
        for tool in tools:
            converted.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        return converted

    def _convert_messages(self, system: list[dict[str, Any]], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        system_text = self._extract_system_text(system)
        if system_text:
            converted.append({"role": "system", "content": system_text})

        for message in messages:
            converted.extend(self._convert_message(message))
        return converted

    def _convert_message(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        role = message.get("role")
        content = message.get("content")
        if isinstance(content, str):
            return [{"role": role, "content": content}]

        if not isinstance(content, list):
            return []

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in (_block_as_dict(b) for b in content):
                block_type = block.get("type")
                if block_type == "text" and block.get("text"):
                    text_parts.append(block["text"])
                elif block_type == "tool_use":
                    tool_calls.append({
                        "id": block.get("id") or f"tool_{uuid.uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": block.get("name"),
                            "arguments": json.dumps(block.get("input") or {}),
                        },
                    })
            return [{
                "role": "assistant",
                "content": "\n".join(text_parts) if text_parts else None,
                "tool_calls": tool_calls or None,
            }]

        if role == "user":
            converted: list[dict[str, Any]] = []
            parts: list[dict[str, Any]] = []  # multimodal parts (text + image_url)
            for block in (_block_as_dict(b) for b in content):
                block_type = block.get("type")
                if block_type == "tool_result":
                    converted.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id"),
                        "content": block.get("content", ""),
                    })
                elif block_type == "text" and block.get("text"):
                    parts.append({"type": "text", "text": block["text"]})
                elif block_type == "image":
                    source = block.get("source") or {}
                    if source.get("type") == "base64":
                        media_type = source.get("media_type", "image/jpeg")
                        data = source.get("data", "")
                        parts.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{data}"},
                        })
            if parts:
                # Collapse to a plain string when there is only text (matches prior behaviour);
                # use OpenAI multimodal list form when any image is present.
                if all(p["type"] == "text" for p in parts):
                    user_content: Any = "\n".join(p["text"] for p in parts)
                else:
                    user_content = parts
                converted.insert(0, {"role": "user", "content": user_content})
            return converted

        return []

    def _extract_system_text(self, system: list[dict[str, Any]]) -> str:
        return "\n".join(block.get("text", "") for block in system if block.get("type") == "text" and block.get("text"))


class GoogleProviderClient(BaseProviderClient):
    """Gemini native generateContent adapter with function calling + multimodal."""

    def __init__(self, api_key: str):
        super().__init__("google", api_key)

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: Optional[dict[str, Any]] = None,
        temperature: Optional[float] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> ProviderResponse:
        tool_name_map = self._build_tool_name_map(messages)
        payload: dict[str, Any] = {
            "contents": self._convert_messages(messages, tool_name_map),
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature if temperature is not None else 0,
            },
        }

        system_text = self._extract_system_text(system)
        if system_text:
            payload["system_instruction"] = {"parts": [{"text": system_text}]}

        if tools:
            payload["tools"] = [{
                "functionDeclarations": [
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                    }
                    for tool in tools
                ]
            }]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": self.api_key},
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        candidate = (data.get("candidates") or [{}])[0]
        content = candidate.get("content") or {}
        blocks: list[ProviderBlock] = []

        for part in content.get("parts") or []:
            if part.get("text"):
                blocks.append(ProviderBlock(type="text", text=part["text"]))
            if part.get("functionCall"):
                function_call = part["functionCall"]
                blocks.append(
                    ProviderBlock(
                        type="tool_use",
                        id=function_call.get("id") or f"tool_{uuid.uuid4().hex[:8]}",
                        name=function_call.get("name"),
                        input=function_call.get("args") or {},
                    )
                )

        usage = data.get("usageMetadata") or {}
        finish_reason = candidate.get("finishReason") or "STOP"
        stop_reason = "tool_use" if finish_reason == "FUNCTION_CALL" else finish_reason.lower()
        return ProviderResponse(
            content=blocks,
            usage=ProviderUsage(
                input_tokens=usage.get("promptTokenCount", 0),
                output_tokens=usage.get("candidatesTokenCount", 0),
            ),
            stop_reason=stop_reason,
            model=model,
        )

    def _extract_system_text(self, system: list[dict[str, Any]]) -> str:
        return "\n".join(block.get("text", "") for block in system if block.get("type") == "text" and block.get("text"))

    def _build_tool_name_map(self, messages: list[dict[str, Any]]) -> dict[str, str]:
        tool_name_map: dict[str, str] = {}
        for message in messages:
            content = message.get("content")
            if message.get("role") != "assistant" or not isinstance(content, list):
                continue
            for block in (_block_as_dict(b) for b in content):
                if block.get("type") == "tool_use" and block.get("id") and block.get("name"):
                    tool_name_map[block["id"]] = block["name"]
        return tool_name_map

    def _convert_messages(self, messages: list[dict[str, Any]], tool_name_map: dict[str, str]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if isinstance(content, str):
                converted.append({
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": content}],
                })
                continue

            if not isinstance(content, list):
                continue

            parts: list[dict[str, Any]] = []
            outgoing_role = "model" if role == "assistant" else "user"
            for block in (_block_as_dict(b) for b in content):
                block_type = block.get("type")
                if block_type == "text" and block.get("text"):
                    parts.append({"text": block["text"]})
                elif block_type == "image":
                    source = block.get("source") or {}
                    if source.get("type") == "base64":
                        parts.append({
                            "inline_data": {
                                "mime_type": source.get("media_type", "image/jpeg"),
                                "data": source.get("data", ""),
                            }
                        })
                elif block_type == "tool_use":
                    parts.append({
                        "functionCall": {
                            "id": block.get("id") or f"tool_{uuid.uuid4().hex[:8]}",
                            "name": block.get("name"),
                            "args": block.get("input") or {},
                        }
                    })
                elif block_type == "tool_result":
                    tool_name = tool_name_map.get(block.get("tool_use_id"), "tool_result")
                    response_content = block.get("content", "")
                    try:
                        parsed_response = json.loads(response_content)
                    except Exception:
                        parsed_response = {"content": response_content}
                    parts.append({
                        "functionResponse": {
                            "name": tool_name,
                            "response": parsed_response,
                        }
                    })
            if parts:
                converted.append({"role": outgoing_role, "parts": parts})
        return converted


def create_provider_client(provider: str, api_key: str) -> BaseProviderClient:
    """Factory for provider compatibility clients."""
    normalized = normalize_provider(provider)
    if normalized == "anthropic":
        return AnthropicProviderClient(api_key)
    if normalized == "openrouter":
        return OpenAICompatibleProviderClient(
            provider=normalized,
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            extra_headers={
                "HTTP-Referer": "https://virtualpytest.angelstreet.io",
                "X-Title": "VirtualPyTest",
            },
        )
    if normalized == "openai":
        return OpenAICompatibleProviderClient(
            provider=normalized,
            api_key=api_key,
            base_url="https://api.openai.com/v1",
        )
    if normalized == "minimax":
        return AnthropicProviderClient(
            api_key=api_key,
            base_url="https://api.minimax.io/anthropic",
            provider=normalized,
        )
    if normalized == "google":
        return GoogleProviderClient(api_key)
    if normalized == LOCAL_PROVIDER:
        base_url = get_local_ai_base_url()
        if not base_url:
            raise ValueError(
                "LOCAL_AI_BASE_URL not set — point it at an OpenAI-compatible server, "
                "e.g. http://10.10.10.10:8000/v1 (Ollama: http://<host>:11434/v1)"
            )
        return OpenAICompatibleProviderClient(
            provider=normalized,
            api_key=api_key or LOCAL_AI_PLACEHOLDER_KEY,
            base_url=base_url,
            timeout=get_local_ai_timeout(),
        )
    raise ValueError(f"Unsupported AI provider: {provider}")


def validate_provider_credentials(provider: str, api_key: str, model: str) -> None:
    """Run a tiny completion to validate provider credentials and model reachability."""
    client = create_provider_client(provider, api_key)
    client.messages.create(
        model=model,
        max_tokens=16,
        system=[{"type": "text", "text": "You are a connectivity check."}],
        messages=[{"role": "user", "content": "Reply with OK"}],
        tools=[],
        tool_choice=None,
        temperature=None,
        extra_headers=None,
    )


# =============================================================================
# High-level convenience helpers (used by the verification text/vision path)
# =============================================================================

def complete_text(
    *,
    provider: str,
    api_key: str,
    model: str,
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 1000,
    temperature: float = 0.0,
) -> ProviderResponse:
    """Single-shot text completion. Returns a ProviderResponse (use .text())."""
    client = create_provider_client(provider, api_key)
    return client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system}] if system else [],
        messages=[{"role": "user", "content": prompt}],
        tools=[],
        tool_choice=None,
        temperature=temperature,
        extra_headers=None,
    )


def complete_vision(
    *,
    provider: str,
    api_key: str,
    model: str,
    prompt: str,
    image_b64: str,
    media_type: str = "image/jpeg",
    system: Optional[str] = None,
    max_tokens: int = 1000,
    temperature: float = 0.0,
) -> ProviderResponse:
    """Single-shot vision completion with one base64 image. Returns a ProviderResponse."""
    client = create_provider_client(provider, api_key)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
        ],
    }]
    return client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system}] if system else [],
        messages=messages,
        tools=[],
        tool_choice=None,
        temperature=temperature,
        extra_headers=None,
    )
