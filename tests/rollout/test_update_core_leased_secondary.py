"""A leased secondary server must get its catch-up, and a missing marker must read as missing (E64).

`update_core.sh` restarts a secondary server (a Pi that also runs `vpt-server.service`) when the
marker on that Pi does not match the server code id. The leased path never looked at that marker:
it queued a follow-up catch-up only when the HOST code changed, and the catch-up the runner queues
for a leased host is HOST-scoped, so the chain died there and the secondary server kept running old
code for ever (measured live on 2026-10-24: a Pi's `vpt-server.service` ran code from 03:32 UTC
while the tree on disk was already current).

The same file had two more defects of that class:

* the marker was read through `run_ssh`, whose own banner line is part of its stdout, so a MISSING
  marker read as the banner text instead of empty - "no marker" was indistinguishable from "some
  marker";
* the catch-up was only called in the host loop, so a runner that also runs a secondary server was
  never caught up.

These tests drive the real bash functions out of the deploy script with a fake `ssh` on PATH:
nothing leaves this machine, no host is touched. The script under test is
`setup/proxmox/node/update_core.sh`; `VPT_UPDATE_CORE_SH` points the tests at another copy (the
negative control runs them against the pre-fix script).
"""
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("VPT_UPDATE_CORE_SH")
              or (PROJECT_ROOT / "setup" / "proxmox" / "node" / "update_core.sh"))

pytestmark = pytest.mark.unit

# A documentation address (RFC 5737 TEST-NET-3), never a real host.
DOC_IP = "203.0.113.10"
# The lease environment of the test: a placeholder, not a real node.
LEASE_ENV = "test-env"


# ─── the script under test ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def script_text() -> str:
    if not SCRIPT.exists():
        pytest.skip(f"{SCRIPT} is not in this checkout")
    return SCRIPT.read_text(encoding="utf-8")


def _function_text(text: str, name: str) -> str:
    """The bash function `name`, verbatim, out of the deploy script."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith(f"{name}() {{")), None)
    assert start is not None, f"{name}() not found in {SCRIPT}"
    out = []
    for line in lines[start:]:
        out.append(line)
        if line.startswith("}"):
            break
    return "".join(out)


def _function_text_or_none(text: str, name: str) -> str:
    """The function `name`, or nothing when the script does not have it (the pre-fix script)."""
    lines = text.splitlines(keepends=True)
    if not any(line.startswith(f"{name}() {{") for line in lines):
        return ""
    return _function_text(text, name)


def _functions(text: str, *names: str) -> str:
    return "\n".join(_function_text(text, name) for name in names)


def _optional_functions(text: str, *names: str) -> str:
    return "\n".join(t for t in (_function_text_or_none(text, n) for n in names) if t)


def _run_bash(script: str, env: dict) -> subprocess.CompletedProcess:
    full = dict(os.environ)
    full.update(env)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=full, timeout=120)


# ─── a fake ssh: the remote side of every value read ──────────────────────────
#
# The banner `run_ssh` prints belongs to run_ssh, not to the remote output: the tests use the
# real run_ssh, so the banner really is in the way of a value read, exactly as in production.

SSH_VALUE_STUB = r'''#!/usr/bin/env bash
# A fake `ssh`: the last argument is the remote command, the one before it the target.
cmd="${*: -1}"
case "$cmd" in
  *"cat ~/.vpt_host_code_id"*)
      [[ -n "${STUB_HOST_MARKER:-}" ]] && printf '%s\n' "${STUB_HOST_MARKER}"
      exit 0
      ;;
  *"cat ~/.vpt_server_code_id"*)
      [[ -n "${STUB_SERVER_MARKER:-}" ]] && printf '%s\n' "${STUB_SERVER_MARKER}"
      exit 0
      ;;
  *"echo "*" > ~/.vpt_server_code_id"*)
      if [[ -n "${STUB_MARKER_FILE:-}" ]]; then
        id="$(printf '%s' "$cmd" | sed -n 's/^echo \([^ ]*\) > .*$/\1/p')"
        printf '%s\n' "$id" > "${STUB_MARKER_FILE}"
      fi
      exit 0
      ;;
  *"systemctl is-active"*) echo active; exit 0 ;;
esac
exit 0
'''


def _fake_ssh(tmp_path) -> dict:
    """A PATH with the fake `ssh` first."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "ssh"
    stub.write_text(SSH_VALUE_STUB, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return {"PATH": f"{bindir}:{os.environ['PATH']}"}


def _ssh_config(tmp_path, mapping: dict) -> dict:
    """A ~/.ssh/config that resolves a documentation IP to a name, like the lease code does."""
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True, exist_ok=True)
    lines = []
    for name, ip in mapping.items():
        lines.append(f"Host {name}\n  HostName {ip}\n")
    (home / ".ssh" / "config").write_text("\n".join(lines), encoding="utf-8")
    return {"HOME": str(home)}


