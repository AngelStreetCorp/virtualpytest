"""
Coverage for server_ai_userinterface_routes.py (`/server/ai_userinterface/*`):
the DB-backed agent knowledge base (screens, transitions, verifications,
tasks, quirks, hardware, fingerprints) with append-only history.

Read endpoints are exercised end-to-end (safe, no side effects). Write
endpoints (create/update/revert/append/supersede) only have a delete-free
audit trail — there is no corresponding delete route, only `supersede`, which
itself becomes a permanent history row — so, per policy, this suite verifies
their required-field validation (safe, no DB writes) rather than performing
real writes against a shared team's knowledge base.
"""

import uuid

import requests


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------


def test_list_requires_team_id(base_url, api_headers, request_timeout, verify_ssl):
    resp = requests.get(
        f"{base_url}/server/ai_userinterface/list",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_list_returns_rows(get, api_headers, team_id):
    resp = get(
        "/server/ai_userinterface/list",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert isinstance(body.get("rows"), list)
    assert body.get("count") == len(body.get("rows"))


def test_get_unknown_ui_id_returns_404(get, api_headers, team_id):
    ui_id = str(uuid.uuid4())
    resp = get(
        f"/server/ai_userinterface/get/{ui_id}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json().get("success") is False


def test_resolve_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/resolve",
        json={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_resolve_unmatched_fingerprint_returns_near_misses(
    base_url, api_headers, team_id, request_timeout, verify_ssl
):
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/resolve",
        json={
            "team_id": team_id,
            "fingerprint_type": "dom_signature",
            "value": f"__nonexistent_fingerprint_{uuid.uuid4().hex}__",
        },
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("matched") is False
    assert body.get("parent") is None
    assert isinstance(body.get("near_misses"), list)


def test_history_requires_team_id(base_url, api_headers, request_timeout, verify_ssl):
    ui_id = str(uuid.uuid4())
    resp = requests.get(
        f"{base_url}/server/ai_userinterface/history/{ui_id}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_history_unknown_id_returns_empty_list(get, api_headers, team_id):
    ui_id = str(uuid.uuid4())
    resp = get(
        f"/server/ai_userinterface/history/{ui_id}",
        headers=api_headers,
        params={"team_id": team_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("rows") == []
    assert body.get("count") == 0


# ---------------------------------------------------------------------------
# PARENT CRUD (validation only — see module docstring)
# ---------------------------------------------------------------------------


def test_create_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/create",
        json={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_update_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    ui_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/update/{ui_id}",
        json={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_revert_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    ui_id = str(uuid.uuid4())
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/revert/{ui_id}",
        json={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


# ---------------------------------------------------------------------------
# APPEND (sub-rows) — validation only
# ---------------------------------------------------------------------------


def test_add_screen_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/screen/add",
        json={"team_id": team_id, "actor": "pytest"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_add_transition_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/transition/add",
        json={"team_id": team_id, "actor": "pytest"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_add_verification_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/verification/add",
        json={"team_id": team_id, "actor": "pytest"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_add_task_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/task/add",
        json={"team_id": team_id, "actor": "pytest"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_add_quirk_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/quirk/add",
        json={"team_id": team_id, "actor": "pytest"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_add_hardware_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/hardware/add",
        json={"team_id": team_id, "actor": "pytest"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


def test_add_fingerprint_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/fingerprint/add",
        json={"team_id": team_id, "actor": "pytest"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False


# ---------------------------------------------------------------------------
# SOFT-DELETE — validation only
# ---------------------------------------------------------------------------


def test_supersede_requires_fields(base_url, api_headers, team_id, request_timeout, verify_ssl):
    resp = requests.post(
        f"{base_url}/server/ai_userinterface/supersede",
        json={"team_id": team_id, "actor": "pytest"},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json().get("success") is False
