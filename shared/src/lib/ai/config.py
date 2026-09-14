"""
Centralized AI provider configuration shared by backend_server (agent) and
backend_host (vision/text verification).

Three task types, each resolved independently to a (provider, model, api_key):
- "agent"  : tool-calling chat (Atlas)
- "vision" : image analysis (subtitle/banner/screen detection)
- "text"   : plain text (translation, transcript analysis)

Environment variables (all optional; code supplies per-provider defaults):
- AI_PROVIDER                            primary provider, default for ALL tasks
- AI_AGENT_PROVIDER  / AI_AGENT_MODEL    agent override
- AI_VISION_PROVIDER / AI_VISION_MODEL   vision override
- AI_TEXT_PROVIDER   / AI_TEXT_MODEL     text override
- ANTHROPIC_API_KEY / OPENROUTER_API_KEY / OPENAI_API_KEY / MINIMAX_API_KEY / GOOGLE_API_KEY

Local / self-hosted models (provider "local" = any OpenAI-compatible server: Ollama,
vLLM, llama.cpp, LM Studio, Colibri...):
- LOCAL_AI_BASE_URL   required, e.g. http://10.10.10.10:8000/v1 (the /chat/completions parent)
- LOCAL_AI_MODEL      default model for every task (AI_<TASK>_MODEL still overrides per task)
- LOCAL_AI_API_KEY    optional; only if the server enforces one (vLLM --api-key)
- LOCAL_AI_TIMEOUT    seconds per request, default 300 (local models are slow)

Optional (LLM observability - auto-enabled when LANGFUSE_HOST is set):
- LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
"""

import os
from typing import Optional

SUPPORTED_PROVIDERS = ("anthropic", "openrouter", "openai", "minimax", "google", "local")

# "local" is any OpenAI-compatible HTTP server the operator runs themselves. It has no
# fixed model catalogue and usually no API key, so it is configured by LOCAL_AI_* envs
# instead of the per-provider tables below.
LOCAL_PROVIDER = "local"
LOCAL_AI_PLACEHOLDER_KEY = "local"  # sent as Bearer when LOCAL_AI_API_KEY is unset; Ollama/llama.cpp ignore it
LOCAL_AI_DEFAULT_TIMEOUT = 300

TASK_TYPES = ("agent", "vision", "text")

# Env var prefix per task type (provider/model envs are AI_<PREFIX>_PROVIDER / _MODEL).
_TASK_ENV_PREFIX = {
    "agent": "AI_AGENT",
    "vision": "AI_VISION",
    "text": "AI_TEXT",
}

AI_PROVIDER_ENV_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "google": "GOOGLE_API_KEY",
    "local": "LOCAL_AI_API_KEY",
}

DEFAULT_PROVIDER = "anthropic"

# Fallback provider per task when neither AI_<TASK>_PROVIDER nor a task-capable
# AI_PROVIDER is set. Vision/text historically run on OpenRouter; the agent on
# Anthropic. Keeps things working out-of-the-box without explicit config.
DEFAULT_PROVIDER_BY_TASK = {
    "agent": "anthropic",
    "vision": "openrouter",
    "text": "openrouter",
}

# Per-provider default model for each task type. None = provider cannot serve that task.
PROVIDER_MODELS: dict[str, dict[str, Optional[str]]] = {
    "anthropic": {
        "agent": "claude-sonnet-4-20250514",
        "vision": "claude-sonnet-4-20250514",
        "text": "claude-sonnet-4-20250514",
    },
    "openrouter": {
        "agent": "openai/gpt-4.1-mini",
        "vision": "qwen/qwen3-vl-8b-instruct",
        "text": "openai/gpt-4.1-mini",
    },
    "openai": {
        "agent": "gpt-4.1-mini",
        "vision": "gpt-4.1-mini",
        "text": "gpt-4.1-mini",
    },
    "minimax": {
        "agent": "MiniMax-M2.7-highspeed",
        "vision": None,  # no vision-language model available
        "text": "MiniMax-M2.7-highspeed",
    },
    "google": {
        "agent": "gemini-2.5-flash",
        "vision": "gemini-2.5-flash",
        "text": "gemini-2.5-flash",
    },
    # Filled at runtime from LOCAL_AI_MODEL (see _provider_model / get_provider_models).
    "local": {
        "agent": None,
        "vision": None,
        "text": None,
    },
}

# Backward-compatible flat map: provider -> default agent model.
DEFAULT_MODEL_BY_PROVIDER = {provider: models["agent"] for provider, models in PROVIDER_MODELS.items()}

MAX_TOKENS = 8192

# Langfuse observability (auto-enabled if LANGFUSE_HOST is configured)
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "")
LANGFUSE_ENABLED = bool(LANGFUSE_HOST)

