"""scripts/ai_routing_import_env.py reproduces the pre-TASK-30 env behaviour as routes.

In-memory fake DB + secrets store; no network.

Run: pytest tests/shared/test_ai_routing_import_env.py -v
"""
import importlib.util
import os
import sys
import uuid

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.ai import secrets_store  # noqa: E402
from shared.src.lib.database import ai_routing_db  # noqa: E402

_spec = importlib.util.spec_from_file_location("ai_routing_import_env",
                                               os.path.join(_repo_root, "scripts", "ai_routing_import_env.py"))
importer_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(importer_mod)


class FakeDB:
    """Seeded like the migration: anthropic + openrouter endpoints, 3 profiles, 3 root routes."""

    def __init__(self):
        self.tables = {"ai_endpoints": [], "ai_profiles": [], "ai_routes": []}
        a = self.create_row("ai_endpoints", {"name": "anthropic", "preset": "anthropic", "secret_name": "anthropic"})
        o = self.create_row("ai_endpoints", {"name": "openrouter", "preset": "openrouter", "secret_name": "openrouter"})
        sonnet = self.create_row("ai_profiles", {"name": "claude-sonnet-4", "endpoint_id": a["id"],
                                                 "model": "claude-sonnet-4-20250514"})
        qwen = self.create_row("ai_profiles", {"name": "qwen3-vl-8b", "endpoint_id": o["id"],
                                               "model": "qwen/qwen3-vl-8b-instruct"})
        mini = self.create_row("ai_profiles", {"name": "gpt-4.1-mini", "endpoint_id": o["id"],
                                               "model": "openai/gpt-4.1-mini"})
        for usage, prof in (("agent", sonnet), ("vision", qwen), ("text", mini)):
            self.create_row("ai_routes", {"team_id": None, "usage_key": usage, "profile_id": prof["id"]})

    def create_row(self, table, data):
        row = {"id": uuid.uuid4().hex, **data}
        self.tables[table].append(row)
        return row

    def update_row(self, table, row_id, data, team_id=None):
        for row in self.tables[table]:
            if row["id"] == row_id:
                row.update(data)
                return row
        return None

    def list_endpoints(self):
        return list(self.tables["ai_endpoints"])

    def list_profiles(self):
        return list(self.tables["ai_profiles"])

    def list_routes(self, team_id):
        return [r for r in self.tables["ai_routes"] if r.get("team_id") == team_id]

    def route_model(self, usage):
        route = next(r for r in self.tables["ai_routes"] if r["usage_key"] == usage)
        profile = next(p for p in self.tables["ai_profiles"] if p["id"] == route["profile_id"])
        endpoint = next(e for e in self.tables["ai_endpoints"] if e["id"] == profile["endpoint_id"])
        return endpoint["name"], profile["model"]


@pytest.fixture
def run(monkeypatch):
    def _run(env, host_env=None):
        db = FakeDB()
        secrets = {}
        for name in ("create_row", "update_row", "list_endpoints", "list_profiles", "list_routes"):
            monkeypatch.setattr(ai_routing_db, name, getattr(db, name))
        monkeypatch.setattr(secrets_store, "set_secret", lambda n, v: secrets.__setitem__(n, v))
        importer_mod.Importer({**(host_env or {}), **env}, host_env or {}, dry_run=False).run()
        return db, secrets
    return _run


def test_no_ai_env_keeps_seeded_defaults(run):
    db, secrets = run({})
    assert db.route_model("agent") == ("anthropic", "claude-sonnet-4-20250514")
    assert db.route_model("vision") == ("openrouter", "qwen/qwen3-vl-8b-instruct")
    assert db.route_model("text") == ("openrouter", "openai/gpt-4.1-mini")
    assert secrets == {}


def test_primary_provider_and_overrides(run):
    db, secrets = run({"AI_PROVIDER": "minimax", "MINIMAX_API_KEY": "mm", "OPENROUTER_API_KEY": "or",
                       "AI_TEXT_MODEL": "MiniMax-M2.5"})
    # minimax cannot serve vision -> the old per-task default (openrouter qwen) stays.
    assert db.route_model("agent") == ("minimax", "MiniMax-M2.7-highspeed")
    assert db.route_model("vision") == ("openrouter", "qwen/qwen3-vl-8b-instruct")
    assert db.route_model("text") == ("minimax", "MiniMax-M2.5")
    assert db.route_model("public.ask") == ("minimax", "MiniMax-M2.7-highspeed")
    assert db.route_model("vision.screenshot") == ("minimax-vlm", "minimax-vlm")
    assert db.route_model("agent.mcp_prompt") == ("openrouter", "google/gemini-2.5-pro")
    assert db.route_model("agent.browser") == ("openrouter", "o4-mini")
    assert secrets["minimax"] == "mm" and secrets["minimax-vlm"] == "mm" and secrets["openrouter"] == "or"


def test_host_env_decides_vision_and_text(run):
    db, _ = run({"AI_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk"},
                host_env={"AI_VISION_PROVIDER": "local", "LOCAL_AI_BASE_URL": "http://10.0.0.5:1234/v1/",
                          "LOCAL_AI_MODEL": "qwen/qwen3-vl-8b", "LOCAL_AI_TIMEOUT": "90"})
    assert db.route_model("agent") == ("anthropic", "claude-sonnet-4-20250514")
    assert db.route_model("vision") == ("local", "qwen/qwen3-vl-8b")
    assert db.route_model("text") == ("anthropic", "claude-sonnet-4-20250514")
    local = next(e for e in db.tables["ai_endpoints"] if e["name"] == "local")
    assert local["base_url"] == "http://10.0.0.5:1234/v1" and local["timeout_s"] == 90


def test_dom_and_sherlock_overrides(run):
    db, _ = run({"OPENAI_API_KEY": "sk", "DOM_EFFORT": "high", "ANALYZER_OPENROUTER_MODEL": "x-ai/grok-3-mini",
                 "OPENROUTER_API_KEY": "or"})
    assert db.route_model("vision.dom") == ("openai", "gpt-5.5")
    dom = next(p for p in db.tables["ai_profiles"] if p["model"] == "gpt-5.5")
    assert dom["extra"]["reasoning_effort"] == "high"
    assert dom["extra"]["max_tokens_param"] == "max_completion_tokens"
    assert db.route_model("analyzer.sherlock") == ("openrouter", "x-ai/grok-3-mini")


def test_local_without_model_refuses(run):
    with pytest.raises(SystemExit):
        run({"AI_PROVIDER": "local", "LOCAL_AI_BASE_URL": "http://gpu:8000/v1"})


def test_rerun_is_idempotent(run, monkeypatch):
    db, _ = run({"AI_PROVIDER": "minimax", "MINIMAX_API_KEY": "mm"})
    counts = {t: len(rows) for t, rows in db.tables.items()}
    importer_mod.Importer({"AI_PROVIDER": "minimax", "MINIMAX_API_KEY": "mm"}, {}, dry_run=False).run()
    assert {t: len(rows) for t, rows in db.tables.items()} == counts
