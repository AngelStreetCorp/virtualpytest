"""
Server Agent Routes Tests

Covers the REST endpoints in backend_server/src/routes/server_agent_routes.py
(blueprint: /server/agent). SocketIO handlers (send_message, approve,
stop_generation, clear_session) registered by this module drive the actual
LLM chat loop and are not exercised here - they need a live socket
connection and would trigger real provider calls with no dry-run mode.
"""

import uuid

import requests


def test_agent_health(base_url, request_timeout, verify_ssl, api_headers):
    """Read-only: reports the active provider configuration, no side effects."""
    response = requests.get(
        f"{base_url}/server/agent/health",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    assert body.get("status") == "healthy"
    assert "api_key_configured" in body
    assert "provider" in body
    assert "model" in body
    assert "manager_initialized" in body


def test_agent_models(base_url, request_timeout, verify_ssl, api_headers):
    """Read-only: static provider/model/task matrix used by the AI settings UI."""
    response = requests.get(
        f"{base_url}/server/agent/models",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    assert isinstance(body.get("providers"), list)
    assert isinstance(body.get("tasks"), list)
    assert isinstance(body.get("provider_models"), dict)


def test_save_api_key_requires_api_key(base_url, request_timeout, verify_ssl, api_headers):
    """Missing api_key returns 400 before any credential validation or env
    file persistence happens - safe, no external provider call is made."""
    response = requests.post(
        f"{base_url}/server/agent/api-key",
        json={"provider": "anthropic", "model": "claude-3-5-sonnet"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("success") is False
    assert "API key required" in body.get("error", "")


class TestSessionLifecycle:
    """Sessions are in-memory (SessionManager keeps a plain dict), so
    create/list/get/delete are safe, repeatable, and self-cleaning."""

    def test_create_list_get_delete_session(self, base_url, request_timeout, verify_ssl, api_headers):
        create_response = requests.post(
            f"{base_url}/server/agent/sessions",
            headers=api_headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert create_response.status_code == 200
        create_body = create_response.json()
        assert create_body.get("success") is True
        session = create_body.get("session")
        assert isinstance(session, dict)
        session_id = session.get("id")
        assert session_id

        try:
            list_response = requests.get(
                f"{base_url}/server/agent/sessions",
                headers=api_headers,
                timeout=request_timeout,
                verify=verify_ssl,
            )
            assert list_response.status_code == 200
            list_body = list_response.json()
            assert list_body.get("success") is True
            assert isinstance(list_body.get("sessions"), list)

            get_response = requests.get(
                f"{base_url}/server/agent/sessions/{session_id}",
                headers=api_headers,
                timeout=request_timeout,
                verify=verify_ssl,
            )
            assert get_response.status_code == 200
            get_body = get_response.json()
            assert get_body.get("success") is True
            assert get_body.get("session", {}).get("id") == session_id
            assert "messages" in get_body
        finally:
            delete_response = requests.delete(
                f"{base_url}/server/agent/sessions/{session_id}",
                headers=api_headers,
                timeout=request_timeout,
                verify=verify_ssl,
            )
            assert delete_response.status_code == 200
            assert delete_response.json().get("success") is True

    def test_get_session_not_found(self, base_url, request_timeout, verify_ssl, api_headers):
        response = requests.get(
            f"{base_url}/server/agent/sessions/{uuid.uuid4()}",
            headers=api_headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert response.status_code == 404
        assert response.json().get("success") is False

    def test_delete_session_not_found_returns_false(self, base_url, request_timeout, verify_ssl, api_headers):
        """delete_session always returns 200; success reflects whether the
        session actually existed."""
        response = requests.delete(
            f"{base_url}/server/agent/sessions/{uuid.uuid4()}",
            headers=api_headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert response.status_code == 200
        assert response.json().get("success") is False

    def test_approve_action_session_not_found(self, base_url, request_timeout, verify_ssl, api_headers):
        response = requests.post(
            f"{base_url}/server/agent/sessions/{uuid.uuid4()}/approve",
            json={"approved": True},
            headers=api_headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert response.status_code == 404
        assert response.json().get("success") is False

    def test_approve_action_no_pending_approval(self, base_url, request_timeout, verify_ssl, api_headers):
        """A freshly created session has no pending_approval, so this returns
        400 before get_manager()/handle_approval() ever runs - no LLM call."""
        create_response = requests.post(
            f"{base_url}/server/agent/sessions",
            headers=api_headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert create_response.status_code == 200
        session_id = create_response.json()["session"]["id"]

        try:
            response = requests.post(
                f"{base_url}/server/agent/sessions/{session_id}/approve",
                json={"approved": True},
                headers=api_headers,
                timeout=request_timeout,
                verify=verify_ssl,
            )
            assert response.status_code == 400
            body = response.json()
            assert body.get("success") is False
            assert "No pending approval" in body.get("error", "")
        finally:
            requests.delete(
                f"{base_url}/server/agent/sessions/{session_id}",
                headers=api_headers,
                timeout=request_timeout,
                verify=verify_ssl,
            )

