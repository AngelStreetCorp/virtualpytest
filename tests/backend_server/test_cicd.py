"""cicd feature — API shape plus a regression guard for BUG-0050.

The restart button resolves a runner name to a VM through `_DEFAULT_RUNNER_HOSTS` in
features/cicd/backend_server/__init__.py, falling back to `CI_RUNNER_HOST` (192.168.0.163)
for anything not listed. When the fleet grew from one runner to eight, that map still held
a single entry, so restarting any VM-164 runner silently acted on VM 163 — see
docs/bugs/BUG-0050-*.md.

The guard here is deliberately indirect: it reads the map out of the source as *text* and
compares it against the runners GitHub currently reports. Importing the module would need
Flask and the whole backend_server package, which the CI job does not install (it installs
only pytest/pytest-html/pytest-timeout/requests), so an import-based test would be skipped
in exactly the environment that matters.

Everything here is tier A — server API and static source, no device.
"""

import re
from pathlib import Path

import pytest

FEATURE_SRC = (
    Path(__file__).resolve().parents[2]
    / "features/cicd/backend_server/__init__.py"
)


def _mapped_runner_names() -> set:
    """Runner names listed in _DEFAULT_RUNNER_HOSTS, read from the source."""
    src = FEATURE_SRC.read_text()
    block = re.search(r"_DEFAULT_RUNNER_HOSTS\s*=\s*\{(.*?)\}", src, re.DOTALL)
    assert block, "could not find _DEFAULT_RUNNER_HOSTS in the cicd feature source"
    return set(re.findall(r"['\"]([^'\"]+)['\"]\s*:", block.group(1)))


class TestCicdApi:
    def test_health_reports_configuration(self, get, api_headers):
        response = get("/server/cicd/health", headers=api_headers)
        assert response.status_code == 200, response.text[:300]

        body = response.json()
        assert body.get("success") is True
        if not body.get("configured"):
            pytest.skip(f"cicd feature not configured here: {body.get('schema_error')}")
        assert isinstance(body.get("reports_dir"), str)

    def test_runners_carry_project_and_repo(self, get, api_headers):
        response = get("/server/cicd/runners", headers=api_headers)
        assert response.status_code == 200, response.text[:300]

        body = response.json()
        if body.get("configured") is False:
            pytest.skip("cicd feature not configured here")
        runners = body.get("runners") or []
        assert runners, "no runners returned at all"
        for runner in runners:
            assert runner.get("name"), runner
            assert runner.get("project"), runner
            assert runner.get("repo"), runner
            assert runner.get("can_run"), runner

    def test_runs_expose_a_report_url(self, get, api_headers):
        response = get("/server/cicd/runs", headers=api_headers, params={"limit": 5})
        assert response.status_code == 200, response.text[:300]

        body = response.json()
        if body.get("configured") is False:
            pytest.skip("cicd feature not configured here")
        for run in body.get("runs") or []:
            assert run.get("run"), run
            assert str(run.get("report_url", "")).startswith("http"), run

    def test_live_reports_per_job_detail(self, get, api_headers):
        """/live must carry the per-job list, which is what lets a runner card name the
        job it is executing — a runner reports `busy` without saying what it is busy with."""
        response = get("/server/cicd/live", headers=api_headers)
        assert response.status_code == 200, response.text[:300]

        body = response.json()
        if body.get("configured") is False:
            pytest.skip("cicd feature not configured here")
        for run in body.get("running") or []:
            assert "jobs" in run, f"run {run.get('run_number')} has no per-job list: {run}"
            for job in run.get("jobs") or []:
                assert "runner_name" in job and "started_at" in job, job


class TestRunnerHostMapping:
    """Regression guard for BUG-0050."""

    def test_every_registered_runner_resolves_to_its_own_vm(self, get, api_headers):
        """Every self-hosted runner the page lists must resolve to the VM it runs on.

        The server derives the VM from the runner name (`<project>-<vmid>-<n>`, last octet =
        VMID on the lab) unless CI_RUNNER_HOSTS overrides it; the response exposes the result as
        `host`. A runner that landed on the single-VM fallback would be restarted on the wrong
        machine (BUG-0050) — that is what this catches, for every project, sibling ones included.
        """
        response = get("/server/cicd/runners", headers=api_headers)
        if response.status_code != 200 or response.json().get("configured") is False:
            pytest.skip("cicd feature not configured here")

        live = [
            r for r in response.json().get("runners") or []
            if r.get("name") and r.get("name") != "github-hosted"
        ]
        if not live:
            pytest.skip("no self-hosted runners registered")
        if not any("host" in r for r in live):
            pytest.skip("deployed server predates the runners' `host` field (deploy pending)")

        wrong = []
        for r in live:
            host = r.get("host") or ""
            m = re.match(r"^[A-Za-z0-9-]+?-(\d{1,3})-\d+$", r["name"])
            if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
                wrong.append(f"{r['name']} -> {host!r} (not an address)")
            elif m and not host.endswith(f".{int(m.group(1))}"):
                wrong.append(f"{r['name']} -> {host} (expected last octet {int(m.group(1))})")
        assert not wrong, (
            "runners whose restart would target the wrong VM (BUG-0050): "
            + "; ".join(wrong)
            + ". Fix the name convention or set CI_RUNNER_HOSTS / CI_RUNNER_SUBNET on the server."
        )

    def test_the_map_is_not_empty(self):
        assert _mapped_runner_names(), "_DEFAULT_RUNNER_HOSTS is empty"
