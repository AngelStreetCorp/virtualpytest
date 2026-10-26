"""
VPT_PROGRESS events (TASK-99 G9): the parser over a recorded run, and the real update_core.sh run
against stub ssh/rsync/sleep binaries on PATH (nothing leaves this machine, no host is touched).
"""
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
UC = PROJECT_ROOT / "setup" / "proxmox" / "node" / "update_core.sh"
SAMPLE = Path(__file__).parent / "data" / "deploy_progress_sample.txt"

pytestmark = pytest.mark.unit


@pytest.fixture
def dp():
    import setup.proxmox.node.lib.deploy_progress as m
    return m


# ─── the parser over a recorded run ────────────────────────────────────────────

class TestParserOnRecordedRun:
    """tests/rollout/data/deploy_progress_sample.txt is a real stubbed run of update_core.sh
    (server, frontend, two hosts of which h2 is unreachable, a docker stack, a Windows host),
    with its timestamps spread so the durations are asserted exactly."""

    @pytest.fixture
    def run(self, dp):
        return dp.parse(SAMPLE.read_text())

    def by(self, run, role, host):
        return next(h for h in run["hosts"] if h["role"] == role and h["host"] == host)

    def test_one_card_per_role_and_host_in_order_of_appearance(self, run):
        assert [(h["role"], h["host"]) for h in run["hosts"]] == [
            ("server", "srv"), ("frontend", "fe"), ("host", "h1"), ("host", "h2"),
            ("docker", "dk"), ("windows", "win1")]

    def test_phase_states_and_durations(self, run):
        srv = self.by(run, "server", "srv")["phases"]
        assert {k: v["state"] for k, v in srv.items()} == {"rsync": "ok", "restart": "ok", "health": "ok"}
        assert srv["rsync"]["duration_s"] == 12 and srv["restart"]["duration_s"] == 3
        assert srv["health"]["duration_s"] == 9
        fe = self.by(run, "frontend", "fe")["phases"]
        assert fe["install"]["state"] == "ok" and fe["install"]["duration_s"] == 95
        assert fe["install"]["detail"] == "frontend build"

    def test_a_failed_host_is_failed_and_keeps_its_error_line(self, run):
        h2 = self.by(run, "host", "h2")
        assert h2["state"] == "failed"
        assert h2["phases"]["rsync"]["state"] == "failed" and h2["phases"]["rsync"]["duration_s"] == 4
        assert h2["phases"]["rsync"]["detail"] == "rsync push failed"
        assert "restart" not in h2["phases"]

    def test_skipped_phases_have_no_duration(self, run):
        win = self.by(run, "windows", "win1")
        assert win["phases"]["install"]["state"] == "skipped" and win["phases"]["install"]["duration_s"] is None
        assert win["state"] == "ok"
        dk = self.by(run, "docker", "dk")
        assert dk["phases"]["restart"]["state"] == "skipped"

    def test_host_totals_and_run_totals(self, run):
        h1 = self.by(run, "host", "h1")
        assert h1["state"] == "ok" and h1["started"] == "2026-10-14T08:02:20Z"
        assert h1["duration_s"] == 31
        assert run["state"] == "failed"
        assert run["started"] == "2026-10-14T08:00:00Z"
        assert run["ended"] == "2026-10-14T08:03:10Z" and run["duration_s"] == 190
        assert run["events"] == len(re.findall(r"^VPT_PROGRESS ", SAMPLE.read_text(), re.M))

    def test_human_log_lines_are_ignored(self, run, dp):
        assert run["ignored"] == 0
        assert dp.parse_line("==> [h1] rsync push") is None


