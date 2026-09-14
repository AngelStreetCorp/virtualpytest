"""
Integrations Routes Tests

Covers backend_server/src/routes/server_integrations_routes.py:
  GET    /server/integrations/jira/instances              — list configured JIRA instances (sanitized)
  POST   /server/integrations/jira/instances               — create/update a JIRA instance config
  DELETE /server/integrations/jira/instances/<instance_id> — delete a JIRA instance config
  GET    /server/integrations/jira/<instance_id>/tickets   — list tickets (calls real JIRA API)
  GET    /server/integrations/jira/<instance_id>/stats     — ticket stats (calls real JIRA API)
  POST   /server/integrations/jira/<instance_id>/test      — test JIRA connection (calls real JIRA API)
  GET    /server/integrations/slack/config                 — read Slack config (sanitized)
  POST   /server/integrations/slack/config                 — update Slack config
  POST   /server/integrations/slack/test                   — test Slack connection (calls real Slack API)
  GET    /server/integrations/slack/status                 — read Slack sync status
  POST   /server/integrations/slack/send-test              — send a real message to the configured Slack channel
  POST   /server/integrations/slack/events                 — Slack Events API webhook (public, unauthenticated)

Environment variables needed (on top of the base conftest ones):
  AUTH_TEST_JWT — Supabase JWT for any authenticated user. These routes carry
                  no role/permission decorator in the source, so they are
                  reachable by any authenticated role once the global
                  /server/* JWT guard (ENFORCE_FRONTEND_JWT) is satisfied.
                  /server/integrations/slack/events is the one explicit
                  exception: backend_server/src/app.py's
                  configure_global_frontend_auth_guard() lists it as a public
                  webhook prefix, reachable with no auth at all.

Notes / deliberate scope limits:
  - get_jira_tickets/get_jira_stats/test_jira_connection call call_jira_api(),
    which hits a real https://<domain>/rest/api/3 JIRA instance — skipped
    entirely except for the "instance not found" 404 branch, which returns
    before any outbound call is made.
  - test_slack_connection and send_test_message call the real slack-sdk
    WebClient against whatever bot token is configured (falling back to the
    server's saved config when no token is supplied), which is both an
    external call and, for send-test, a visible message in a real Slack
    channel — skipped entirely.
  - update_slack_config persists to a local JSON file with no delete
    endpoint, so the round-trip test below reads the config first and
    restores it afterwards (matching the save/restore pattern used for
    other config endpoints in this backfill).
"""

import uuid

import pytest
import requests


def _is_auth_enforced(base_url: str, verify_ssl: bool) -> bool:
    try:
        resp = requests.get(
            f"{base_url}/server/users",
            headers={"Content-Type": "application/json"},
            timeout=5,
            verify=verify_ssl,
        )
        return resp.status_code in (401, 403)
    except Exception:
        return False


@pytest.fixture(scope="session")
def auth_enforced(base_url: str, verify_ssl: bool) -> bool:
    return _is_auth_enforced(base_url, verify_ssl)


def jwt_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def _skip_if_no_jwt(token: str) -> None:
    if not token:
        pytest.skip("AUTH_TEST_JWT not configured — set AUTH_TEST_JWT env var")


# ---------------------------------------------------------------------------
# JIRA instances
# ---------------------------------------------------------------------------


