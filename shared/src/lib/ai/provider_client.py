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
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

import anthropic

from .config import KEYLESS_PLACEHOLDER, get_preset

# Connecting must fail fast even when generation is allowed to take minutes: a local
# model on a PC that is switched off would otherwise hold every call for the whole
# endpoint timeout before the fallback profile gets a chance.
CONNECT_TIMEOUT_S = 5


def http_timeout(timeout: int) -> tuple[float, float]:
    """(connect, read) timeout for requests: short connect, endpoint-sized read."""
    return (min(CONNECT_TIMEOUT_S, timeout), timeout)


class ModelRefusal(Exception):
    """The model declined the request (``stop_reason == "refusal"``, HTTP 200): try the next hop."""

    def __init__(self, response: Any):
        details = getattr(response, "stop_details", None)
        self.category = getattr(details, "category", None) if details is not None else None
        self.response = response
        super().__init__(f"model refused (category: {self.category or 'unknown'})")


def raise_on_refusal(response: Any) -> Any:
    """Return ``response``, or raise ModelRefusal when the model declined it."""
    if getattr(response, "stop_reason", None) == "refusal":
        raise ModelRefusal(response)
    return response


def is_connection_error(exc: BaseException) -> bool:
    """True when the endpoint could not be reached at all (down, refused, DNS, connect timeout).

    A read timeout or an HTTP error is NOT one: the server answered or accepted the call.
    """
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout)):
        return not isinstance(exc, requests.exceptions.ReadTimeout)
    if isinstance(exc, anthropic.APIConnectionError):
        return not isinstance(exc, anthropic.APITimeoutError) or "connect" in str(exc).lower()
    try:
        import httpx
        return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
    except ImportError:  # pragma: no cover
        return False


class RequestNotSent(ValueError):
    """Our own client refused the call before any request left (no image, no key, no URL): nothing was sent or billed,
    so the call log counts it as skipped, not as a failed request."""


ERROR_TYPES = ("timeout", "rate_limit", "no_credit", "auth", "bad_request", "server", "connection",
               "empty_answer", "busy", "parse", "refusal", "other")


def classify_error(exc: BaseException) -> str:
    """Map a provider exception onto the fixed ``ai_calls.error_type`` list."""
    if isinstance(exc, ModelRefusal):
        return "refusal"
    if is_connection_error(exc):
        return "connection"
    status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status == 429:
            return "rate_limit"
        if status == 402:
            return "no_credit"
        if status in (401, 403):
            return "auth"
        if status >= 500:
            return "server"
        if status >= 400:
            return "bad_request"
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "jsondecode" in name:
        return "server"  # the provider answered with something that is not JSON
    if isinstance(exc, ValueError):
        # Raised by our own clients before a request leaves: a missing image on MiniMax VLM, tools on a
        # chat-less endpoint, a missing key or base URL. The request was wrong, not the provider.
        return "bad_request"
    return "other"


_THINK_RE = re.compile(r"<think>[\s\S]*?</think>\s*")


def strip_reasoning(text: Optional[str]) -> str:
    """Drop ``<think>…</think>`` blocks some models inline in their answer.

    An unterminated ``<think>`` (the budget ran out mid-thought) leaves no answer.
    """
    if not text:
        return ""
    stripped = _THINK_RE.sub("", text)
    if "<think>" in stripped:
        stripped = stripped.split("<think>", 1)[0]
    return stripped.strip()


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
    reasoning_tokens: int = 0
    web_searches: int = 0
    # Cost the provider itself reported for this call (OpenRouter ``usage.cost``), in USD.
    cost: Optional[float] = None


def _openai_usage(usage: dict) -> ProviderUsage:
    """OpenAI-shaped ``usage`` object -> ProviderUsage (cache, reasoning, search and cost fields)."""
    # Chat Completions names (prompt_/completion_tokens) or the Responses API names (input_/output_tokens).
    prompt_details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
    cost = usage.get("cost")
    cache_read = int(prompt_details.get("cached_tokens") or 0)
    cache_write = int(prompt_details.get("cache_write_tokens") or 0)
    prompt = usage.get("prompt_tokens") if usage.get("prompt_tokens") is not None else usage.get("input_tokens")
    completion = (usage.get("completion_tokens") if usage.get("completion_tokens") is not None
                  else usage.get("output_tokens"))
    return ProviderUsage(
        # Anthropic meaning, like the field names: the uncached part. ``prompt_tokens`` counts the cache too.
        input_tokens=max(int(prompt or 0) - cache_read - cache_write, 0),
        output_tokens=int(completion or 0),
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
        reasoning_tokens=int(completion_details.get("reasoning_tokens") or 0),
        web_searches=int((usage.get("server_tool_use") or {}).get("web_search_requests") or 0),
        cost=float(cost) if isinstance(cost, (int, float)) else None,
    )


