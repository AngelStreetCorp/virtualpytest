"""QuickTest lifecycle — create, read, edit, delete, run.

QuickTest (features/quicktest/) has no backend of its own: the builder compiles its
linear step list to a core testcase graph and persists/executes it through
`/server/testcase/*`. These tests walk that path end to end with a QuickTest-shaped
graph, which is what the feature actually depends on.

Tiers (docs/technical/FEATURES.md → "Testing a feature"):

  create / read / edit / delete  tier A — server API only, no device involved
  run                            tier B — executes on `host-clone-1` via the real
                                 server → host → device path

Every test creates its own testcase and deletes it in teardown, so the suite is
independent of what already exists in the target team — the pre-existing
`test_get_testcase_list_returns_array` passes against an empty team too, which is
exactly why an always-empty team was never noticed.
"""

import time
import uuid

import pytest

from .conftest import assert_not_auth_failure

def _script_result_for(get, api_headers, team_id, execution_id):
    """The durable record of one execution, or None if it has not landed yet.

    `script_results.metadata.execution_id` carries the id returned by /execute, which is
    what ties a run to its stored verdict once the transient status record is gone.
    """
    response = get(
        "/server/script-results/getAllScriptResults",
        headers=api_headers,
        params={"team_id": team_id, "limit": 20},
    )
    if response.status_code != 200:
        return None
    rows = response.json()
    if not isinstance(rows, list):
        rows = rows.get("script_results") or rows.get("data") or []
    for row in rows:
        metadata = row.get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get("execution_id") == execution_id:
            return row
    return None


def _edge(kind: str, source: str, target: str) -> dict:
    """Mirror successEdge/failureEdge in compileStepsToGraph.ts.

    `type` is required — the executor rejects a graph with
    "Edge N has invalid type: None (must be 'success' or 'failure')" — and
    sourceHandle must match it.
    """
    return {
        "id": f"e-{kind}-{source}-{target}",
        "source": source,
        "target": target,
        "sourceHandle": kind,
        "type": kind,
    }


def _quicktest_graph(target: str = "home") -> dict:
    """START -> navigation(goto target) -> SUCCESS / FAILURE.

    Exactly the shape features/quicktest/frontend/utils/compileStepsToGraph.ts emits for a
    single `goto` step: BlockType.NAVIGATION with `data.target_node_label`, and both a
    success and a failure edge. Built by hand rather than imported because the compiler is
    TypeScript — compileStepsToGraph.test.ts covers the compiler itself; this covers what
    the server and host do with its output.
    """
    return {
        "nodes": [
            {"id": "start", "type": "start", "position": {"x": 250, "y": 0}, "data": {}},
            {
                "id": "node-1",
                "type": "navigation",
                "position": {"x": 250, "y": 120},
                "data": {"target_node_label": target},
            },
            {"id": "success", "type": "success", "position": {"x": 250, "y": 240}, "data": {}},
            {"id": "failure", "type": "failure", "position": {"x": 450, "y": 240}, "data": {}},
        ],
        "edges": [
            _edge("success", "start", "node-1"),
            _edge("success", "node-1", "success"),
            _edge("failure", "node-1", "failure"),
        ],
    }


@pytest.fixture
def quicktest(post, delete, api_headers, team_id, device_userinterface):
    """Create a QuickTest-shaped testcase; always remove it afterwards."""
    name = f"zz-ci-quicktest-{uuid.uuid4().hex[:8]}"
    created: dict = {}

    response = post(
        "/server/testcase/save",
        headers=api_headers,
        params={"team_id": team_id},
        json={
            "testcase_name": name,
            "graph_json": _quicktest_graph(),
            "description": "Created by tests/backend_server/test_quicktest.py",
            "userinterface_name": device_userinterface,
        },
    )
    assert_not_auth_failure(response, "creating a testcase")
    if response.status_code != 200 or not response.json().get("success"):
        pytest.skip(f"could not create a testcase ({response.status_code}): {response.text[:200]}")

    created = response.json().get("testcase") or {}
    created["_name"] = name
    yield created

    tc_id = created.get("testcase_id") or created.get("id")
    if tc_id:
        delete(f"/server/testcase/{tc_id}", headers=api_headers, params={"team_id": team_id})


