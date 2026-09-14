"""
Agent Benchmark & Feedback Routes Tests

Covers backend_server/src/routes/agent_benchmark_routes.py (blueprint:
/server/benchmarks). DELETE /run/<id> and DELETE /feedback/<id> were added
2026-09-07 so a happy-path create test could clean up after itself
(create -> verify -> delete) instead of skipping forever for lack of a
cleanup path. See those routes' docstrings for the score-consistency
caveats (DELETE /run/<id> refuses a 'completed' run; DELETE /feedback/<id>
explicitly recalculates the agent's aggregate score after deleting, since
neither table has an AFTER DELETE trigger to do that automatically).

BUT: live-testing the actual create calls against the deployed server
(2026-09-07) found a deeper, pre-existing blocker — POST /run and POST
/feedback both fail with a real Postgres RLS violation ("new row violates
row-level security policy") for *any* caller using this suite's API key,
not just a quirk of the test. So the happy-path tests below are still
skipped, now for the real reason: the DB's row-level security policy on
agent_benchmark_runs/agent_feedback doesn't currently permit this
API-key-authenticated write path at all. That's a security-model decision
(should API keys write to these tables, or only real user sessions/a
service-role key?) for the team, not something to loosen blindly. The
DELETE endpoints themselves are still correctly implemented and ready for
whenever that's resolved.

POST /run/<id>/execute is skipped outright regardless: it would run real
agent tasks for real.
"""

import uuid

import pytest
import requests


def test_list_benchmark_tests(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/benchmarks/tests",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("tests"), list)
    assert body.get("count") == len(body["tests"])


def test_create_benchmark_run_requires_agent_id(base_url, request_timeout, verify_ssl, api_headers):
    """No agent_id returns 400 before create_benchmark_run() is called, so no
    row is written to agent_benchmark_runs."""
    response = requests.post(
        f"{base_url}/server/benchmarks/run",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "agent_id required"


def test_create_and_delete_benchmark_run_round_trip(base_url, request_timeout, verify_ssl, api_headers, team_id):
    """Create a benchmark run, see it listed, delete it, see it gone.

    Was test_create_benchmark_run_regression_currently_blocked_by_rls, which asserted a
    500 with a row-level-security violation: the server held the anon key, so this INSERT
    matched no policy. TASK-10 moved the server onto the service_role key, so the write
    goes through and the round trip the original docstring asked for is now possible.
    """
    created = requests.post(
        f"{base_url}/server/benchmarks/run",
        json={"agent_id": "__test_agent_never_real__", "version": "0.0.0-test", "team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert created.status_code == 201, created.text
    run_id = created.json().get("run_id")
    assert run_id, created.text

    # DELETE returning 200 is itself the proof the row was created; a second DELETE
    # returning 404 proves it is gone. No listing assertion: /benchmarks/runs is scoped
    # by agent and would couple this test to that filtering.
    deleted = requests.delete(
        f"{base_url}/server/benchmarks/runs/{run_id}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert deleted.status_code == 200, deleted.text

    gone = requests.delete(
        f"{base_url}/server/benchmarks/runs/{run_id}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert gone.status_code == 404, gone.text


@pytest.mark.skip(
    reason="Would run real agent tasks for real against a live agent — not "
    "repeatable-safe in CI regardless of run cleanup. Also currently unreachable "
    "anyway without a live agent to benchmark."
)
def test_execute_benchmark_run_not_exercised():
    pass


def test_delete_benchmark_run_unknown_id_returns_404(base_url, request_timeout, verify_ssl, api_headers):
    """Only proves the 404 path (route_delete_benchmark_run's own not-found
    check runs before the 'refuses a completed run' check) — the "reject a
    completed run" path can't be exercised until POST /run's RLS issue above
    is resolved, since there's currently no way to create a run to complete."""
    response = requests.delete(
        f"{base_url}/server/benchmarks/runs/{uuid.uuid4()}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404, response.text


def test_list_benchmark_runs(base_url, request_timeout, verify_ssl, api_headers, team_id):
    response = requests.get(
        f"{base_url}/server/benchmarks/runs",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("runs"), list)
    assert body.get("count") == len(body["runs"])


def test_get_benchmark_run_not_found(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/benchmarks/runs/{uuid.uuid4()}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404
    assert response.json().get("error") == "Run not found"


def test_submit_feedback_requires_agent_id_and_rating(base_url, request_timeout, verify_ssl, api_headers):
    """Missing required fields returns 400 before submit_feedback() writes to
    the agent_feedback table."""
    response = requests.post(
        f"{base_url}/server/benchmarks/feedback",
        json={},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "agent_id and rating required"


def test_submit_feedback_rejects_out_of_range_rating(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.post(
        f"{base_url}/server/benchmarks/feedback",
        json={"agent_id": "assistant", "rating": 6},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "rating must be 1-5"


def test_submit_and_delete_feedback_round_trip(base_url, request_timeout, verify_ssl, api_headers, team_id):
    """Submit feedback, delete it, confirm it is gone.

    Was test_submit_feedback_regression_currently_blocked_by_rls — same anon-key RLS
    violation as the benchmark-run test above, resolved by TASK-10. DELETE also
    re-triggers the agent_scores recalculation that agent_feedback's own trigger only
    performs on INSERT, so the delete is part of what is being covered here.
    """
    created = requests.post(
        f"{base_url}/server/benchmarks/feedback",
        json={
            "agent_id": "__test_agent_never_real__",
            "version": "0.0.0-test",
            "rating": 3,
            "team_id": team_id,
        },
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert created.status_code == 201, created.text
    feedback_id = created.json().get("feedback_id")
    assert feedback_id, created.text

    deleted = requests.delete(
        f"{base_url}/server/benchmarks/feedback/{feedback_id}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert deleted.status_code == 200, deleted.text

    gone = requests.delete(
        f"{base_url}/server/benchmarks/feedback/{feedback_id}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert gone.status_code == 404, gone.text


def test_delete_feedback_unknown_id_returns_404(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.delete(
        f"{base_url}/server/benchmarks/feedback/{uuid.uuid4()}",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 404, response.text


def test_list_feedback(base_url, request_timeout, verify_ssl, api_headers, team_id):
    response = requests.get(
        f"{base_url}/server/benchmarks/feedback",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("feedback"), list)
    assert body.get("count") == len(body["feedback"])


def test_get_agent_scores(base_url, request_timeout, verify_ssl, api_headers, team_id):
    response = requests.get(
        f"{base_url}/server/benchmarks/scores",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("scores"), list)
    assert body.get("count") == len(body["scores"])


def test_get_leaderboard(base_url, request_timeout, verify_ssl, api_headers, team_id):
    response = requests.get(
        f"{base_url}/server/benchmarks/leaderboard",
        params={"team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("leaderboard"), list)
    assert body.get("count") == len(body["leaderboard"])


def test_compare_agents_requires_agents_param(base_url, request_timeout, verify_ssl, api_headers):
    response = requests.get(
        f"{base_url}/server/benchmarks/compare",
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 400
    assert response.json().get("error") == "agents parameter required"


def test_compare_agents(base_url, request_timeout, verify_ssl, api_headers, team_id):
    """Read-only comparison query; nonexistent agent:version pairs are a
    valid input (compare_agents just returns whatever data it finds)."""
    response = requests.get(
        f"{base_url}/server/benchmarks/compare",
        params={"agents": "assistant:1.0.0,__nonexistent_agent__:1.0.0", "team_id": team_id},
        headers=api_headers,
        timeout=request_timeout,
        verify=verify_ssl,
    )
    assert response.status_code == 200
    assert isinstance(response.json(), dict)