@dataclass
class ProviderResponse:
    content: list[ProviderBlock]
    usage: ProviderUsage
    stop_reason: str = "end_turn"
    model: str = ""
    # Web pages the answer was grounded on (web-search calls): [{"url", "title"}].
    sources: list[dict[str, str]] = field(default_factory=list)

    def text(self) -> str:
        """Concatenate all text blocks (convenience for non-agent callers)."""
        return "".join(b.text for b in self.content if b.type == "text" and b.text)


class BaseProviderClient:
    """Base compatibility client with Anthropic-like `.messages.create(...)`."""

    def __init__(self, provider: str, api_key: str):
        self.provider = provider
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
        extra_body: Optional[dict[str, Any]] = None,
    ) -> ProviderResponse:
        raise NotImplementedError


MAX_CACHE_BREAKPOINTS = 4  # Anthropic per-request limit; the automatic breakpoint takes one of them


def _sdk_accepts(name: str) -> bool:
    """Does the INSTALLED anthropic SDK's ``Messages.create`` take this keyword?

    The SDK's signature is not stable across the range this repo allows
    (backend_server/requirements.txt: ``anthropic>=0.40.0,<1.0``). 1.x rewrote ``create()`` with an explicit
    keyword-only signature and DROPPED ``temperature`` from it, so a call that carries it raises
    ``TypeError: Messages.create() got an unexpected keyword argument 'temperature'`` before a byte goes
    out. That is what the M3.1-Flash profile on the ``minimax`` (Anthropic-compatible) endpoint hit:
    ``gateway.execute`` defaults ``temperature`` to 0.0, and 0.0 is not None, so the wrapper kept it.

    Feature-detected once at import: the wrapper then sends the parameter only where it exists, which is
    exactly the old behaviour on the pinned SDK and no breakage on a newer one.
    """
    try:
        import inspect
        from anthropic.resources.messages import Messages
        return name in inspect.signature(Messages.create).parameters
    except Exception:  # noqa: BLE001 — an unknown SDK is treated as "accepts everything we may send"
        return True


_SDK_ACCEPTS_TEMPERATURE = _sdk_accepts('temperature')


def cache_breakpoints(kwargs: dict[str, Any]) -> int:
    """Explicit ``cache_control`` markers in a request's tools, system and message blocks."""
    blocks: list[Any] = list(kwargs.get("tools") or []) + list(kwargs.get("system") or [])
    for message in kwargs.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            blocks.extend(content)
    return sum(1 for b in blocks if isinstance(b, dict) and b.get("cache_control"))


def _wants_auto_cache(kwargs: dict[str, Any]) -> bool:
    """Automatic caching only pays on a conversation (more than one message), where the next request
    re-sends this one's tail. On a one-shot call the tail is the unique part (a screenshot, a question):
    caching it is a write surcharge never read back, so those rely on the system-block breakpoint."""
    return len(kwargs.get("messages") or []) > 1 and cache_breakpoints(kwargs) < MAX_CACHE_BREAKPOINTS


