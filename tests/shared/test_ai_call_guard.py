"""Guard: no code calls an AI provider outside the logging client (BUG-0721).

Every model call must land in ai_calls. The shared AI package (shared/src/lib/ai/) does that through
router.record; anything else that imports a provider SDK, posts to a provider URL or runs ``claude -p`` must be
listed in ALLOWED below with how it is logged, and must contain that logging call. A new direct call fails this
test until it goes through gateway.complete / router.record, or reports itself with gateway.report_external_call.

Run: pytest tests/shared/test_ai_call_guard.py -q
"""
import os
import re

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SCAN_DIRS = ("backend_server", "backend_host", "shared", "scripts", "features", "test_scripts", "setup", "frontend/src")
EXTENSIONS = (".py", ".sh", ".ts", ".tsx", ".js", ".mjs")
SKIP_PARTS = ("/node_modules/", "/venv/", "/.venv/", "/__pycache__/", "/tests/")
LOGGING_PACKAGE = "shared/src/lib/ai/"

PROVIDER_CALL = re.compile(
    r"^\s*(import anthropic|from anthropic\b|import openai|from openai\b|from langchain_openai|from browser_use\.llm"
    r"|import google\.generativeai|from google import genai|import litellm|from litellm)"
    r"|https://(openrouter\.ai/api|api\.anthropic\.com|api\.minimax\.io|api\.openai\.com"
    r"|generativelanguage\.googleapis\.com)"
    r"|\bclaude\"?,?\s+\"?-p\b",
    re.M,
)

# file -> marker that proves the file logs its calls (None: the file makes no billed call, reason in the comment).
ALLOWED = {
    # browser-use: host-reach calls reported by an httpx hook, others go through the server passthrough.
    "backend_host/src/lib/utils/browseruse_utils.py": "report_direct_call",
    # OpenAI passthrough (router.record per hop); the OpenRouter credit / key reads are free.
    "backend_server/src/routes/server_ai_routing_routes.py": "router.record",
    # Scripts that must hit a provider themselves (pinned model, own request body): report every call.
    "scripts/localize/bench_models.py": "report_external_call",
    "scripts/coc_llm_player.py": "report_external_call",
    "scripts/lol_practice/llm_relay.py": "report_external_call",
    "scripts/promo/voiceover.py": "report_external_call",
    "shared/src/lib/game/leagueoflegends/game_review_ai.py": "report_external_call",
    # Headless Claude Code runs: the JSON result's modelUsage is reported.
    "scripts/promo/run_builder.sh": "ai_report_claude_cli",
    "scripts/pokemon_stall_review.py": "ai_report_claude_cli",
    "scripts/ai_report_claude_cli.py": "report_external_call",  # the reporter itself (its docstring names claude -p)
}


def _files():
    for top in SCAN_DIRS:
        for root, _dirs, names in os.walk(os.path.join(REPO, top)):
            rel_root = os.path.relpath(root, REPO).replace(os.sep, "/") + "/"
            if any(part in "/" + rel_root for part in SKIP_PARTS):
                continue
            for name in names:
                if name.endswith(EXTENSIONS):
                    yield rel_root + name


def _provider_callers():
    found = {}
    for rel in _files():
        if rel.startswith(LOGGING_PACKAGE):
            continue
        try:
            text = open(os.path.join(REPO, rel), encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        if PROVIDER_CALL.search(text):
            found[rel] = text
    return found


def test_no_unlogged_provider_call():
    callers = _provider_callers()
    unlisted = sorted(set(callers) - set(ALLOWED))
    assert not unlisted, (
        "These files call an AI provider outside the logging client; route them through gateway.complete or report "
        f"each call with gateway.report_external_call, then list them in ALLOWED: {unlisted}")
    missing = sorted(rel for rel, marker in ALLOWED.items()
                     if rel in callers and marker and marker not in callers[rel])
    assert not missing, f"Listed callers that no longer log their calls: {missing}"


def test_allowlist_has_no_stale_entries():
    callers = _provider_callers()
    stale = sorted(rel for rel in ALLOWED if rel not in callers)
    assert not stale, f"Remove from ALLOWED (no provider call left): {stale}"
