"""TASK-99 page layer: bundle build/deploy jobs (subprocess mocked), progress aggregation, timing summary."""
import io
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import bundle_jobs as bj  # noqa: E402
from backend_server.src.lib.platform_update import deployment  # noqa: E402
from backend_server.src.lib.platform_update.runs import PlatformUpdateError, RunStore  # noqa: E402

SAMPLE = os.path.join(_repo_root, "tests", "rollout", "data", "deploy_progress_sample.txt")
TOKEN = "glpat-SECRET-TOKEN-123"


class FakeProc:
    def __init__(self, output, rc=0):
        self.stdout = io.StringIO(output)
        self._rc = rc

    def wait(self):
        return self._rc


class FakePopen:
    """Records argv/env; plays back `output`."""
    calls = []

    def __init__(self, output, rc=0):
        self.output, self.rc = output, rc

    def __call__(self, argv, **kw):
        FakePopen.calls.append((argv, kw))
        return FakeProc(self.output, self.rc)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    FakePopen.calls = []
    bj._RUNNING.clear()
    monkeypatch.setattr(bj, "gitlab_credentials", lambda: ("http://gitlab.lan", TOKEN))
    monkeypatch.setattr(bj, "github_token", lambda: "")
    yield
    bj._RUNNING.clear()


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "pu")


def _ready_for(store, step):
    run = store.start("a@x")
    for i in range(step):
        store.begin_step(run["id"], i)
        store.finish_step(run["id"], i, True, "", {"backup": {"ok": True, "items": []}} if i == 1 else None)
    return run["id"]


def _build_output(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "vpt-platform-main-2026.10.13-63726.zip").write_text("zip")
    (out / "DELIVERY-x.md").write_text("# note")
    rec = {"name": "vpt-platform-main-2026.10.13-63726.zip", "path": str(out / "vpt-platform-main-2026.10.13-63726.zip"),
           "size": 3, "sha256": "ab" * 32, "delivery_note": "DELIVERY-x.md"}
    return "--- 1/3 core ---\ncloning\n\n" + json.dumps(rec, indent=2) + "\n", rec


# -- spec -> command ---------------------------------------------------------------------------
def test_spec_core_tag_and_overlays(tmp_path):
    up = tmp_path / ("a" * 32)
    up.mkdir()
    (up / "source.zip").write_text("z")
    spec = bj.parse_spec({"core": {"kind": "github", "tag": "main-2026.10.13-63726"},
                          "overlay": {"kind": "gitlab", "project": "g/o", "ref": "prod"}}, str(tmp_path))
    assert spec["core"] == "github:main-2026.10.13-63726" and spec["overlay"] == "gitlab:g/o@prod"
    spec = bj.parse_spec({"core": {"kind": "zip", "upload_id": "a" * 32}, "overlay": {"kind": "none"}}, str(tmp_path))
    assert spec["core"] == f"zip:{up / 'source.zip'}" and spec["overlay"] == "none"
    spec = bj.parse_spec({"core": {"kind": "github", "tag": "v1.2.3"},
                          "overlay": {"kind": "github", "url": "https://github.com/o/r", "ref": "prod"}}, str(tmp_path))
    assert spec["overlay"] == "github:https://github.com/o/r@prod"


@pytest.mark.parametrize("body", [
    {"core": {"kind": "github", "tag": "--evil"}},
    {"core": {"kind": "zip", "upload_id": "../../etc"}},
    {"core": {"kind": "zip", "upload_id": "b" * 32}},  # not on disk
    {"core": {"kind": "github", "tag": "v1.2.3"}, "overlay": {"kind": "github", "url": "https://tok@github.com/o/r", "ref": "p"}},
    {"core": {"kind": "github", "tag": "v1.2.3"}, "overlay": {"kind": "gitlab", "project": "noslash", "ref": "p"}},
    {"core": {"kind": "github", "tag": "v1.2.3"}, "format": "rar"},
])
def test_spec_rejects_bad_input(tmp_path, body):
    with pytest.raises(PlatformUpdateError):
        bj.parse_spec(body, str(tmp_path))