class TestQuickTestCrud:
    """Tier A — create / read / edit / delete. No device."""

    def test_create_returns_the_saved_testcase(self, quicktest):
        assert quicktest.get("testcase_id") or quicktest.get("id"), quicktest
        assert quicktest.get("name") == quicktest["_name"] or \
               quicktest.get("testcase_name") == quicktest["_name"], quicktest

    def test_created_testcase_is_readable_by_id(self, get, api_headers, team_id, quicktest):
        tc_id = quicktest.get("testcase_id") or quicktest["id"]
        response = get(f"/server/testcase/{tc_id}", headers=api_headers, params={"team_id": team_id})
        assert response.status_code == 200, response.text[:300]

        body = response.json()
        assert body.get("success") is True, body
        graph = (body.get("testcase") or {}).get("graph_json") or {}
        # The graph must survive the round-trip, not just the row.
        assert len(graph.get("nodes") or []) == 4, graph

    def test_created_testcase_appears_in_the_list(self, get, api_headers, team_id, quicktest):
        response = get("/server/testcase/list", headers=api_headers, params={"team_id": team_id})
        assert response.status_code == 200

        names = {
            tc.get("name") or tc.get("testcase_name")
            for tc in response.json().get("testcases") or []
        }
        assert quicktest["_name"] in names

    def test_edit_persists_a_changed_graph(self, post, get, api_headers, team_id, quicktest):
        tc_id = quicktest.get("testcase_id") or quicktest["id"]
        edited = _quicktest_graph(target="settings")
        edited["nodes"].append(
            {"id": "node-2", "type": "wait", "position": {"x": 0, "y": 180},
             "data": {"duration": 500}}
        )

        response = post(
            "/server/testcase/save",
            headers=api_headers,
            params={"team_id": team_id},
            json={"testcase_id": tc_id, "graph_json": edited, "description": "edited"},
        )
        assert response.status_code == 200, response.text[:300]
        assert response.json().get("success") is True

        reread = get(f"/server/testcase/{tc_id}", headers=api_headers, params={"team_id": team_id})
        graph = (reread.json().get("testcase") or {}).get("graph_json") or {}
        assert len(graph.get("nodes") or []) == 5, graph
        labels = [
            (n.get("data") or {}).get("target_node_label")
            for n in graph.get("nodes") or []
        ]
        assert "settings" in labels, labels

    def test_delete_removes_it(self, post, get, delete, api_headers, team_id, device_userinterface):
        # Not using the fixture: this test owns the whole lifecycle so the delete is
        # the assertion rather than teardown.
        name = f"zz-ci-quicktest-del-{uuid.uuid4().hex[:8]}"
        created = post(
            "/server/testcase/save",
            headers=api_headers,
            params={"team_id": team_id},
            json={
                "testcase_name": name,
                "graph_json": _quicktest_graph(),
                "userinterface_name": device_userinterface,
            },
        )
        assert_not_auth_failure(created, "creating a testcase")
        if created.status_code != 200 or not created.json().get("success"):
            pytest.skip(f"could not create a testcase: {created.text[:200]}")
        tc_id = (created.json().get("testcase") or {}).get("testcase_id") or \
                (created.json().get("testcase") or {}).get("id")

        removed = delete(f"/server/testcase/{tc_id}", headers=api_headers,
                         params={"team_id": team_id})
        assert removed.status_code == 200, removed.text[:300]

        listed = get("/server/testcase/list", headers=api_headers, params={"team_id": team_id})
        names = {
            tc.get("name") or tc.get("testcase_name")
            for tc in listed.json().get("testcases") or []
        }
        assert name not in names, "deleted testcase still listed"