class AnthropicProviderClient(BaseProviderClient):
    def __init__(self, api_key: str, base_url: Optional[str] = None, provider: str = "anthropic",
                 timeout: int = 120, default_headers: Optional[dict[str, str]] = None):
        super().__init__(provider, api_key)
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            # anthropic.Timeout follows whichever HTTP lib the installed SDK uses (httpx or httpx2).
            "timeout": anthropic.Timeout(timeout, connect=min(CONNECT_TIMEOUT_S, timeout)),
            # Fallback profiles handle an unreachable endpoint; SDK retries would only delay them.
            "max_retries": 0,
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        if default_headers:
            client_kwargs["default_headers"] = default_headers
        self._client = anthropic.Anthropic(**client_kwargs)

    def create(self, **kwargs: Any) -> Any:
        # The Anthropic SDK rejects empty `tools`/`system`, a `tool_choice` without tools,
        # and None-valued kwargs. Drop them so text/vision calls (no tools) work too.
        if not kwargs.get("tools"):
            kwargs.pop("tools", None)
            kwargs.pop("tool_choice", None)
        elif kwargs.get("tool_choice") is None:
            kwargs.pop("tool_choice", None)
        if not kwargs.get("system"):
            kwargs.pop("system", None)
        if kwargs.get("extra_headers") is None:
            kwargs.pop("extra_headers", None)
        if kwargs.get("temperature") is None:
            kwargs.pop("temperature", None)
        # ``omit_temperature`` is a profile flag, not an Anthropic body field: some
        # models (e.g. claude-haiku-5-5) reject `temperature` entirely. Consume the
        # flag here so it is never sent, and drop the parameter when it is set.
        extra_body = dict(kwargs.get("extra_body") or {})
        if extra_body.pop("omit_temperature", False):
            kwargs.pop("temperature", None)
        if not _SDK_ACCEPTS_TEMPERATURE:
            # The installed SDK has no `temperature` parameter at all (1.x rewrote create() with an
            # explicit keyword-only signature), so sending it raises TypeError before the request.
            # Nothing is lost by dropping it: the profile sets none, so the model samples by default.
            kwargs.pop("temperature", None)
        if self.provider == "anthropic" and _wants_auto_cache(kwargs):
            # Top-level automatic caching keeps the growing conversation tail cached. SDK 0.58 has no
            # ``cache_control`` argument, so it goes in the body.
            extra_body.setdefault("cache_control", {"type": "ephemeral"})
        if extra_body:
            kwargs["extra_body"] = extra_body
        else:
            kwargs.pop("extra_body", None)
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
        extra_body: Optional[dict[str, Any]] = None,
    ) -> ProviderResponse:
        extra = dict(extra_body or {})
        # Profile flags for reasoning models (e.g. GPT-5): they reject max_tokens and a
        # non-default temperature.
        token_param = extra.pop("max_tokens_param", None) or "max_tokens"
        omit_temperature = bool(extra.pop("omit_temperature", False))
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(system, messages),
            token_param: max_tokens,
        }
        if tools:
            payload["tools"] = self._convert_tools(tools)
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = False
        if temperature is not None and not omit_temperature:
            payload["temperature"] = temperature
        if self.provider == "openrouter":
            payload["usage"] = {"include": True}  # makes OpenRouter return the billed cost
        payload.update(extra)

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
            timeout=http_timeout(self.timeout),
        )
        if response.status_code >= 400:
            # raise_for_status() alone drops the body, which is the only place the
            # provider says WHY (a bare "400 Bad Request" hid BUG-0177).
            raise requests.HTTPError(
                f"{response.status_code} from {self.provider}: {response.text[:500]}",
                response=response,
            )
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        blocks: list[ProviderBlock] = []

        # Reasoning is never part of the answer: `reasoning_content` is ignored and
        # inline <think> blocks are stripped.
        text_content = message.get("content")
        if isinstance(text_content, str) and strip_reasoning(text_content):
            blocks.append(ProviderBlock(type="text", text=strip_reasoning(text_content)))
        elif isinstance(text_content, list):
            for part in text_content:
                text = strip_reasoning(part.get("text")) if isinstance(part, dict) else None
                if text:
                    blocks.append(ProviderBlock(type="text", text=text))

        sources = [
            {"url": (a.get("url_citation") or {}).get("url", ""), "title": (a.get("url_citation") or {}).get("title", "")}
            for a in message.get("annotations") or []
            if isinstance(a, dict) and a.get("type") == "url_citation"
        ]

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
            usage=_openai_usage(usage),
            stop_reason=stop_reason,
            model=data.get("model") or model,
            sources=sources,
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

    def __init__(self, api_key: str, base_url: str = "https://generativelanguage.googleapis.com/v1beta",
                 timeout: int = 60):
        super().__init__("google", api_key)
        self.base_url = base_url.rstrip("/")
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
        extra_body: Optional[dict[str, Any]] = None,
    ) -> ProviderResponse:
        extra = dict(extra_body or {})
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
        elif extra.get("google_search"):
            payload["tools"] = [{"google_search": {}}]

        response = requests.post(
            f"{self.base_url}/models/{model}:generateContent",
            params={"key": self.api_key},
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=http_timeout(self.timeout),
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

        grounding = candidate.get("groundingMetadata") or {}
        sources = [
            {"url": (chunk.get("web") or {}).get("uri", ""), "title": (chunk.get("web") or {}).get("title", "")}
            for chunk in grounding.get("groundingChunks") or []
            if chunk.get("web")
        ]

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
            sources=sources,
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


class MiniMaxVLMClient(BaseProviderClient):
    """MiniMax coding-plan VLM: one prompt + one image in, a text description out.

    Not a chat API — no tools, no history. The last user message's text and first
    image are sent; a system prompt is prepended to the text.
    """

    def __init__(self, api_key: str, base_url: str, timeout: int = 60):
        super().__init__("minimax_vlm", api_key)
        self.base_url = base_url
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
        extra_body: Optional[dict[str, Any]] = None,
    ) -> ProviderResponse:
        if tools:
            raise RequestNotSent("The MiniMax VLM endpoint does not support tool calling")
        content = messages[-1].get("content") if messages else ""
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        texts = [b.get("text", "") for b in (_block_as_dict(x) for x in blocks) if b.get("type") == "text"]
        images = [b.get("source") or {} for b in (_block_as_dict(x) for x in blocks) if b.get("type") == "image"]
        if not images:
            raise RequestNotSent("The MiniMax VLM endpoint needs an image")
        system_text = "\n".join(b.get("text", "") for b in system if b.get("type") == "text")
        prompt = "\n\n".join(t for t in [system_text, *texts] if t)
        source = images[0]
        response = requests.post(
            self.base_url,
            json={"prompt": prompt,
                  "image_url": f"data:{source.get('media_type', 'image/jpeg')};base64,{source.get('data', '')}"},
            headers={"content-type": "application/json", "authorization": f"Bearer {self.api_key}"},
            timeout=http_timeout(self.timeout),
        )
        if response.status_code >= 400:
            raise requests.HTTPError(f"{response.status_code} from minimax_vlm: {response.text[:500]}",
                                     response=response)
        payload = response.json() or {}
        # A provider-level error can arrive with HTTP 200 and an EMPTY content field. MiniMax does exactly
        # that when the coding plan's token allowance is used up: HTTP 200, body
        # {"content":"", "base_resp":{"status_code":2056,"status_msg":"Token Plan usage limit reached"}}.
        # Read as an empty answer it is invisible: the call looks like the model had nothing to say, so it
        # is logged as an empty answer (which the dashboard calls wasted) instead of the quota wall it
        # really is, and the caller cannot tell "the plan is finished" from "this frame was hard".
        # Surface it as a failure carrying the provider's own words, mapped to the fixed error_type list:
        # a token-plan limit is a quota wall, i.e. no_credit (402), not an empty answer.
        base = payload.get('base_resp') or {}
        code = base.get('status_code')
        if isinstance(code, int) and code != 0:
            msg = str(base.get('status_msg') or payload.get('content') or f'provider error {code}')
            lowered = msg.lower()
            status = 402 if ('usage limit' in lowered or 'token plan' in lowered
                             or 'quota' in lowered or 'insufficient' in lowered) else 400
            err = requests.HTTPError(f"{status} from minimax_vlm: {msg} (base_resp {code})")
            err.response = requests.Response()
            err.response.status_code = status
            err.response._content = str(payload).encode()
            raise err
        text = payload.get("content")
        return ProviderResponse(
            content=[ProviderBlock(type="text", text=strip_reasoning(text))] if isinstance(text, str) and text.strip() else [],
            usage=ProviderUsage(),
            model=model,
        )