class TestParserEdges:
    def line(self, **kw):
        ev = {"host": "h", "role": "host", "phase": "rsync", "state": "start",
              "ts": "2026-10-14T08:00:00Z", "detail": ""}
        ev.update(kw)
        return "VPT_PROGRESS " + json.dumps(ev)

    def test_a_prefix_before_the_marker_is_fine(self, dp):
        assert dp.parse_line("[08:00:01] [stdout] " + self.line())["host"] == "h"

    def test_malformed_events_are_counted_not_fatal(self, dp):
        run = dp.parse([self.line(), "VPT_PROGRESS {not json", self.line(phase="bogus"),
                        self.line(state="exploded"), "VPT_PROGRESS []"])
        assert run["events"] == 1 and run["ignored"] == 4

    def test_a_phase_that_never_ended_is_running(self, dp):
        run = dp.parse([self.line()])
        assert run["hosts"][0]["state"] == "running" and run["state"] == "running"
        assert run["hosts"][0]["phases"]["rsync"]["duration_s"] is None and run["ended"] is None

    def test_a_restarted_phase_restarts_its_clock(self, dp):
        run = dp.parse([self.line(), self.line(state="failed", ts="2026-10-14T08:00:05Z"),
                        self.line(ts="2026-10-14T08:01:00Z"), self.line(state="ok", ts="2026-10-14T08:01:02Z")])
        ph = run["hosts"][0]["phases"]["rsync"]
        assert ph["state"] == "ok" and ph["duration_s"] == 2

    def test_no_events_is_pending(self, dp):
        assert dp.parse("just text\n")["state"] == "pending"

    def test_the_stale_code_note_is_parsed_and_never_fails_a_host(self, dp):
        """The deploy says when a service was left running the code from before the deploy.

        The note has to survive the parser: a phase the parser does not know is counted as
        ignored and dropped, so the event would be invisible exactly when it matters (BUG-0893).
        It is a NOTE, not a phase of the deploy, so it never turns a healthy host card into a
        failure and it carries no duration.
        """
        run = dp.parse([self.line(state="ok", ts="2026-10-14T08:00:05Z"),
                        self.line(phase="stale-code", state="skipped",
                                  ts="2026-10-14T08:00:06Z", detail="vpt-monitor-img: running the code from before this deploy")])
        host = run["hosts"][0]
        note = host["phases"]["stale-code"]
        assert note["state"] == "skipped"
        assert note["duration_s"] is None
        assert "vpt-monitor-img" in note["detail"]
        assert host["state"] == "ok", "a stale-code note must not turn a healthy host into a failure"
        assert run["ignored"] == 0

    def test_a_role_defaults_to_host(self, dp):
        ev = json.loads(self.line()[len("VPT_PROGRESS "):])
        del ev["role"]
        assert dp.parse_line("VPT_PROGRESS " + json.dumps(ev))["role"] == "host"


# ─── the real update_core.sh against stubs ─────────────────────────────────────

SSH_STUB = r'''#!/usr/bin/env bash
# last argument is the remote command; the target is the one before it
cmd="${*: -1}"
case "$cmd" in
  *"--property=MainPID"*) echo $((RANDOM + 100)) ;;
  *"--property=ActiveState"*) printf 'ActiveState=active\nSubState=running\nResult=success\nExecMainStatus=0\n' ;;
  *"is-active"*) exit 1 ;;
  *"ensure_dist.sh"*) [[ "$STUB_FAIL_BUILD" == 1 ]] && { echo build failed >&2; exit 1; } ; exit 0 ;;
  *"docker ps"*|"bash -s") cat >/dev/null; echo "build started in the background" ;;
esac
exit 0
'''
RSYNC_STUB = r'''#!/usr/bin/env bash
for a in "$@"; do [[ "$a" == *"$STUB_FAIL_RSYNC"* && -n "$STUB_FAIL_RSYNC" ]] && exit 23; done
exit 0
'''


