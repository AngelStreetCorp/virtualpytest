"""The frontend and the backend must know the same permissions (BUG-0787).

`update_role()` rejects every permission outside the backend vocabulary, and the
Roles page only offers what the frontend registry knows. When one side knew a
permission the other did not, the roles that held it could not be saved at all
(team:projects:create was in the frontend registry, not in the backend one), and
the two pages counted different numbers for the same role.

These tests pin the two lists to each other.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

FRONTEND_TYPES = REPO / "frontend" / "src" / "types" / "auth.ts"
BACKEND_ROUTE = REPO / "backend_server" / "src" / "routes" / "server_permissions_routes.py"


def _frontend_permissions() -> set:
    source = FRONTEND_TYPES.read_text(encoding="utf-8")
    block = re.search(r"export const ALL_PERMISSIONS: Permission\[\] = \[(.*?)\];", source, re.S)
    assert block, "ALL_PERMISSIONS not found in frontend/src/types/auth.ts"
    return set(re.findall(r"'([^']+)'", block.group(1)))


def _backend_permissions() -> set:
    source = BACKEND_ROUTE.read_text(encoding="utf-8")
    block = re.search(r"_ALL_PERMISSIONS = \[(.*?)\]", source, re.S)
    assert block, "_ALL_PERMISSIONS not found in server_permissions_routes.py"
    return set(re.findall(r"'([^']+)'", block.group(1)))


def test_the_two_vocabularies_are_the_same():
    front = _frontend_permissions()
    back = _backend_permissions()
    assert front - back == set(), f"the frontend knows permissions the backend rejects: {sorted(front - back)}"
    assert back - front == set(), f"the backend knows permissions the frontend cannot offer: {sorted(back - front)}"


def test_the_project_permissions_are_known():
    """POST /server/projects is gated by team:projects:create — the backend must know it."""
    assert 'team:projects:create' in _backend_permissions()
    assert 'team:projects:create' in _frontend_permissions()