def create_client(preset: str, api_key: Optional[str], base_url: Optional[str] = None,
                  timeout: int = 120, headers: Optional[dict[str, str]] = None) -> BaseProviderClient:
    """Build the compatibility client for one endpoint (see ``config.PRESETS``). ``headers`` go on every request
    (an Anthropic user key's ``anthropic-workspace-id``)."""
    spec = get_preset(preset)
    url = (base_url or "").strip() or spec.base_url
    if spec.needs_key and not api_key:
        raise RequestNotSent(f"No API key configured for this {spec.label} endpoint")
    key = api_key or KEYLESS_PLACEHOLDER
    if spec.client == "anthropic":
        return AnthropicProviderClient(api_key=key, base_url=url, provider=spec.name, timeout=timeout,
                                       default_headers=headers)
    if spec.client == "google":
        return GoogleProviderClient(key, base_url=url, timeout=timeout)
    if spec.client == "minimax_vlm":
        return MiniMaxVLMClient(key, url, timeout=timeout)
    if not url:
        raise RequestNotSent(f"A base URL is required for a {spec.label} endpoint")
    return OpenAICompatibleProviderClient(
        provider=spec.name,
        api_key=key,
        base_url=url,
        extra_headers=dict(spec.extra_headers),
        timeout=timeout,
    )