def test_token_goes_in_env_never_argv():
    spec = {"core": "github:v1.2.3", "overlay": "gitlab:g/o@prod", "format": "zip", "prev_pin": ""}
    argv, env, secrets = bj.build_command(spec, "/out")
    assert TOKEN not in " ".join(argv) and env["VPT_GITLAB_TOKEN"] == TOKEN and TOKEN in secrets
    assert "--gitlab-url" in argv and "http://gitlab.lan" in argv


def test_gitlab_overlay_needs_a_configured_instance(monkeypatch):
    monkeypatch.setattr(bj, "gitlab_credentials", lambda: ("", ""))
    with pytest.raises(PlatformUpdateError):
        bj.build_command({"core": "github:v1.2.3", "overlay": "gitlab:g/o@p", "format": "zip", "prev_pin": ""}, "/o")


# -- build job ---------------------------------------------------------------------------------
def test_build_job_streams_log_records_archive_and_masks_token(store, tmp_path):
    rid = _ready_for(store, 2)
    output, rec = _build_output(tmp_path)
    output = f"auth {TOKEN}\n" + output
    bj.start_build(store, rid, {"core": {"kind": "github", "tag": "main-2026.10.13-63726"},
                                "overlay": {"kind": "gitlab", "project": "g/o", "ref": "prod"}},
                   threaded=False, popen=FakePopen(output))
    run = store.get(rid)
    step = run["steps"][2]
    assert step["state"] == "done"
    assert step["data"]["bundle"]["sha256"] == "ab" * 32 and step["data"]["bundle"]["delivery_note"] == "DELIVERY-x.md"
    assert step["data"]["version"] == "main-2026.10.13-63726" and step["data"]["overlay"] == "g/o"
    log = "\n".join(store.log_lines(rid))
    assert "cloning" in log and "[step 2]" in log and TOKEN not in log and "auth ***" in log
    argv, kw = FakePopen.calls[0]
    assert TOKEN not in " ".join(argv) and kw["env"]["VPT_GITLAB_TOKEN"] == TOKEN
    assert not bj.is_running("build")  # the slot is released


def test_build_failure_marks_step_failed_with_reason(store):
    rid = _ready_for(store, 2)
    bj.start_build(store, rid, {"core": {"kind": "github", "tag": "v1.2.3"}, "overlay": {"kind": "none"}},
                   threaded=False, popen=FakePopen("cloning\nFAILED: tag not found\n", rc=1))
    step = store.get(rid)["steps"][2]
    assert step["state"] == "failed" and "tag not found" in step["detail"]
    assert not bj.is_running("build")


def test_one_build_at_a_time(store):
    rid = _ready_for(store, 2)
    bj._RUNNING["build"] = "other-run"
    with pytest.raises(bj.JobBusy) as ei:
        bj.start_build(store, rid, {"core": {"kind": "github", "tag": "v1.2.3"}, "overlay": {"kind": "none"}},
                       threaded=False, popen=FakePopen(""))
    assert ei.value.code == 409
    assert store.get(rid)["steps"][2]["state"] == "waiting"


def test_interrupted_job_is_closed_as_failed(store):
    rid = _ready_for(store, 2)
    store.begin_step(rid, 2)
    store.set_data(rid, 2, {"job": {"state": "running"}})
    run = bj.recover_interrupted(store, store.get(rid))
    assert run["steps"][2]["state"] == "failed" and "interrupted" in run["steps"][2]["detail"]


# -- deploy job + progress aggregation ----------------------------------------------------------
def _with_built_bundle(store, tmp_path):
    rid = _ready_for(store, 2)
    store.begin_step(rid, 2)
    arch = tmp_path / "b.zip"
    arch.write_text("z")
    store.finish_step(rid, 2, True, "b", {"bundle": {"name": "b.zip", "path": str(arch), "sha256": "cd" * 32}, "version": "v1"})
    return rid


def test_deploy_needs_a_built_bundle(store):
    rid = _ready_for(store, 2)
    with pytest.raises(PlatformUpdateError):
        bj.start_deploy(store, rid, {}, threaded=False, popen=FakePopen(""))


