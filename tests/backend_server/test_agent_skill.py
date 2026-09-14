"""
Agent Skill Routes Tests

Covers backend_server/src/routes/agent_skill_routes.py (blueprint:
/server/skills). Every endpoint here is a deterministic, local operation
over in-memory/YAML-backed skill definitions - no LLM calls, no device/host
dependency, no durable-data mutation - so all of them are safe to exercise
for real.
"""

import pytest
import requests


def test_reload_skills(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/skills/reload",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("count"), int)
    assert isinstance(body.get("skills"), list)
    assert body.get("count") == len(body["skills"])


def test_list_skills(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/skills",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("skills"), list)
    assert body.get("count") == len(body["skills"])
    assert isinstance(body.get("total"), int)


def test_list_skills_with_platform_filter(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/skills",
        params={"platform": "__nonexistent_platform__"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("skills") == []
    assert body.get("count") == 0


def test_get_skill_not_found(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/skills/__nonexistent_skill__",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert "not found" in response.json().get("error", "").lower()


def test_get_skill_by_name_from_list(base_url, request_timeout, verify_ssl, api_headers):
    """Discover a real skill name from the list endpoint, then fetch it directly."""
    list_response = requests.get(
        f"{base_url}/server/skills",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert list_response.status_code == 200
    skills = list_response.json().get("skills", [])
    if not skills:
        pytest.skip("No skills loaded on this server")
    skill_name = skills[0]["name"]

    response = requests.get(
        f"{base_url}/server/skills/{skill_name}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("name") == skill_name
    assert "triggers" in body
    assert "tools" in body


def test_test_skill_not_found(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/skills/test/__nonexistent_skill__",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert "not found" in response.json().get("error", "").lower()


def test_test_skill_by_name_from_list(base_url, request_timeout, verify_ssl, api_headers):
    """Structural validation of a real skill definition - pure local checks,
    no execution of the skill itself."""
    list_response = requests.get(
        f"{base_url}/server/skills",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert list_response.status_code == 200
    skills = list_response.json().get("skills", [])
    if not skills:
        pytest.skip("No skills loaded on this server")
    skill_name = skills[0]["name"]

    response = requests.post(
        f"{base_url}/server/skills/test/{skill_name}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("valid"), bool)
    assert "skill" in body  # 'skill' is either the name (invalid) or a summary dict (valid)


def test_match_skill_requires_message(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/skills/match",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "message is required"


def test_match_skill_no_match(base_url, request_timeout, verify_ssl, api_headers):
    """Keyword/trigger matching is pure local computation - no LLM involved."""
    response = requests.post(
        f"{base_url}/server/skills/match",
        json={
            "message": "asdkjhasdlkjh qwerty zxcvbn no real trigger words here",
            "available_skills": [],
        },
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert "matched" in body