def normalize_stop_reason(resp: Any) -> Optional[str]:
    """The response's stop reason in Anthropic terms (OpenAI ``length`` -> ``max_tokens``, ``stop`` -> ``end_turn``)."""
    reason = getattr(resp, "stop_reason", None)
    if not isinstance(reason, str):
        return None
    return {"length": "max_tokens", "stop": "end_turn", "MAX_TOKENS": "max_tokens"}.get(reason, reason)


def response_text(resp: Any) -> str:
    """Answer text from either response shape, reasoning removed.

    OpenAICompatible/Google clients return a ProviderResponse (``.text()``); the
    Anthropic client passes the SDK Message through (``.content`` blocks, thinking
    blocks excluded).
    """
    textf = getattr(resp, "text", None)
    if callable(textf):
        return strip_reasoning(textf())
    blocks = list(getattr(resp, "content", None) or [])
    # A web-search answer interleaves narration ("Let me search...") with the searches;
    # the answer is the text after the last search result.
    last_search = max((i for i, blk in enumerate(blocks) if getattr(blk, "type", None) == "web_search_tool_result"),
                      default=-1)
    return strip_reasoning("".join(
        getattr(b, "text", "") or ""
        for b in blocks[last_search + 1:]
        if getattr(b, "type", None) == "text"
    ))


def response_sources(resp: Any) -> list[dict[str, str]]:
    """Web pages a web-search answer was grounded on, deduplicated by URL.

    ProviderResponse carries them in ``.sources``; an Anthropic SDK Message has them in
    ``web_search_tool_result`` blocks and in the text blocks' citations.
    """
    found: list[dict[str, str]] = list(getattr(resp, "sources", None) or [])
    if not isinstance(resp, ProviderResponse):
        for block in getattr(resp, "content", None) or []:
            kind = getattr(block, "type", None)
            if kind == "web_search_tool_result":
                results = getattr(block, "content", None)
                for item in results if isinstance(results, list) else []:
                    if getattr(item, "url", None):
                        found.append({"url": item.url, "title": getattr(item, "title", "") or ""})
            elif kind == "text":
                for cite in getattr(block, "citations", None) or []:
                    if getattr(cite, "url", None):
                        found.append({"url": cite.url, "title": getattr(cite, "title", "") or ""})
    seen: set[str] = set()
    unique = []
    for source in found:
        if source.get("url") and source["url"] not in seen:
            seen.add(source["url"])
            unique.append(source)
    return unique


# Searches one web-grounded completion may run (Anthropic max_uses / OpenRouter max_results).
WEB_SEARCH_MAX = 3