BASH_MAJOR = int(subprocess.run(["bash", "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True).stdout.strip() or 0)


# update_core.sh claims a lease before it deploys and FAILS CLOSED when there is no registry client
# (rc 127 -> exit 5). These tests are about the progress events, not the lease, so ~/bin/vpt-lease in
# the throwaway HOME grants every claim. Without it the tests only passed on a box that had one.
LEASE_STUB = r'''#!/usr/bin/env bash
case "$1" in
  validate) [[ -n "$STUB_EVENT_LOG" ]] && echo "$*" >> "$STUB_EVENT_LOG"; exit "${STUB_VALIDATE_RC:-3}" ;;
  release) [[ -n "$STUB_EVENT_LOG" ]] && echo "$*" >> "$STUB_EVENT_LOG" ;;
  deploy) [[ "$2" == last ]] || exit 0
          [[ -n "$STUB_LAST_RC" && "$STUB_LAST_RC" != 0 ]] && exit "$STUB_LAST_RC"
          [[ -n "$STUB_LAST_JSON" ]] && cat "$STUB_LAST_JSON" ;;
  claim) [[ -n "$STUB_LEASE_LOG" ]] && echo "$*" >> "$STUB_LEASE_LOG"
         case " $* " in *" --help "*) echo "usage: vpt-lease claim ... [--wait]";; *) echo "lease-stub-1";; esac ;;
esac
exit 0
'''


def _git_repo(tmp_path):
    """A real checkout (not a bundle) with origin/main = c2 and a side branch `newer` one commit ahead. Returns (repo, c1, c2, c3)."""
    def git(cwd, *a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.hooksPath=/dev/null", *a],
                              cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    shas = []
    for d in ("backend_host", "backend_server", "shared", "features", "scripts", "setup"):   # the code-id probes need tracked files
        (origin / d).mkdir()
        (origin / d / "f.txt").write_text("x\n")
    (origin / "requirements.txt").write_text("\n")
    for i in (1, 2):
        (origin / "VERSION.txt").write_text(f"current:main-{i}\n")
        git(origin, "add", "."); git(origin, "commit", "-q", "-m", f"c{i}")
        shas.append(git(origin, "rev-parse", "HEAD"))
    git(origin, "checkout", "-q", "-b", "newer")
    (origin / "VERSION.txt").write_text("current:main-3\n")
    git(origin, "add", "VERSION.txt"); git(origin, "commit", "-q", "-m", "c3")
    shas.append(git(origin, "rev-parse", "HEAD"))
    git(origin, "checkout", "-q", "main")
    repo = tmp_path / "bundle" / "virtualpytest"
    repo.parent.mkdir(parents=True, exist_ok=True)
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    return repo, shas[0], shas[1], shas[2]


def _registry(tmp_path, entries):
    """entries: {target: commit} for env node1-vpt, all status done (a value may be (commit, status))."""
    envs = {}
    for k, v in entries.items():
        c, st = v if isinstance(v, tuple) else (v, "done")
        envs[k] = {"ref": "main", "commit": c, "version": "v", "agent": "x", "status": st}
    f = tmp_path / "last.json"
    f.write_text(json.dumps({"now": 1, "envs": {"node1-vpt": envs}}))
    return str(f)


def _run_update_core(tmp_path, args, git_repo=None, **env_extra):
    bins = tmp_path / "bin"
    bins.mkdir(exist_ok=True)
    for name, body in (("ssh", SSH_STUB), ("rsync", RSYNC_STUB), ("sleep", "#!/bin/sh\nexit 0\n")):
        f = bins / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    repo = tmp_path / "bundle" / "virtualpytest"
    if git_repo is None:
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "BUNDLE_MANIFEST.txt").write_text("bundle: t\n")
        (repo / "VERSION.txt").write_text("current:main-1\n")
    uc = tmp_path / "uc.sh"
    text = UC.read_text()
    for key, val in (("SERVER_IP", "srv"), ("FRONTEND_IP", "fe"), ("HOST_IPS", "h1,h2"),
                     ("HOST_WINDOWS_IPS", "win1"), ("DOCKER_IPS", "dk"), ("RUNNER_IPS", "r1")):
        text = re.sub(rf'^{key}=.*$', f'{key}="{val}"', text, count=1, flags=re.M)
    if BASH_MAJOR < 4:       # macOS ships bash 3.2: no associative arrays. Only this test copy is patched.
        text = text.replace("declare -A AUX_RESTART_FAIL=()", "AUX_RESTART_FAIL=()")
    uc.write_text(text)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "bin").mkdir(exist_ok=True)
    lease = home / "bin" / "vpt-lease"
    lease.write_text(LEASE_STUB)
    lease.chmod(lease.stat().st_mode | stat.S_IEXEC)
    env = {"PATH": f"{bins}:{os.environ['PATH']}", "HOME": str(home), "REPO_DIR": str(repo),
           "SSH_KEY": str(tmp_path / "nokey"), **env_extra}
    return subprocess.run(["bash", str(uc), *args], capture_output=True, text=True, env=env, timeout=120)


class TestRealScriptEmitsEvents:
    def test_script_is_valid_bash(self):
        assert subprocess.run(["bash", "-n", str(UC)]).returncode == 0

    def test_a_full_run_emits_the_four_phases_per_host_and_keeps_the_human_log(self, tmp_path, dp):
        r = _run_update_core(tmp_path, [])
        assert r.returncode == 0, r.stderr[-2000:] + r.stdout[-2000:]
        run = dp.parse(r.stdout)
        cards = {(h["role"], h["host"]): h for h in run["hosts"]}
        assert set(cards) == {("server", "srv"), ("frontend", "fe"), ("host", "h1"), ("host", "h2"),
                              ("host", "r1"), ("docker", "dk"), ("windows", "win1")}
        for key in (("server", "srv"), ("host", "h1"), ("host", "h2")):
            ph = cards[key]["phases"]
            assert [ph[p]["state"] for p in ("rsync", "restart", "health")] == ["ok"] * 3, key
        assert cards[("frontend", "fe")]["phases"]["install"]["state"] == "ok"
        assert cards[("host", "h1")]["phases"]["install"]["state"] == "ok"            # feature-unit reconcile
        assert cards[("windows", "win1")]["phases"]["restart"]["state"] == "ok"
        assert cards[("docker", "dk")]["phases"]["install"]["state"] == "ok"
        assert run["state"] == "ok" and run["ignored"] == 0
        # the human log is still there, line for line
        assert "==> [proxmox -> h1] rsync push" in r.stdout and "========== DEPLOY SUMMARY ==========" in r.stdout
        # events sit on their own lines and are valid JSON
        for line in r.stdout.splitlines():
            if line.startswith("VPT_PROGRESS "):
                json.loads(line[len("VPT_PROGRESS "):])

    def test_a_failed_rsync_is_a_failed_card_and_the_run_goes_on(self, tmp_path, dp):
        r = _run_update_core(tmp_path, ["--host"], STUB_FAIL_RSYNC="h2")
        run = dp.parse(r.stdout)
        cards = {h["host"]: h for h in run["hosts"]}
        assert cards["h2"]["state"] == "failed" and cards["h2"]["phases"]["rsync"]["detail"] == "rsync push failed"
        assert "restart" not in cards["h2"]["phases"]
        assert cards["h1"]["state"] == "ok"
        assert "FAILED (1): h2" in r.stdout and run["state"] == "failed"

    def test_a_failed_frontend_build_stops_before_restart(self, tmp_path, dp):
        r = _run_update_core(tmp_path, ["--frontend"], STUB_FAIL_BUILD="1")
        fe = next(h for h in dp.parse(r.stdout)["hosts"] if h["role"] == "frontend")
        assert fe["state"] == "failed" and fe["phases"]["install"]["state"] == "failed"
        assert "restart" not in fe["phases"]
        assert "frontend build FAILED" in r.stdout and r.returncode != 0


class TestLeaseScope:
    """What a run claims: a Windows host lives in its own lease env, a Windows-only deploy touches nothing on the node's."""

    def _claims(self, tmp_path, args):
        log = tmp_path / "claims.log"
        r = _run_update_core(tmp_path, args, STUB_LEASE_LOG=str(log))
        claims = [l for l in (log.read_text().splitlines() if log.exists() else []) if "--help" not in l]
        return r, [l.split(" --agent")[0] for l in claims]

    @pytest.mark.skipif(BASH_MAJOR < 4, reason="needs bash 4")
    def test_windows_only_claims_the_windows_env_and_nothing_on_the_node(self, tmp_path):
        r, claims = self._claims(tmp_path, ["main", "--host-windows"])
        assert claims == ["claim vpt-windows *"], (claims, r.stdout[-800:])
        assert "node1-vpt" not in "".join(claims)

    @pytest.mark.skipif(BASH_MAJOR < 4, reason="needs bash 4")
    def test_windows_plus_server_claims_both_envs(self, tmp_path):
        r, claims = self._claims(tmp_path, ["main", "--host-windows", "--server"])
        assert claims == ["claim node1-vpt *", "claim vpt-windows *"], (claims, r.stdout[-800:])


class TestHostOnlyClaimKind:
    """A host-only run claims `--kind host` (it must not queue server deploys); a run with a server or frontend keeps the default."""

    def _claims(self, tmp_path, args):
        log = tmp_path / "claims.log"
        r = _run_update_core(tmp_path, args, STUB_LEASE_LOG=str(log))
        claims = [l for l in (log.read_text().splitlines() if log.exists() else []) if "--help" not in l]
        return r, claims

    @pytest.mark.skipif(BASH_MAJOR < 4, reason="needs bash 4")
    def test_host_only_claim_carries_kind_host(self, tmp_path):
        r, claims = self._claims(tmp_path, ["main", "--host"])
        assert len(claims) == 1 and "--kind host" in claims[0], (claims, r.stdout[-800:])

    @pytest.mark.skipif(BASH_MAJOR < 4, reason="needs bash 4")
    def test_mixed_runs_keep_the_default_kind(self, tmp_path):
        for args in (["main", "--host", "--server"], ["main", "--host", "--frontend"], ["main", "--server"], ["main", "--frontend"], ["main"]):
            sub = tmp_path / "_".join(a.strip("-") for a in args)
            sub.mkdir()
            r, claims = self._claims(sub, args)
            assert claims and all("--kind" not in c for c in claims), (args, claims)

    @pytest.mark.skipif(BASH_MAJOR < 4, reason="needs bash 4")
    def test_windows_claim_never_carries_kind(self, tmp_path):
        r, claims = self._claims(tmp_path, ["main", "--host", "--host-windows"])
        win = [c for c in claims if c.startswith("claim vpt-windows")]
        node = [c for c in claims if not c.startswith("claim vpt-windows")]
        assert len(win) == 1 and "--kind" not in win[0], claims
        assert len(node) == 1 and "--kind host" in node[0], claims


class TestLeaseTenMinuteCap:
    """Owner rule 2026-10-19: a deployment never holds a lease for more than 10 minutes."""

    @pytest.mark.skipif(BASH_MAJOR < 4, reason="needs bash 4")
    def test_every_claim_carries_ttl_10(self, tmp_path):
        log = tmp_path / "claims.log"
        r = _run_update_core(tmp_path, ["main", "--host-windows", "--server"], STUB_LEASE_LOG=str(log))
        claims = [l for l in log.read_text().splitlines() if "--help" not in l]
        assert len(claims) == 2, (claims, r.stdout[-800:])  # node + Windows
        for c in claims:
            assert " --ttl 10" in c + " " and "--ttl 60" not in c, c

    @pytest.mark.skipif(BASH_MAJOR < 4, reason="needs bash 4")
    def test_an_expired_lease_aborts_before_the_next_host_with_a_loud_error(self, tmp_path):
        # a negative TTL makes the lease already "expired" when the first host step is reached
        r = _run_update_core(tmp_path, ["main"], DEPLOY_LEASE_TTL_MIN="-1")
        assert r.returncode == 6, (r.returncode, r.stdout[-800:], r.stderr[-800:])
        assert "DEPLOY LEASE EXPIRED" in r.stderr and "ABORT before" in r.stderr


class TestJoinRunnerLease:
    """A deploy started by the runner joins the runner's lease (VPT_LEASE_ID) instead of claiming its own."""

    def _run(self, tmp_path, rc, lease_id="runner-lease-9"):
        log = tmp_path / "lease.log"; ev = tmp_path / "events.log"
        r = _run_update_core(tmp_path, ["main", "--server"], STUB_LEASE_LOG=str(log), STUB_EVENT_LOG=str(ev), STUB_VALIDATE_RC=str(rc),
                             VPT_LEASE_ID=lease_id, VPT_LEASE_AGENT="manager:deploy")
        lines = [l for l in (log.read_text().splitlines() if log.exists() else []) if "--help" not in l]
        events = ev.read_text().splitlines() if ev.exists() else []
        return r, lines, events

    @pytest.mark.skipif(BASH_MAJOR < 4, reason="needs bash 4")
    def test_valid_lease_is_joined_no_claim_no_release(self, tmp_path):
        r, claims, events = self._run(tmp_path, 0)
        assert claims == [] and events == ["validate runner-lease-9 --agent manager:deploy"], (claims, events, r.stdout[-800:])
        assert "holding lease runner-lease-9 on" in r.stdout and "joined" in r.stdout

    @pytest.mark.skipif(BASH_MAJOR < 4, reason="needs bash 4")
    def test_invalid_lease_claims_its_own_and_releases_it(self, tmp_path):
        r, claims, events = self._run(tmp_path, 3)
        assert len(claims) == 1 and claims[0].startswith("claim node1-vpt "), (claims, r.stdout[-800:])
        assert events == ["validate runner-lease-9 --agent manager:deploy", "release lease-stub-1"] and "not valid" in r.stdout


@pytest.mark.skipif(BASH_MAJOR < 4, reason="needs bash 4")
class TestSkipTargetsAlreadyCurrent:
    """A target whose recorded commit is the requested one (or a descendant of it) is dropped; the registry failing opens."""

    def _run(self, tmp_path, entries, args=("main",), **kw):
        repo, c1, c2, c3 = _git_repo(tmp_path)
        claims = tmp_path / "claims.log"
        env = dict(STUB_LEASE_LOG=str(claims), **kw)
        if entries is not None:
            env["STUB_LAST_JSON"] = _registry(tmp_path, entries(c1, c2, c3))
        r = _run_update_core(tmp_path, list(args), git_repo=repo, **env)
        made = [l for l in (claims.read_text().splitlines() if claims.exists() else []) if "--help" not in l]
        return r, made, c2

    def test_everything_current_exits_0_without_claiming(self, tmp_path):
        names = ["server", "frontend", "h1", "h2", "r1", "win1"]
        r, claims, c2 = self._run(tmp_path, lambda c1, c2, c3: {n: c2 for n in names})
        assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]
        assert f"nothing to deploy: every target already on {c2[:10]}" in r.stdout
        assert f"already on {c2[:10]}: h1 (skipped)" in r.stdout
        assert claims == [] and "Step 1" not in r.stdout and "rsync push" not in r.stdout

    def test_one_current_host_is_skipped_and_the_others_deploy(self, tmp_path):
        r, claims, c2 = self._run(tmp_path, lambda c1, c2, c3: {"h1": c2}, args=("main", "--host"))
        assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]
        assert f"already on {c2[:10]}: h1 (skipped)" in r.stdout
        assert "[proxmox -> h1] rsync push" not in r.stdout
        assert "[proxmox -> h2] rsync push" in r.stdout and len(claims) == 1
        assert "h1" not in claims[0].split(" --agent")[0]

    def test_a_target_on_a_newer_commit_is_never_rolled_back(self, tmp_path):
        r, claims, c2 = self._run(tmp_path, lambda c1, c2, c3: {"h1": c3, "h2": c1})
        assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]
        assert f"already on {c2[:10]}: h1 (skipped)" in r.stdout
        assert "h2 (skipped)" not in r.stdout
        assert "[proxmox -> h2] rsync push" in r.stdout and "[proxmox -> h1] rsync push" not in r.stdout

    def test_a_failed_record_does_not_count_as_current(self, tmp_path):
        r, claims, c2 = self._run(tmp_path, lambda c1, c2, c3: {"h1": (c2, "failed")}, args=("main", "--host"))
        assert "(skipped)" not in r.stdout and "[proxmox -> h1] rsync push" in r.stdout

    def test_registry_read_failure_deploys_as_today_with_one_warning(self, tmp_path):
        r, claims, c2 = self._run(tmp_path, None, args=("main", "--host"), STUB_LAST_RC="1")
        assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]
        assert r.stdout.count("WARNING: already-deployed check skipped") == 1
        assert "[proxmox -> h1] rsync push" in r.stdout and "[proxmox -> h2] rsync push" in r.stdout

    def test_redeploy_and_force_deploy_current_targets_anyway(self, tmp_path):
        for flag in ("--redeploy", "--force"):
            sub = tmp_path / flag.strip("-"); sub.mkdir()
            r, claims, c2 = self._run(sub, lambda c1, c2, c3: {"h1": c2, "h2": c2}, args=("main", "--host", flag))
            assert "(skipped)" not in r.stdout and "[proxmox -> h1] rsync push" in r.stdout, flag