def test_deploy_script_missing_says_where_it_must_run(store, tmp_path, monkeypatch):
    rid = _with_built_bundle(store, tmp_path)
    monkeypatch.setenv("VPT_DEPLOY_BUNDLE_SCRIPT", str(tmp_path / "nope.sh"))
    with pytest.raises(PlatformUpdateError) as ei:
        bj.start_deploy(store, rid, {}, threaded=False, popen=FakePopen(""))
    assert "deploy node" in str(ei.value) and "VPT_LEASE_AGENT" in str(ei.value)
    assert store.get(rid)["steps"][3]["state"] == "waiting"


def test_deploy_job_passes_lease_agent_parses_progress_and_saves_timings(store, tmp_path, monkeypatch):
    script = tmp_path / "deploy_bundle.sh"
    script.write_text("#!/bin/bash\n")
    monkeypatch.setenv("VPT_DEPLOY_BUNDLE_SCRIPT", str(script))
    monkeypatch.delenv("VPT_LEASE_AGENT", raising=False)
    rid = _with_built_bundle(store, tmp_path)
    sample = open(SAMPLE, encoding="utf-8").read()
    argv = bj.start_deploy(store, rid, {"update_args": ["--server", "--rm-rf"]}, threaded=False, popen=FakePopen(sample))
    assert argv[:2] == ["bash", str(script)] and "--server" in argv and "--rm-rf" not in argv
    assert FakePopen.calls[0][1]["env"]["VPT_LEASE_AGENT"] == "platform-update"
    step = store.get(rid)["steps"][3]
    timings = step["data"]["timings"]
    assert timings["hosts"] and all("phases" in h and "log" not in h for h in timings["hosts"])
    assert step["state"] in ("done", "failed")
    assert not bj.is_running("deploy")


def test_deploy_failure_from_exit_code(store, tmp_path, monkeypatch):
    script = tmp_path / "d.sh"
    script.write_text("x")
    monkeypatch.setenv("VPT_DEPLOY_BUNDLE_SCRIPT", str(script))
    rid = _with_built_bundle(store, tmp_path)
    bj.start_deploy(store, rid, {}, threaded=False, popen=FakePopen("sha256 mismatch\n", rc=1))
    assert store.get(rid)["steps"][3]["state"] == "failed"


def _ev(host, phase, state, ts, role="host", detail=""):
    return "2026-10-14 08:00:00 [step 3] VPT_PROGRESS " + json.dumps(
        {"host": host, "role": role, "phase": phase, "state": state, "ts": ts, "detail": detail})


def test_view_per_host_cards_counts_and_host_log_lines():
    lines = [
        "[step 3] ==> [proxmox -> pi1] rsync push",
        _ev("pi1", "rsync", "start", "2026-10-14T08:00:00Z"),
        _ev("pi1", "rsync", "ok", "2026-10-14T08:00:12Z"),
        "[step 3] ==> [pi2] sudo systemctl restart x",
        _ev("pi1", "install", "start", "2026-10-14T08:00:12Z"),
        _ev("pi1", "install", "failed", "2026-10-14T08:00:20Z", detail="pip failed"),
        _ev("srv", "rsync", "start", "2026-10-14T08:00:00Z", role="server"),
    ]
    view = deployment.build_view(lines)
    cards = {c["host"]: c for c in view["hosts"]}
    assert set(cards) == {"pi1", "srv"} and view["state"] == "failed"
    assert cards["pi1"]["phases"]["rsync"]["duration_s"] == 12 and cards["pi1"]["phases"]["install"]["duration_s"] == 8
    assert cards["pi1"]["error"] == "pip failed" and cards["srv"]["state"] == "running"
    assert cards["pi1"]["log"] == ["[step 3] ==> [proxmox -> pi1] rsync push"]  # pi2 line excluded, no raw events
    assert view["phases_total"] == 8 and view["phases_done"] == 2  # pi1: rsync ok + install failed


def test_view_none_without_progress_lines():
    assert deployment.build_view(["[step 3] plain log", "nothing"]) is None
    assert deployment.timing_summary(None)["hosts"] == []


def test_timing_summary_has_durations_and_no_log_lines():
    view = deployment.build_view([_ev("pi1", "rsync", "start", "2026-10-14T08:00:00Z"),
                                  _ev("pi1", "rsync", "ok", "2026-10-14T08:00:05Z")])
    summary = deployment.timing_summary(view)
    host = summary["hosts"][0]
    assert host["phases"]["rsync"] == {"state": "ok", "duration_s": 5.0} and "log" not in host