def web_search_request(mechanism: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(tools, extra_body) that make one completion search the web, per ``ProviderPreset.web_search``."""
    if mechanism == "anthropic_tool":
        return [{"type": "web_search_20250305", "name": "web_search", "max_uses": WEB_SEARCH_MAX}], {}
    if mechanism == "openrouter_plugin":
        return [], {"plugins": [{"id": "web", "max_results": WEB_SEARCH_MAX}]}
    if mechanism == "google_grounding":
        return [], {"google_search": True}
    raise ValueError(f"Unknown web search mechanism '{mechanism}'")


def response_tokens(resp: Any) -> tuple[int, int]:
    """(prompt tokens including cached ones, output tokens) of a response."""
    used = response_usage(resp)
    return used.tokens_in, used.tokens_out


@dataclass
class CallUsage:
    """Everything a response says about what the call consumed (and, if given, cost).

    ``tokens_in`` is the whole prompt on every provider: uncached + cache read + cache write. Anthropic's
    ``input_tokens`` is only the uncached part (0 when the whole prompt was cached, as on MiniMax)."""
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0
    web_searches: int = 0
    cost: Optional[float] = None  # provider-reported, USD


def _num(obj: Any, name: str) -> int:
    value = getattr(obj, name, 0)
    return int(value) if isinstance(value, (int, float)) else 0


def openai_call_usage(usage: dict) -> CallUsage:
    """CallUsage from a raw OpenAI-shaped ``usage`` dict (passthrough and host-side callers)."""
    u = _openai_usage(usage or {})
    return CallUsage(tokens_in=u.input_tokens + u.cache_read_input_tokens + u.cache_creation_input_tokens,
                     tokens_out=u.output_tokens, cache_read=u.cache_read_input_tokens,
                     cache_write=u.cache_creation_input_tokens, reasoning=u.reasoning_tokens,
                     web_searches=u.web_searches, cost=u.cost)


def anthropic_call_usage(usage: dict) -> CallUsage:
    """CallUsage from a raw Anthropic Messages ``usage`` dict (scripts that call /v1/messages themselves).
    ``input_tokens`` there is the uncached part: the cache counts are added back."""
    usage = usage or {}
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    return CallUsage(tokens_in=int(usage.get("input_tokens") or 0) + cache_read + cache_write,
                     tokens_out=int(usage.get("output_tokens") or 0), cache_read=cache_read, cache_write=cache_write,
                     web_searches=int((usage.get("server_tool_use") or {}).get("web_search_requests") or 0))


def response_usage(resp: Any) -> CallUsage:
    """Full usage of a response: tokens plus cache-read / cache-write / reasoning / web searches / cost.

    Works on ProviderResponse and on the Anthropic SDK message (``cache_*_input_tokens``,
    ``server_tool_use.web_search_requests``). ``response_tokens`` keeps returning (in, out) only.
    """
    usage = getattr(resp, "usage", None)
    if usage is None:
        return CallUsage()
    server_tool = getattr(usage, "server_tool_use", None)
    cost = getattr(usage, "cost", None)
    cache_read, cache_write = _num(usage, "cache_read_input_tokens"), _num(usage, "cache_creation_input_tokens")
    return CallUsage(
        tokens_in=_num(usage, "input_tokens") + cache_read + cache_write,
        tokens_out=_num(usage, "output_tokens"),
        cache_read=cache_read,
        cache_write=cache_write,
        reasoning=_num(usage, "reasoning_tokens"),
        web_searches=_num(usage, "web_searches") or _num(server_tool, "web_search_requests"),
        cost=float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
    )


def single_completion(
    client: BaseProviderClient,
    *,
    model: str,
    prompt: str,
    image_b64: Optional[str] = None,
    media_type: str = "image/jpeg",
    system: Optional[str] = None,
    max_tokens: int = 1000,
    temperature: Optional[float] = 0.0,
    extra_body: Optional[dict[str, Any]] = None,
    web_search: Optional[str] = None,
) -> Any:
    """One text (or text + one image) completion, no tools.

    ``web_search`` (a ``ProviderPreset.web_search`` mechanism) lets the provider search the
    web before answering; the pages used come back via ``response_sources``.

    The system prompt is the stable part and carries the prompt-cache breakpoint; the image and the
    prompt change per call and come after it. A system prompt under the model's minimum cacheable
    size (512-4096 tokens) is simply not cached. Non-Anthropic clients read only the block text.
    """
    if image_b64 is not None:
        content: Any = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
            {"type": "text", "text": prompt},
        ]
    else:
        content = prompt
    tools: list[dict[str, Any]] = []
    if web_search:
        tools, web_extra = web_search_request(web_search)
        extra_body = {**(extra_body or {}), **web_extra}
    return client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if system else [],
        messages=[{"role": "user", "content": content}],
        tools=tools,
        tool_choice=None,
        temperature=temperature,
        extra_headers=None,
        extra_body=extra_body,
    )


def connectivity_response(client: BaseProviderClient, model: str) -> Any:
    """Tiny completion proving the endpoint, key and model work. Returns the raw response."""
    return single_completion(client, model=model, prompt="Reply with OK", system="You are a connectivity check.",
                             max_tokens=16, temperature=None)


def check_connectivity(client: BaseProviderClient, model: str) -> str:
    """Tiny completion proving the endpoint, key and model work. Returns the reply."""
    return response_text(connectivity_response(client, model))
