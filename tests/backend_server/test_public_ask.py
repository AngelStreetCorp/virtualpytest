"""
Tests for server_public_ask_routes.py (/server/public/ask)

Anonymous docs Q&A used by the marketing website. Only the guard rails are
exercised against a live server: the Origin allowlist, the input validation,
and the JWT bypass. The real answer path calls MiniMax and is skipped in CI.
"""
import pytest
import requests

SITE_ORIGIN = "https://virtualpytest.com"


def test_ask_refuses_missing_origin(base_url, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/public/ask",
        json={"question": "What is VirtualPyTest?"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 403
    assert response.json().get("error") == "Origin not allowed"


def test_ask_refuses_foreign_origin(base_url, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/public/ask",
        json={"question": "What is VirtualPyTest?"},
        headers={"Origin": "https://evil.example"},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 403


def test_ask_requires_question_without_jwt(base_url, verify_ssl, request_timeout):
    """Allowed origin, no auth header at all: must reach the route (400), not the JWT guard (401)."""
    response = requests.post(
        f"{base_url}/server/public/ask",
        json={},
        headers={"Origin": SITE_ORIGIN},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "Question required"


def test_ask_rejects_long_question(base_url, verify_ssl, request_timeout):
    response = requests.post(
        f"{base_url}/server/public/ask",
        json={"question": "x" * 501},
        headers={"Origin": SITE_ORIGIN},
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert "too long" in response.json().get("error", "")


@pytest.mark.manual  # calls MiniMax for real
def test_ask_answers_from_docs(base_url, verify_ssl):
    response = requests.post(
        f"{base_url}/server/public/ask",
        json={"question": "Does VirtualPyTest support Android TV?"},
        headers={"Origin": SITE_ORIGIN},
        timeout=90,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["answer"]
    assert isinstance(body["sources"], list)
    assert body["cached"] is False


@pytest.mark.manual  # calls MiniMax once for real
def test_ask_serves_similar_question_from_cache(base_url, verify_ssl):
    """Second, near-identical phrasing must be a cache hit: no LLM call, cached=true."""
    headers = {"Origin": SITE_ORIGIN}
    first = requests.post(f"{base_url}/server/public/ask", json={"question": "Is VirtualPyTest free to use?"},
                          headers=headers, timeout=90, verify=verify_ssl).json()
    second = requests.post(f"{base_url}/server/public/ask", json={"question": "is virtualpytest free to use??"},
                           headers=headers, timeout=30, verify=verify_ssl).json()
    assert first["success"] and second["success"]
    assert second["cached"] is True
    assert second["answer"] == first["answer"]