def _field(out: str, name: str) -> str:
    for line in out.splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return ""


def _log(path: Path) -> str:
    """The content of a stub's log, empty when the stub never ran."""
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ─── the leased path ──────────────────────────────────────────────────────────

LEASED_HARNESS = r'''
set -u
SSH_USER="vpt_user"
SSH_KEY="${SSH_KEY:-/nonexistent/key}"
SSH_OPTS="-i ${SSH_KEY} -o BatchMode=yes"
# `-` and not `:-`: an id that is explicitly empty means "unknown identity", and the harness
# must not turn it back into a known one.
HOST_CODE_ID="${HOST_CODE_ID-host-id}"
SERVER_CODE_ID="${SERVER_CODE_ID-server-id}"
HOST_CODE_MARKER='.vpt_host_code_id'
SERVER_CODE_MARKER='.vpt_server_code_id'
HOST_SERVICE="vpt-host.service"
SERVER_SERVICE="vpt-server.service"
DEPLOY_SERVER="${DEPLOY_SERVER:-false}"
DEPLOY_PHASE=host
PROGRESS_ROLE=""
SERVER_IP="${SERVER_IP}"
SYNC_LEASED=(${SYNC_LEASED:-})
SYNC_LEASED_BY=(${SYNC_LEASED_BY:-})
SKIPPED_HOSTS=()
SKIPPED_BY=()
DEFERRED_RESTARTS=()
HOST_RESTART_SKIPPED=()
SECONDARY_CATCHUP=()
STUB_LOG="${STUB_LOG}"
rsync_push() { echo "RSYNC $1" >> "$STUB_LOG"; return 0; }
report_stale_aux_services() { echo "STALE-AUX $1" >> "$STUB_LOG"; return 0; }
'''


