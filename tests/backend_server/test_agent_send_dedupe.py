"""BUG-0401: the SPA's ack watchdog re-sends a message with the same client_msg_id; the server runs it once."""

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend_server" / "src"))


def test_same_client_msg_id_is_processed_once_per_session(monkeypatch):
    from routes import server_agent_routes as routes
    monkeypatch.setattr(routes, "_RECENT_CLIENT_MSGS", {})
    assert routes._seen_client_msg("s1", "m1") is False
    assert routes._seen_client_msg("s1", "m1") is True
    assert routes._seen_client_msg("s2", "m1") is False  # other session
    assert routes._seen_client_msg("s1", "m2") is False


def test_ids_expire_after_the_ttl(monkeypatch):
    import time
    from routes import server_agent_routes as routes
    monkeypatch.setattr(routes, "_RECENT_CLIENT_MSGS", {("s1", "m1"): time.time() - routes._RECENT_CLIENT_MSG_TTL_S - 1})
    assert routes._seen_client_msg("s1", "m1") is False
