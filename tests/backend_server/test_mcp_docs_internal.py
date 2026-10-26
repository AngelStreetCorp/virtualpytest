"""MCP docs tools must never serve internal-only docs (gitignored or on internal-paths.txt)."""
import pytest

from backend_server.src.mcp.tools.docs_tools import DocsTools, _is_internal_path
from backend_server.src.mcp.tool_definitions.auto_generator import generate_from_class

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("path", [
    "agent/infra/LOAD_AVERAGE.md",          # gitignored dir, still tracked
    "agent/TROUBLESHOOT.md",                # gitignored file
    "agent/release/ANONYMIZATION.md",       # internal-paths prefix
    "tasks/TASK-01-x.md",
    "security/snyk.json",                   # internal-paths wildcard
    "Agent/Infra/LOAD_AVERAGE.md",          # case-insensitive filesystems
])
def test_internal_paths_blocked(path):
    assert _is_internal_path(path)
    assert DocsTools().read_doc({"path": path})["success"] is False


def test_public_and_agent_docs_not_blocked():
    assert not _is_internal_path("INDEX.md")
    assert not _is_internal_path("agent/navigation/MAP.md")
    assert DocsTools().read_doc({"path": "INDEX.md"})["success"] is True


def test_list_and_search_skip_internal():
    sections = DocsTools().list_docs({})["sections"]
    listed = [p for v in sections.values() for p in v]
    assert listed and not [p for p in listed if _is_internal_path(p)]
    hits = DocsTools().search_docs({"query": "the", "max_results": 500})["results"]
    assert not [h for h in hits if _is_internal_path(h["path"])]


def test_schemas_expose_parameters():
    defs = {d["name"]: d["inputSchema"] for d in generate_from_class(DocsTools)}
    assert defs["read_doc"]["required"] == ["path"] and "path" in defs["read_doc"]["properties"]
    assert "section" in defs["list_docs"]["properties"]
    assert defs["search_docs"]["required"] == ["query"] and "section" in defs["search_docs"]["properties"]