class TestLeasedSecondaryServerGetsItsCatchUp:
    """The leased path must notice a stale SECONDARY server and queue the catch-up."""

    def _run(self, tmp_path, script_text, host="pi-secondary", **env):
        log = tmp_path / "calls.log"
        log.write_text("", encoding="utf-8")
        script = (LEASED_HARNESS
                  + _functions(script_text, "is_ipv4_target", "build_ssh_target", "run_ssh")
                  + _optional_functions(script_text, "read_remote")
                  + _functions(script_text, "ip_host_name")
                  + _optional_functions(script_text, "target_identities", "is_secondary_server_host")
                  + _functions(script_text, "server_secondary_names", "sync_leased_index",
                               "is_sync_leased", "sync_leased_host")
                  + _functions(script_text, "progress_json_escape", "progress")
                  + 'if [[ -n "${STUB_FROZEN_SECONDARIES:-}" ]]; then SECONDARY_SERVERS="${STUB_FROZEN_SECONDARIES}"; else SECONDARY_SERVERS="$(server_secondary_names)"; fi\n'
                  + '\nsync_leased_host "${HOST}"\n'
                  + 'echo "SKIPPED_HOSTS=${SKIPPED_HOSTS[*]-}"\n'
                  + 'echo "DEFERRED=${DEFERRED_RESTARTS[*]-}"\n'
                  + 'echo "NOT_RESTARTED=${HOST_RESTART_SKIPPED[*]-}"\n'
                  + 'echo "SECONDARY=${SECONDARY_CATCHUP[*]-}"\n')
        base = {
            "STUB_LOG": str(log),
            "HOST": host,
            "SERVER_IP": "srv,pi-secondary",
            "SYNC_LEASED": "pi-secondary",
            "SYNC_LEASED_BY": "other-agent",
            "HOST_CODE_ID": "host-id",
            "SERVER_CODE_ID": "server-id",
            "STUB_HOST_MARKER": "host-id",
            "STUB_SERVER_MARKER": "",
            "HOME": str(tmp_path / "home"),
        }
        base.update(env)
        result = _run_bash(script, {**_fake_ssh(tmp_path), **base})
        assert result.returncode == 0, result.stderr[-2000:]
        return result.stdout, log.read_text(encoding="utf-8")

    def test_a_missing_server_marker_queues_the_catch_up(self, tmp_path, script_text):
        """No marker: the secondary server runs unknown code, so it needs the catch-up."""
        out, _ = self._run(tmp_path, script_text)
        assert "pi-secondary" in _field(out, "SKIPPED_HOSTS").split(), out
        assert "pi-secondary" in _field(out, "DEFERRED").split(), out

    def test_a_stale_server_marker_queues_the_catch_up(self, tmp_path, script_text):
        out, _ = self._run(tmp_path, script_text, STUB_SERVER_MARKER="old-id")
        assert "pi-secondary" in _field(out, "SKIPPED_HOSTS").split(), out
        assert "pi-secondary" in _field(out, "DEFERRED").split(), out

    def test_a_current_server_marker_queues_no_catch_up(self, tmp_path, script_text):
        """The server code is current: the host-code rules alone decide."""
        out, _ = self._run(tmp_path, script_text, STUB_SERVER_MARKER="server-id")
        assert "pi-secondary" not in _field(out, "SKIPPED_HOSTS").split(), out
        assert "pi-secondary" in _field(out, "NOT_RESTARTED").split(), out

    def test_a_leased_host_that_is_not_a_secondary_server_is_unchanged(self, tmp_path, script_text):
        out, _ = self._run(tmp_path, script_text, SERVER_IP="srv,other-secondary")
        assert "pi-secondary" not in _field(out, "SKIPPED_HOSTS").split(), out
        assert "pi-secondary" not in _field(out, "SECONDARY"), out

    def test_an_empty_server_code_id_queues_the_catch_up(self, tmp_path, script_text):
        """An unknown identity means RESTART, never skip (E62's rule), in the leased path too."""
        out, _ = self._run(tmp_path, script_text, SERVER_CODE_ID="")
        assert "pi-secondary" in _field(out, "SKIPPED_HOSTS").split(), out

    def test_a_secondary_server_addressed_by_ip_is_matched(self, tmp_path, script_text):
        """SERVER_IP may carry the IP: the lease code resolves an IP to a name, so must this."""
        env = _ssh_config(tmp_path, {"pi-secondary": DOC_IP})
        out, _ = self._run(tmp_path, script_text, SERVER_IP=f"srv,{DOC_IP}", **env)
        assert "pi-secondary" in _field(out, "SKIPPED_HOSTS").split(), out

    def test_a_host_addressed_by_ip_matches_a_secondary_server_by_name(self, tmp_path, script_text):
        env = _ssh_config(tmp_path, {"pi-secondary": DOC_IP})
        out, _ = self._run(tmp_path, script_text, host=DOC_IP, **env)
        assert DOC_IP in _field(out, "SKIPPED_HOSTS").split(), out

    def test_the_lease_plan_dropping_the_leased_server_from_SERVER_IP_does_not_hide_it(self, tmp_path, script_text):
        """The lease plan drops a LEASED secondary server from SERVER_IP; it is still one."""
        out, _ = self._run(tmp_path, script_text, SERVER_IP="srv",
                           STUB_FROZEN_SECONDARIES="pi-secondary")
        assert "pi-secondary" in _field(out, "SKIPPED_HOSTS").split(), out

    def test_the_stale_secondary_server_is_reported_in_the_summary(self, tmp_path, script_text):
        """A silent no-op is what made this cost a day: the outcome says what happened."""
        out, _ = self._run(tmp_path, script_text)
        assert "pi-secondary" in _field(out, "SECONDARY"), out
        assert "stale" in _field(out, "SECONDARY"), out