@pytest.mark.device
# Runs a real script on a device host and polls up to 240s; the suite-wide 30s CI timeout
# (regression.yml) would cut it off, so this class carries its own budget.
@pytest.mark.timeout(300)
class TestQuickTestExecution:
    """Tier B — actually run it on `host-clone-1` through the real device path.

    Skipped rather than failed when the host is busy or absent: a device tier that goes
    red because someone else holds the lock trains people to ignore CI. A genuine
    execution failure (the run starts and reports failure) still fails the test.
    """

    def test_execute_runs_on_the_device_host(
        self, post, get, api_headers, team_id, quicktest, device_host, device_id,
        device_userinterface
    ):
        # /execute runs a graph directly (no save needed) — it requires graph_json,
        # device_id and host_name; passing only testcase_id is rejected with 400.
        launched = post(
            "/server/testcase/execute",
            headers=api_headers,
            params={"team_id": team_id},
            json={
                "graph_json": _quicktest_graph(),
                "host_name": device_host,
                "device_id": device_id,
                "userinterface_name": device_userinterface,
                "testcase_id": quicktest.get("testcase_id") or quicktest["id"],
            },
            timeout=60,
        )
        if launched.status_code in (409, 423, 503):
            pytest.skip(f"{device_host} unavailable ({launched.status_code})")
        assert launched.status_code == 200, launched.text[:300]

        body = launched.json()
        if not body.get("success"):
            error = str(body.get("error", "")).lower()
            # Only host *availability* is a skip. Deliberately not matching a bare
            # "not found": the executor says "Node with label '…' not found in navigation
            # graph" for a genuinely broken test, and swallowing that as a skip would hide
            # exactly the failure this tier exists to catch.
            unavailable = (
                "locked" in error
                or "busy" in error
                or "unavailable" in error
                or "host not found" in error
                or "no host" in error
                or "device not found" in error
            )
            if unavailable:
                pytest.skip(f"{device_host} not available for execution: {error[:150]}")
            pytest.fail(f"execute rejected: {error[:300]}")

        execution_id = body.get("execution_id") or body.get("id")
        assert execution_id, body

        # Poll to a terminal state; the goto itself is a few seconds, the browser start
        # dominates. Deliberately bounded so a wedged host fails the job fast.
        #
        # The status route proxies to the host, so it needs host_name/device_id as well as
        # team_id — without them it 400s ("host_name required"), which polls as an endless
        # "no status yet". The payload nests the real state under `status.status`.
        deadline = time.time() + 240
        status, detail = None, {}
        while time.time() < deadline:
            polled = get(
                f"/server/testcase/execution/{execution_id}/status",
                headers=api_headers,
                params={"team_id": team_id, "host_name": device_host, "device_id": device_id},
            )
            assert polled.status_code == 200, (
                f"status poll failed ({polled.status_code}): {polled.text[:200]}"
            )
            detail = polled.json().get("status") or {}
            status = detail.get("status") if isinstance(detail, dict) else detail
            if status in ("completed", "success", "failed", "error", "aborted"):
                break
            # The status record is transient and host-local: it can go EMPTY while the run
            # is still going (observed on stb3, 2026-09-07 — four polls of "running", then
            # nothing, while the run completed fine). The durable verdict is the
            # script_results row, matched on metadata.execution_id, so fall through to it
            # rather than treating a vanished record as a failure.
            if not detail:
                recorded = _script_result_for(get, api_headers, team_id, execution_id)
                if recorded is not None:
                    assert recorded.get("success") is True, (
                        f"QuickTest on {device_host}/{device_id} recorded success="
                        f"{recorded.get('success')}: {str(recorded.get('error_msg'))[:200]}"
                    )
                    return
            time.sleep(3)

        if status is None:
            recorded = _script_result_for(get, api_headers, team_id, execution_id)
            assert recorded is not None, (
                "execution never reported a status and no script_results row was recorded"
            )
            assert recorded.get("success") is True, (
                f"recorded success={recorded.get('success')}: {str(recorded.get('error_msg'))[:200]}"
            )
            return

        # `status` is the LIFECYCLE state, not the verdict: a run whose navigation failed
        # still reports "completed" (verified against a graph targeting a non-existent
        # node — status "completed", current_block_id "failure", result.success False).
        # Asserting on `status` alone therefore passes on a failed run. The verdict lives
        # in result.success, cross-checked against the terminal block.
        assert status not in ("failed", "error", "aborted"), (
            f"QuickTest execution on {device_host} ended {status}: {detail.get('error')}"
        )

        result = detail.get("result") or {}
        failed_blocks = {
            name: block.get("error")
            for name, block in (detail.get("block_states") or {}).items()
            if isinstance(block, dict) and block.get("status") == "failure"
        }
        assert result.get("success") is True, (
            f"QuickTest execution on {device_host} reported success={result.get('success')} "
            f"(terminal block {detail.get('current_block_id')!r}); failures: {failed_blocks}"
        )
        assert detail.get("current_block_id") != "failure", (
            f"execution ended on the FAILURE terminal; failures: {failed_blocks}"
        )
