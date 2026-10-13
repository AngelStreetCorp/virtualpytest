"""
AI provider presets (TASK-30).

Which model serves which AI call is no longer configured here: it lives in the
database (``ai_endpoints`` / ``ai_profiles`` / ``ai_routes``) and is resolved per
usage by ``shared.src.lib.ai.router``. API keys live server-side in the secrets
store (``shared.src.lib.ai.secrets_store``).

This module only describes what each kind of endpoint *is*: the client class it
needs, its default base URL, and provider-specific behaviour the agent relies on
(prompt caching, MiniMax thinking budget, OpenRouter headers).

Langfuse tracing of every AI call: see ``tracing.py`` (LANGFUSE_HOST / _PUBLIC_KEY /
_SECRET_KEY, read at call time).
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ProviderPreset:
    name: str
    label: str
    client: str  # "anthropic" | "openai_compatible" | "google" | "minimax_vlm"
    base_url: Optional[str]
    needs_key: bool = True
    supports_prompt_caching: bool = False
    extra_headers: dict = field(default_factory=dict)
    # Lists its models at GET <base_url>/models (OpenAI shape) — used by the Test button.
    lists_models: bool = False
    # How the provider searches the web inside one completion (usages that need "web"):
    # "anthropic_tool" (server web_search tool), "openrouter_plugin" (plugins: web),
    # "google_grounding" (google_search tool). None: this preset cannot search.
    web_search: Optional[str] = None
    # A fixed subscription (MiniMax coding plan): every call costs 0 per call and shows "included in plan".
    flat_plan: bool = False


PRESETS: dict[str, ProviderPreset] = {p.name: p for p in (
    ProviderPreset("anthropic", "Anthropic", "anthropic", None, supports_prompt_caching=True,
                   web_search="anthropic_tool"),
    ProviderPreset(
        "openrouter", "OpenRouter", "openai_compatible", "https://openrouter.ai/api/v1",
        extra_headers={"HTTP-Referer": "https://virtualpytest.angelstreet.io", "X-Title": "VirtualPyTest"},
        lists_models=True, web_search="openrouter_plugin",
    ),
    ProviderPreset("openai", "OpenAI", "openai_compatible", "https://api.openai.com/v1", lists_models=True),
    ProviderPreset("minimax", "MiniMax", "anthropic", "https://api.minimax.io/anthropic", flat_plan=True),
    ProviderPreset("google", "Google Gemini", "google", "https://generativelanguage.googleapis.com/v1beta",
                   web_search="google_grounding"),
    # MiniMax coding-plan VLM: single image + prompt -> text description (no tools, no chat).
    ProviderPreset("minimax_vlm", "MiniMax VLM (coding plan)", "minimax_vlm",
                   "https://api.minimax.io/v1/coding_plan/vlm", flat_plan=True),
    # Any OpenAI-compatible server: LM Studio, Ollama, vLLM, llama.cpp... base_url required.
    ProviderPreset("openai_compatible", "OpenAI-compatible (local)", "openai_compatible", None,
                   needs_key=False, lists_models=True),
)}

REACH_VALUES = ("server", "host")
THINKING_VALUES = ("auto", "on", "off")

# Sent as Bearer to keyless OpenAI-compatible servers; LM Studio/Ollama/llama.cpp ignore it.
KEYLESS_PLACEHOLDER = "local"

MAX_TOKENS = 8192



def get_preset(name: Optional[str]) -> ProviderPreset:
    preset = PRESETS.get((name or "").strip().lower())
    if not preset:
        raise ValueError(f"Unknown AI provider preset '{name}'. Expected one of: {', '.join(PRESETS)}")
    return preset


def presets_catalogue() -> list[dict]:
    """Serializable preset list for the settings UI."""
    return [
        {
            "name": p.name,
            "label": p.label,
            "base_url": p.base_url,
            "needs_key": p.needs_key,
            "base_url_required": p.base_url is None and p.client == "openai_compatible",
            "lists_models": p.lists_models,
            "web_search": bool(p.web_search),
        }
        for p in PRESETS.values()
    ]