# ─── the marker read ──────────────────────────────────────────────────────────

CATCHUP_HARNESS = r'''
set -u
SSH_USER="vpt_user"
SSH_KEY="${SSH_KEY:-/nonexistent/key}"
SSH_OPTS="-i ${SSH_KEY} -o BatchMode=yes"
# `-` and not `:-`: an id that is explicitly empty means "unknown identity", and the harness
# must not turn it back into a known one.
SERVER_CODE_ID="${SERVER_CODE_ID-server-id}"
SERVER_CODE_MARKER='.vpt_server_code_id'
SERVER_SERVICE="vpt-server.service"
SERVER_IP="${SERVER_IP}"
DEPLOY_PHASE=host
PROGRESS_ROLE=""
SECONDARY_CATCHUP=()
STUB_LOG="${STUB_LOG}"
restart_and_status() {
  local host="$1" service="$2"
  echo "RESTART $host $service" >> "$STUB_LOG"
  progress "${host}" restart ok "${service}"
  return 0
}
'''


class TestAMissingMarkerReadsAsMissing:
    """`run_ssh` prints its own banner: a value read through it was the banner when it was empty."""

    def _catch_up(self, tmp_path, script_text, server_marker="", server_code_id="server-id"):
        log = tmp_path / "calls.log"
        log.write_text("", encoding="utf-8")
        marker_file = tmp_path / "marker"
        script = (CATCHUP_HARNESS
                  + _functions(script_text, "is_ipv4_target", "build_ssh_target", "run_ssh")
                  + _optional_functions(script_text, "read_remote")
                  + _functions(script_text, "ip_host_name")
                  + _optional_functions(script_text, "target_identities", "is_secondary_server_host")
                  + _functions(script_text, "server_secondary_names", "catch_up_secondary_server")
                  + _functions(script_text, "progress_json_escape", "progress")
                  + '\ncatch_up_secondary_server "pi-secondary"\n')
        result = _run_bash(script, {
            **_fake_ssh(tmp_path),
            "STUB_LOG": str(log),
            "STUB_MARKER_FILE": str(marker_file),
            "STUB_SERVER_MARKER": server_marker,
            "SERVER_CODE_ID": server_code_id,
            "SERVER_IP": "srv,pi-secondary",
            "HOME": str(tmp_path / "home"),
        })
        assert result.returncode == 0, result.stderr[-2000:]
        return result.stdout, log.read_text(encoding="utf-8")

    def test_a_missing_marker_is_reported_as_no_marker(self, tmp_path, script_text):
        """The banner is a log line, not a marker value: "no marker" must read as no marker."""
        out, _ = self._catch_up(tmp_path, script_text)
        assert "secondary server code is stale (no marker)" in out, out
        assert "cat ~/.vpt_server_code_id" not in out, out

    def test_a_missing_marker_still_restarts_the_server(self, tmp_path, script_text):
        _, calls = self._catch_up(tmp_path, script_text)
        assert "RESTART pi-secondary vpt-server.service" in calls, calls

    def test_a_current_marker_is_not_restarted(self, tmp_path, script_text):
        out, calls = self._catch_up(tmp_path, script_text, server_marker="server-id")
        assert "RESTART pi-secondary vpt-server.service" not in calls, calls
        assert "code is current" in out, out

    def test_a_stale_marker_is_restarted_and_the_marker_written(self, tmp_path, script_text):
        out, calls = self._catch_up(tmp_path, script_text, server_marker="old-id")
        assert "RESTART pi-secondary vpt-server.service" in calls, calls
        assert "stale" in out, out

    def test_an_empty_code_id_restarts_the_server(self, tmp_path, script_text):
        out, calls = self._catch_up(tmp_path, script_text, server_code_id="")
        assert "RESTART pi-secondary vpt-server.service" in calls, calls
        assert "identity unknown" in out, out