class TestBusyHostRestartDeferred:
    """2026-10-19: a deploy restarted vpt-host on vpt-pi1 and killed the script it was running, because no lease covered it.
    Whatever the lease registry says, a host whose own scheduler reports a running deployment execution gets its code synced
    but its vpt-host restart deferred (the TASK-129 mechanism: SKIPPED_HOSTS -> catch-up deploy)."""

    BUSY_JSON = '{"success":true,"snapshot":{"running_executions":[{"id":"e1","status":"running"}]}}'
    IDLE_JSON = '{"success":true,"snapshot":{"running_executions":[]}}'

    def _run(self, tmp_path, monkeypatch, busy_host, extra_args=()):
        stub = SSH_STUB.replace(
            '  *"is-active"*) exit 1 ;;',
            '  *"is-active"*) exit 1 ;;\n'
            '  *"host/deployment/jobs"*) [[ "$*" == *"$STUB_BUSY_HOST"* && -n "$STUB_BUSY_HOST" ]] && echo "$STUB_JOBS_BUSY" || echo "$STUB_JOBS_IDLE" ;;')
        stub = stub.replace('cmd="${*: -1}"', 'cmd="${*: -1}"\n[[ -n "$STUB_CMD_LOG" ]] && echo "$*" >> "$STUB_CMD_LOG"')
        monkeypatch.setattr(sys.modules[__name__], "SSH_STUB", stub)
        log = tmp_path / "cmds.log"
        r = _run_update_core(tmp_path, ["main", "--host", *extra_args], STUB_CMD_LOG=str(log), STUB_BUSY_HOST=busy_host,
                             STUB_JOBS_BUSY=self.BUSY_JSON, STUB_JOBS_IDLE=self.IDLE_JSON)
        restarts = [l for l in log.read_text().splitlines() if "systemctl restart" in l and "vpt-host" in l]
        return r, restarts

    def test_script_is_valid_bash(self):
        assert subprocess.run(["bash", "-n", str(UC)], capture_output=True).returncode == 0

    def test_a_host_with_a_running_execution_is_synced_but_not_restarted(self, tmp_path, monkeypatch):
        r, restarts = self._run(tmp_path, monkeypatch, "h1")
        assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-500:]
        assert "[h1] code synced; vpt-host.service restart DEFERRED" in r.stdout
        assert not any("h1" in l for l in restarts), restarts
        assert any("h2" in l for l in restarts), restarts           # an idle host is restarted as always
        assert "SKIPPED_HOSTS=h1" in r.stdout                         # the registry queues the catch-up deploy
        assert re.search(r'VPT_PROGRESS .*"host": ?"h1".*"phase": ?"restart".*"state": ?"skipped"', r.stdout)

    def test_force_restarts_a_busy_host_anyway(self, tmp_path, monkeypatch):
        r, restarts = self._run(tmp_path, monkeypatch, "h1", ["--force"])
        assert any("h1" in l for l in restarts), restarts
        assert "DEFERRED" not in r.stdout and "SKIPPED_HOSTS=" not in r.stdout

    def test_idle_hosts_all_restart_and_nothing_is_skipped(self, tmp_path, monkeypatch):
        r, restarts = self._run(tmp_path, monkeypatch, "")
        assert {h for h in ("h1", "h2") if any(h in l for l in restarts)} == {"h1", "h2"}, restarts
        assert "DEFERRED" not in r.stdout and "SKIPPED_HOSTS=" not in r.stdout