class TestJiraInstances:
    def test_get_jira_instances_without_jwt(
        self, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        resp = requests.get(
            f"{base_url}/server/integrations/jira/instances",
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if auth_enforced:
            assert resp.status_code == 401, resp.text
        else:
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data.get("success") is True
            assert isinstance(data.get("instances"), list)

    def test_get_jira_instances_with_jwt(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/integrations/jira/instances",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("success") is True
        for instance in data.get("instances", []):
            # Sanitized: API tokens must never be returned.
            assert "apiToken" not in instance

    def test_create_jira_instance_requires_fields(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/integrations/jira/instances",
            json={"name": "Incomplete Instance"},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json().get("success") is False

    def test_create_then_delete_jira_instance(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        headers = jwt_headers(auth_jwt)
        instance_id = f"__smoke_test_jira_{uuid.uuid4().hex[:8]}__"

        create_resp = requests.post(
            f"{base_url}/server/integrations/jira/instances",
            json={
                "id": instance_id,
                "name": "Smoke Test Instance",
                "domain": "smoke-test.atlassian.net",
                "email": "smoke-test@example.com",
                "apiToken": "not-a-real-token",
                "projectKey": "SMOKE",
            },
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()
        assert created.get("success") is True
        assert created.get("instance", {}).get("id") == instance_id
        assert "apiToken" not in created.get("instance", {})

        del_resp = requests.delete(
            f"{base_url}/server/integrations/jira/instances/{instance_id}",
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json().get("success") is True

    def test_delete_nonexistent_jira_instance_is_success(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        """Delete filters the instance list by id with no existence check, so
        deleting an id that was never configured is still a success."""
        _skip_if_no_jwt(auth_jwt)
        resp = requests.delete(
            f"{base_url}/server/integrations/jira/instances/__does_not_exist__",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json().get("success") is True


class TestJiraInstanceNotFound:
    """Only the local-lookup 404 branch, which returns before any call to
    the real JIRA API."""

    def test_get_jira_tickets_unknown_instance(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/integrations/jira/__does_not_exist__/tickets",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json().get("success") is False

    def test_get_jira_stats_unknown_instance(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/integrations/jira/__does_not_exist__/stats",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json().get("success") is False

    def test_test_jira_connection_unknown_instance(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.post(
            f"{base_url}/server/integrations/jira/__does_not_exist__/test",
            json={},
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json().get("success") is False


@pytest.mark.skip(
    reason=(
        "get_jira_tickets/get_jira_stats call the real JIRA REST API "
        "(https://<domain>/rest/api/3) for any configured instance — no "
        "safe way to exercise the success path without a live third-party "
        "JIRA account."
    )
)
class TestJiraLiveApiCalls:
    def test_get_tickets_and_stats(self):
        ...


# ---------------------------------------------------------------------------
# Slack config / status
# ---------------------------------------------------------------------------


class TestSlackConfig:
    def test_get_slack_config_without_jwt(
        self, base_url, verify_ssl, request_timeout, auth_enforced
    ):
        resp = requests.get(
            f"{base_url}/server/integrations/slack/config",
            timeout=request_timeout,
            verify=verify_ssl,
        )
        if auth_enforced:
            assert resp.status_code == 401, resp.text
        else:
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data.get("success") is True
            assert "has_token" in data.get("config", {})

    def test_get_slack_config_with_jwt(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/integrations/slack/config",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("success") is True
        config = data.get("config", {})
        # Sanitized: the raw bot token must never be returned.
        assert "bot_token" not in config
        assert "has_token" in config

    def test_get_slack_status(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        _skip_if_no_jwt(auth_jwt)
        resp = requests.get(
            f"{base_url}/server/integrations/slack/status",
            headers=jwt_headers(auth_jwt),
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("success") is True
        status = data.get("status", {})
        assert "enabled" in status
        assert "configured" in status

    def test_update_slack_config_round_trip(
        self, base_url, verify_ssl, request_timeout, auth_jwt
    ):
        """Toggle sync_tool_calls off-then-back-on (or vice versa) and
        restore the original value, without ever touching bot_token."""
        _skip_if_no_jwt(auth_jwt)
        headers = jwt_headers(auth_jwt)

        original_resp = requests.get(
            f"{base_url}/server/integrations/slack/config",
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert original_resp.status_code == 200, original_resp.text
        original_sync = original_resp.json().get("config", {}).get("sync_tool_calls", False)

        toggle_resp = requests.post(
            f"{base_url}/server/integrations/slack/config",
            json={"sync_tool_calls": not original_sync},
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert toggle_resp.status_code == 200, toggle_resp.text
        assert toggle_resp.json().get("success") is True

        # Restore original value.
        restore_resp = requests.post(
            f"{base_url}/server/integrations/slack/config",
            json={"sync_tool_calls": original_sync},
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert restore_resp.status_code == 200, restore_resp.text


@pytest.mark.skip(
    reason=(
        "test_slack_connection and send_test_message call the real "
        "slack-sdk WebClient — either an external API call or (for "
        "send-test) a visible message posted to a real Slack channel. Not "
        "safe to run unconditionally in CI."
    )
)
class TestSlackLiveApiCalls:
    def test_slack_connection_and_send_test(self):
        ...


# ---------------------------------------------------------------------------
# Slack Events webhook — public, local-only echo for url_verification
# ---------------------------------------------------------------------------


class TestSlackEventsWebhook:
    def test_url_verification_challenge_is_echoed(
        self, base_url, verify_ssl, request_timeout
    ):
        """This endpoint is explicitly listed as a public prefix in
        configure_global_frontend_auth_guard(), so no auth header is sent."""
        challenge_token = "smoke-test-challenge-token"
        resp = requests.post(
            f"{base_url}/server/integrations/slack/events",
            json={"type": "url_verification", "challenge": challenge_token},
            headers={"Content-Type": "application/json"},
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json().get("challenge") == challenge_token

    def test_bot_message_event_is_ignored(
        self, base_url, verify_ssl, request_timeout
    ):
        resp = requests.post(
            f"{base_url}/server/integrations/slack/events",
            json={
                "type": "event_callback",
                "event": {"type": "message", "bot_id": "B123", "text": "hi"},
            },
            headers={"Content-Type": "application/json"},
            timeout=request_timeout,
            verify=verify_ssl,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json().get("ok") is True