# ─── the whole script, against stubs ──────────────────────────────────────────

SSH_STUB = r'''#!/usr/bin/env bash
# The last argument is the remote command, the one before it is the target.
target="${*: -2:1}"
cmd="${*: -1}"
[[ -n "${STUB_CMD_LOG:-}" ]] && echo "$target | $cmd" >> "${STUB_CMD_LOG}"
home="${STUB_FAKE_HOME:-/tmp}"
case "$cmd" in
  *"--property=MainPID"*)
      n=0
      [[ -f "$home/$target/.pid" ]] && n="$(cat "$home/$target/.pid")"
      n=$((n + 1))
      mkdir -p "$home/$target"
      echo "$n" > "$home/$target/.pid"
      echo "$n"
      ;;
  *"--property=ActiveState"*) printf 'ActiveState=active\nSubState=running\nResult=success\nExecMainStatus=0\n' ;;
  *"is-active"*) echo active; exit 0 ;;
  *"cat ~/.vpt_server_code_id"*) [[ -f "$home/$target/.vpt_server_code_id" ]] && cat "$home/$target/.vpt_server_code_id" ;;
  *"cat ~/.vpt_host_code_id"*) [[ -f "$home/$target/.vpt_host_code_id" ]] && cat "$home/$target/.vpt_host_code_id" ;;
  *" > ~/.vpt_server_code_id"*)
      mkdir -p "$home/$target"
      id="$(printf '%s' "$cmd" | sed -n 's/^echo \([^ ]*\) > .*$/\1/p')"
      printf '%s\n' "$id" > "$home/$target/.vpt_server_code_id"
      ;;
esac
exit 0
'''

RSYNC_STUB = r'''#!/usr/bin/env bash
[[ -n "${STUB_RSYNC_LOG:-}" ]] && echo "${*: -1}" >> "${STUB_RSYNC_LOG}"
exit 0
'''