# Optional temporary overrides keyed by user/session identifier (agent task only).
_user_ai_configs: dict[str, dict[str, str]] = {}


def _normalize_task(task: Optional[str]) -> str:
    normalized = (task or "agent").strip().lower()
    return normalized if normalized in TASK_TYPES else "agent"


def get_local_ai_base_url() -> str:
    """LOCAL_AI_BASE_URL without a trailing slash ("" when unset)."""
    return os.getenv("LOCAL_AI_BASE_URL", "").strip().rstrip("/")


def get_local_ai_timeout() -> int:
    try:
        return int(os.getenv("LOCAL_AI_TIMEOUT", "").strip() or LOCAL_AI_DEFAULT_TIMEOUT)
    except ValueError:
        return LOCAL_AI_DEFAULT_TIMEOUT


def _provider_model(provider: str, task: str) -> Optional[str]:
    """Default model for provider+task; the local provider reads LOCAL_AI_MODEL at call time."""
    if provider == LOCAL_PROVIDER:
        return os.getenv("LOCAL_AI_MODEL", "").strip() or None
    return PROVIDER_MODELS[provider].get(task)


def get_provider_models() -> dict[str, dict[str, Optional[str]]]:
    """PROVIDER_MODELS with the local provider resolved from the environment (for the settings UI)."""
    matrix = {provider: dict(models) for provider, models in PROVIDER_MODELS.items()}
    matrix[LOCAL_PROVIDER] = {task: _provider_model(LOCAL_PROVIDER, task) for task in TASK_TYPES}
    return matrix


def normalize_provider(provider: Optional[str]) -> str:
    """Normalize provider value and fall back to the project default."""
    normalized = (provider or DEFAULT_PROVIDER).strip().lower()
    if normalized not in SUPPORTED_PROVIDERS:
        return DEFAULT_PROVIDER
    return normalized


# Expected model-name prefixes per provider — used to catch wrong-family
# combos (e.g. minimax + sonnet) before a blocking LLM call. openrouter routes
# any model id so it has no prefix constraint.
KNOWN_MODEL_PREFIXES = {
    "anthropic": ("claude-",),
    "minimax": ("minimax-",),
    "openai": ("gpt-", "o1-", "o3-", "o4-"),
    "google": ("gemini-",),
    "openrouter": (),
    "local": (),
}


def validate_provider_model(provider: Optional[str], model: Optional[str]) -> Optional[str]:
    """Return None if the combo looks valid, else a user-facing error string."""
    p = normalize_provider(provider)
    m = (model or "").strip()
    if not m:
        return f"No model configured for provider '{p}'."
    if p == "openrouter":
        return None
    prefixes = KNOWN_MODEL_PREFIXES.get(p, ())
    if not prefixes:
        return None
    if not any(m.lower().startswith(prefix) for prefix in prefixes):
        examples = ", ".join(f"{prefix}…" for prefix in prefixes)
        return (
            f"Model '{m}' is not valid for provider '{p}'. "
            f"Expected a model name starting with: {examples}"
        )
    return None


def get_provider_api_env(provider: Optional[str] = None) -> str:
    """Return the API key env var name for a provider."""
    return AI_PROVIDER_ENV_MAP[normalize_provider(provider)]


def get_default_model(provider: Optional[str] = None, task: str = "agent") -> str:
    """Return the default model for a provider + task.

    Raises ValueError if the provider has no model for the task (e.g. minimax + vision).
    """
    provider = normalize_provider(provider)
    task = _normalize_task(task)
    model = _provider_model(provider, task)
    if not model:
        if provider == LOCAL_PROVIDER:
            raise ValueError(
                "Provider 'local' has no model configured. Set LOCAL_AI_MODEL to the model name "
                "your server exposes (e.g. 'qwen3:8b' for Ollama, 'Qwen/Qwen3-8B' for vLLM)."
            )
        raise ValueError(
            f"Provider '{provider}' has no '{task}' model configured. "
            f"Set AI_{task.upper()}_PROVIDER to a provider that supports {task} "
            f"(e.g. openrouter, anthropic, openai, google)."
        )
    return model


def get_active_provider(task: str = "agent") -> str:
    """Resolve the provider for a task.

    Order: AI_<TASK>_PROVIDER -> AI_PROVIDER (only if it can serve the task) ->
    per-task default (DEFAULT_PROVIDER_BY_TASK). The "can serve the task" check
    means a vision-incapable primary (e.g. minimax) still falls back to a vision
    provider instead of failing.
    """
    task = _normalize_task(task)
    task_env = os.getenv(f"{_TASK_ENV_PREFIX[task]}_PROVIDER", "").strip()
    if task_env:
        return normalize_provider(task_env)

    primary_env = os.getenv("AI_PROVIDER", "").strip()
    if primary_env:
        primary = normalize_provider(primary_env)
        if _provider_model(primary, task):
            return primary

    return DEFAULT_PROVIDER_BY_TASK.get(task, DEFAULT_PROVIDER)