LEASE_STUB = r'''#!/usr/bin/env bash
case "$1" in
  validate) exit 3 ;;
  claim) case " $* " in *" --help "*) echo "usage: vpt-lease claim ... [--wait]";; *) echo "lease-stub-1";; esac ;;
  deploy) case " $* " in *" last "*) printf '%s' "${STUB_DEPLOY_LAST_JSON:-}";; esac ;;
esac
exit 0
'''


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _git_repo(tmp_path) -> Path:
    """A clone of a local origin, with the code paths tracked (the ids need a tree)."""
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "-C", str(origin), "init", "-q", "-b", "main"], check=True, capture_output=True)
    for directory in ("backend_host", "backend_server", "shared", "features", "scripts", "setup"):
        (origin / directory).mkdir()
        (origin / directory / "f.txt").write_text("x\n", encoding="utf-8")
    (origin / "requirements.txt").write_text("\n", encoding="utf-8")
    (origin / "VERSION.txt").write_text("current:main-1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(origin), "-c", "user.name=t", "-c", "user.email=t@t",
                    "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(origin), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "-m", "c1"], check=True, capture_output=True)
    repo = tmp_path / "checkout" / "virtualpytest"
    repo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
    return repo


class TestRunnerThatIsAlsoASecondaryServer:
    """The catch-up was called in the host loop only: a runner that also runs a server was skipped."""

    def _run(self, tmp_path):
        bins = tmp_path / "bin"
        bins.mkdir(exist_ok=True)
        for name, body in (("ssh", SSH_STUB), ("rsync", RSYNC_STUB), ("sleep", "#!/bin/sh\nexit 0\n")):
            path = bins / name
            path.write_text(body, encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        home = tmp_path / "home"
        (home / "bin").mkdir(parents=True, exist_ok=True)
        lease = home / "bin" / "vpt-lease"
        lease.write_text(LEASE_STUB, encoding="utf-8")
        lease.chmod(lease.stat().st_mode | stat.S_IEXEC)
        repo = _git_repo(tmp_path)
        text = SCRIPT.read_text(encoding="utf-8")
        # the node's own server, a secondary server that is also a RUNNER, and one plain host
        for key, value in (("SERVER_IP", "srv,pi-secondary"), ("HOST_IPS", "host-a"), ("RUNNER_IPS", "pi-secondary")):
            text = re.sub(rf"^{key}=.*$", f'{key}="{value}"', text, count=1, flags=re.M)
        script = tmp_path / "update_core.sh"
        script.write_text(text, encoding="utf-8")
        env = {
            "PATH": f"{bins}:{os.environ['PATH']}",
            "HOME": str(home),
            "REPO_DIR": str(repo),
            "SSH_KEY": str(tmp_path / "nokey"),
            "STUB_FAKE_HOME": str(tmp_path / "fake-home"),
        }
        return subprocess.run(["bash", str(script), "main", "--host"],
                              capture_output=True, text=True, env={**os.environ, **env}, timeout=180)

    def test_the_runner_secondary_server_is_caught_up(self, tmp_path):
        result = self._run(tmp_path)
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
        assert "SECONDARY SERVER (catch-up)" in result.stdout, result.stdout[-3000:]
        lines = [line for line in result.stdout.splitlines() if "pi-secondary" in line]
        assert lines, f"the deploy never mentioned the secondary server:\n{result.stdout[-3000:]}"
        assert any("secondary server" in line for line in lines), lines


# ─── the commit-level skip must not hide the secondary server ─────────────────

def _host_code_id(repo: Path) -> str:
    """The id the deploy script computes for the host code tree."""
    out = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "HEAD", "--",
                          "backend_host", "shared", "features", "requirements.txt"],
                         capture_output=True, text=True, check=True).stdout
    return hashlib.sha1(out.encode()).hexdigest()


def _server_code_id(repo: Path) -> str:
    """The id the deploy script computes for the server code tree."""
    out = subprocess.run(["git", "-C", str(repo), "ls-tree", "HEAD", "--",
                          "backend_server", "shared", "features", "scripts", "setup",
                          "requirements.txt"],
                         capture_output=True, text=True, check=True).stdout
    return hashlib.sha1(out.encode()).hexdigest()


class TestAlreadyOnCommitStillNeedsTheSecondaryCatchUp:
    """"already on <commit>" says the FILES are current; the catch-up asks about the PROCESS.

    The registry records the commit a host was deployed at, and a deploy that only SYNCED the code
    (its restart was deferred because the host was leased) is recorded at that commit too. The
    commit-level skip therefore dropped exactly the host whose secondary server still ran the old
    code, and the catch-up became unreachable for the host it exists for (E64, 2026-10-24).
    """

    def _run(self, tmp_path, hosts="pi-secondary", deployed=("pi-secondary",), server_marker="stale"):
        bins = tmp_path / "bin"
        bins.mkdir(exist_ok=True)
        for name, body in (("ssh", SSH_STUB), ("rsync", RSYNC_STUB), ("sleep", "#!/bin/sh\nexit 0\n")):
            path = bins / name
            path.write_text(body, encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        home = tmp_path / "home"
        (home / "bin").mkdir(parents=True, exist_ok=True)
        lease = home / "bin" / "vpt-lease"
        lease.write_text(LEASE_STUB, encoding="utf-8")
        lease.chmod(lease.stat().st_mode | stat.S_IEXEC)
        repo = _git_repo(tmp_path)
        commit = _git(repo, "rev-parse", "origin/main")
        # the registry: these targets were deployed at the requested commit
        entries = ", ".join(f'"{h}": {{"status": "done", "commit": "{commit}"}}' for h in deployed)
        last_json = json.dumps({"envs": {LEASE_ENV: json.loads("{" + entries + "}")}})
        # the fake home: the host code is current, the secondary server's marker is what the test says
        fake_home = tmp_path / "fake-home"
        marker = {"stale": "", "current": _server_code_id(repo)}[server_marker]
        for host in hosts.split(","):
            (fake_home / host).mkdir(parents=True, exist_ok=True)
            (fake_home / host / ".vpt_host_code_id").write_text(_host_code_id(repo), encoding="utf-8")
            if marker:
                (fake_home / host / ".vpt_server_code_id").write_text(marker, encoding="utf-8")
        text = SCRIPT.read_text(encoding="utf-8")
        for key, value in (("SERVER_IP", "srv,pi-secondary"), ("HOST_IPS", hosts)):
            text = re.sub(rf"^{key}=.*$", f'{key}="{value}"', text, count=1, flags=re.M)
        script = tmp_path / "update_core.sh"
        script.write_text(text, encoding="utf-8")
        rsync_log = tmp_path / "rsync.log"
        cmd_log = tmp_path / "cmd.log"
        env = {
            "PATH": f"{bins}:{os.environ['PATH']}",
            "HOME": str(home),
            "REPO_DIR": str(repo),
            "SSH_KEY": str(tmp_path / "nokey"),
            "STUB_FAKE_HOME": str(fake_home),
            "STUB_DEPLOY_LAST_JSON": last_json,
            "STUB_RSYNC_LOG": str(rsync_log),
            "STUB_CMD_LOG": str(cmd_log),
            "LEASE_ENV": LEASE_ENV,
        }
        result = subprocess.run(["bash", str(script), "main", "--host"],
                                capture_output=True, text=True, env={**os.environ, **env}, timeout=180)
        return result, rsync_log, cmd_log

    def test_a_stale_secondary_server_is_caught_up_although_the_host_is_already_on_the_commit(self, tmp_path):
        result, _, _ = self._run(tmp_path, server_marker="stale")
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
        assert "nothing to deploy" not in result.stdout, result.stdout[-3000:]
        assert "SECONDARY SERVER (catch-up)" in result.stdout, result.stdout[-3000:]
        assert "secondary server" in result.stdout, result.stdout[-3000:]

    def test_the_registry_says_done_but_the_restart_was_deferred_the_catch_up_still_runs(self, tmp_path):
        """The registry records the sync, not the restart: the marker is the other half of the truth."""
        result, _, _ = self._run(tmp_path, server_marker="stale")
        assert "SECONDARY SERVER (catch-up)" in result.stdout, result.stdout[-3000:]

    def test_a_current_secondary_server_leaves_the_host_skipped(self, tmp_path):
        """The optimisation must survive: nothing to catch up -> no rsync, no restart."""
        result, rsync_log, cmd_log = self._run(tmp_path, server_marker="current")
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
        assert "already on" in result.stdout and "(skipped)" in result.stdout, result.stdout[-3000:]
        assert "SECONDARY SERVER (catch-up)" not in result.stdout, result.stdout[-3000:]
        assert "pi-secondary" not in _log(rsync_log), _log(rsync_log)
        assert "restart \"vpt-server.service\"" not in _log(cmd_log), _log(cmd_log)

    def test_a_plain_host_that_is_already_on_the_commit_is_still_skipped(self, tmp_path):
        """A host without a secondary server keeps the plain skip: no rsync, no restart."""
        result, rsync_log, _ = self._run(tmp_path, hosts="host-a", deployed=("host-a",))
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
        assert "already on" in result.stdout and "host-a" in result.stdout, result.stdout[-3000:]
        assert "SECONDARY SERVER (catch-up)" not in result.stdout, result.stdout[-3000:]
        assert "host-a" not in _log(rsync_log), _log(rsync_log)