def get_active_model(provider: Optional[str] = None, task: str = "agent") -> str:
    """Resolve the model for a task, falling back to the provider's default for that task."""
    task = _normalize_task(task)
    active_provider = normalize_provider(provider or get_active_provider(task))
    configured = (os.getenv(f"{_TASK_ENV_PREFIX[task]}_MODEL") or "").strip()
    model = configured or get_default_model(active_provider, task)
    # Strip provider prefix (e.g. "minimax/MiniMax-M1" -> "MiniMax-M1") for non-OpenRouter providers.
    # OpenRouter uses "provider/model" format for routing; native APIs expect just the model name.
    # Local servers keep it too: vLLM model ids are HuggingFace paths ("Qwen/Qwen3-8B").
    if active_provider not in ("openrouter", LOCAL_PROVIDER) and "/" in model:
        model = model.split("/", 1)[1]
    return model


def set_user_ai_config(identifier: str, provider: str, api_key: str, model: Optional[str] = None) -> None:
    """Store a temporary agent provider override for a user/session."""
    normalized_provider = normalize_provider(provider)
    _user_ai_configs[identifier] = {
        "provider": normalized_provider,
        "api_key": api_key,
        "model": (model or "").strip() or get_active_model(normalized_provider, "agent"),
    }


def get_user_ai_config(identifier: Optional[str]) -> Optional[dict[str, str]]:
    """Get a temporary agent provider override for a user/session."""
    if not identifier:
        return None
    return _user_ai_configs.get(identifier)


def get_provider_api_key(provider: Optional[str] = None, identifier: Optional[str] = None) -> str:
    """
    Get API key for the requested provider from user override or environment.

    Raises:
        ValueError: If the provider API key is not configured.
    """
    requested_provider = normalize_provider(provider or get_active_provider("agent"))

    if identifier:
        override = get_user_ai_config(identifier)
        if override and normalize_provider(override.get("provider")) == requested_provider and override.get("api_key"):
            return override["api_key"]

    env_name = get_provider_api_env(requested_provider)
    key = os.getenv(env_name, "").strip()
    if requested_provider == LOCAL_PROVIDER:
        # The key is optional for a local server; the base URL is what makes it configured.
        if not get_local_ai_base_url():
            raise ValueError("LOCAL_AI_BASE_URL not set in environment")
        return key or LOCAL_AI_PLACEHOLDER_KEY
    if not key:
        raise ValueError(f"{env_name} not set in environment")
    return key


def resolve_task(task: str, identifier: Optional[str] = None) -> dict[str, str]:
    """Resolve a task to its provider, model, and API key.

    Used by non-agent callers (vision/text) and anyone needing a complete config.

    Raises:
        ValueError: if no model is configured for the provider+task, or the key is missing.
    """
    task = _normalize_task(task)

    # Agent task honours per-user/session overrides; vision/text resolve from env only.
    override = get_user_ai_config(identifier) if task == "agent" else None
    provider = normalize_provider(override.get("provider") if override else get_active_provider(task))
    model = (override.get("model") if override else "") or get_active_model(provider, task)

    if override and override.get("api_key"):
        api_key = override["api_key"]
    else:
        api_key = get_provider_api_key(provider, identifier=identifier if task == "agent" else None)

    return {"provider": provider, "model": model, "api_key": api_key}


def is_task_available(task: str = "agent", identifier: Optional[str] = None) -> bool:
    """True if the task has a provider, model, and API key configured.

    Config-only check (no network): lets callers skip AI entirely on hosts that have
    no key/provider instead of attempting a call that would fail (or hang on retry).
    """
    try:
        resolve_task(task, identifier)
        return True
    except ValueError:
        return False


def get_active_ai_settings(identifier: Optional[str] = None) -> dict[str, "str | bool"]:
    """Resolve the agent provider, model, and API key status for status/health display."""
    override = get_user_ai_config(identifier)
    provider = normalize_provider(override.get("provider") if override else get_active_provider("agent"))
    model = (override.get("model") if override else "") or get_active_model(provider, "agent")
    env_name = get_provider_api_env(provider)

    try:
        api_key = get_provider_api_key(provider, identifier=identifier)
    except ValueError:
        api_key = ""

    if provider == LOCAL_PROVIDER:
        # No key to check: "configured" means the server address is set.
        env_name = "LOCAL_AI_BASE_URL"
        api_key_configured = bool(get_local_ai_base_url())
    else:
        api_key_configured = bool(api_key and len(api_key) > 10)

    return {
        "provider": provider,
        "model": model,
        "api_key_env": env_name,
        "api_key_configured": api_key_configured,
        "supports_prompt_caching": provider == "anthropic",
    }
