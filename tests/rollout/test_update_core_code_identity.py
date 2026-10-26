"""The deploy's "code identity" check must not be defeatable, and the secondary-server catch-up must never be silent.

`update_core.sh` hashes the tracked tree a service runs from (`git ls-tree HEAD -- <paths>`) and compares that
hash with the marker on the host to decide whether the service has to be restarted. The dirty-tree guard that
decides whether the hash can be trusted used `git status --porcelain`, which also reports UNTRACKED files: one
stray file in `backend_server/` emptied the server code id on every deploy. An empty id then meant "skip" for the
secondary-server catch-up, so the catch-up - the only path that restarts a secondary server whose server code went
stale - never fired, and it failed quietly: the deploy summary said "OK (1)" and nothing said the secondary server
was never even checked.

These tests drive the real bash functions out of the deploy script, with a fake `git` on PATH and a stub `ssh`:
nothing leaves this machine, no host is touched. The last test runs the whole script against stubs.

The script under test is `setup/proxmox/node/update_core.sh`; `VPT_UPDATE_CORE_SH` points the tests at another
copy (the negative control runs them against the pre-fix script).
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

SERVER_CODE_PATHS = ("backend_server", "shared", "features", "scripts", "setup", "requirements.txt")


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


# ─── a fake git ───────────────────────────────────────────────────────────────

GIT_STUB = r'''#!/usr/bin/env bash
# A fake `git` for the deploy script: it answers rev-parse, status --porcelain and ls-tree.
# Untracked files ("?? path") are reported ONLY when the caller did not ask for the tracked-only
# status, exactly like the real git does (-u no / --untracked-files=no hides them).
[[ -n "${STUB_GIT_LOG:-}" ]] && echo "$*" >> "${STUB_GIT_LOG}"
cmd=""
for a in "$@"; do
  case "$a" in
    -C) ;;
    rev-parse|status|ls-tree) [[ -z "$cmd" ]] && cmd="$a" ;;
  esac
done
tracked_only=0
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[$i]}" in
    --untracked-files=no|-uno) tracked_only=1 ;;
    -u) [[ "${args[$((i + 1))]:-}" == "no" ]] && tracked_only=1 ;;
  esac
done
case "$cmd" in
  rev-parse)
    [[ "${STUB_GIT_NO_REPO:-0}" == "1" ]] && exit 128
    echo ".git"
    ;;
  status)
    if (( tracked_only )); then
      printf '%s' "${STUB_GIT_STATUS_TRACKED:-}"
    else
      printf '%s' "${STUB_GIT_STATUS_ALL:-}"
    fi
    ;;
  ls-tree)
    printf '%s' "${STUB_GIT_LS_TREE:-}"
    ;;
esac
exit 0
'''


def _fake_git(tmp_path) -> dict:
    """A PATH with the fake `git` first, plus the env its answers come from."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "git"
    stub.write_text(GIT_STUB, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return {"PATH": f"{bindir}:{os.environ['PATH']}"}


# ─── a real checkout ──────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _real_repo(tmp_path) -> Path:
    """A checkout with tracked files under every path the two code ids hash."""
    repo = tmp_path / "repo"
    for directory in ("backend_server/src", "backend_host/src", "shared/src", "features", "scripts", "setup"):
        (repo / directory).mkdir(parents=True, exist_ok=True)
    (repo / "backend_server" / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "backend_host" / "src" / "host.py").write_text("h = 1\n", encoding="utf-8")
    (repo / "shared" / "src" / "lib.py").write_text("y = 1\n", encoding="utf-8")
    (repo / "features" / "f.txt").write_text("f\n", encoding="utf-8")
    (repo / "scripts" / "s.sh").write_text("echo s\n", encoding="utf-8")
    (repo / "setup" / "setup.sh").write_text("echo setup\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("requests\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "v1")
    return repo


def _server_tree_hash(repo: Path) -> str:
    """The hash the deploy script computes for the server code tree."""
    out = subprocess.run(["git", "-C", str(repo), "ls-tree", "HEAD", "--", *SERVER_CODE_PATHS],
                         capture_output=True, text=True, check=True).stdout
    return hashlib.sha1(out.encode()).hexdigest()


# ─── the code id ──────────────────────────────────────────────────────────────

CODE_ID_HARNESS = r'''
set -u
REPO_DIR="${REPO_DIR}"
HOST_CODE_PATHS=(backend_host shared features requirements.txt)
HOST_CODE_IGNORE=$'\tshared/src/lib/game(2048)?/'
HOST_CODE_ID=""
SERVER_CODE_PATHS=(backend_server shared features scripts setup requirements.txt)
SERVER_CODE_ID=""
SERVER_CODE_MARKER='.vpt_server_code_id'
HOST_CODE_MARKER='.vpt_host_code_id'
SERVER_SERVICE="vpt-server.service"
HOST_SERVICE="vpt-host.service"
'''


def _code_id(script_text: str, which: str, repo_dir: str, env: dict | None = None) -> str:
    """Run the deploy script's own compute_*_code_id and return the id it left behind."""
    script = (CODE_ID_HARNESS
              + _functions(script_text, f"compute_{which}_code_id")
              + f"\ncompute_{which}_code_id\n"
              + f'printf "%s" "${{{which.upper()}_CODE_ID}}"\n')
    result = _run_bash(script, {"REPO_DIR": repo_dir, **(env or {})})
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout.strip()


class TestCodeIdentityIgnoresUntrackedFiles:
    """The hash describes the TRACKED tree (`ls-tree HEAD`): an untracked file is not part of it."""

    def test_an_untracked_file_leaves_the_server_code_id_computed(self, tmp_path, script_text):
        tree = "100644 blob 0123456789abcdef\tbackend_server/src/app.py\n"
        expected = hashlib.sha1(tree.encode()).hexdigest()
        got = _code_id(script_text, "server", str(tmp_path), {
            **_fake_git(tmp_path),
            "STUB_GIT_STATUS_ALL": "?? backend_server/src/app.py.new\n",
            "STUB_GIT_STATUS_TRACKED": "",
            "STUB_GIT_LS_TREE": tree,
        })
        assert got == expected, (
            "an untracked file emptied the server code id: the catch-up skips an empty id, "
            "so the secondary server was never restarted"
        )

    def test_a_modified_tracked_file_still_empties_the_server_code_id(self, tmp_path, script_text):
        got = _code_id(script_text, "server", str(tmp_path), {
            **_fake_git(tmp_path),
            "STUB_GIT_STATUS_ALL": " M backend_server/src/app.py\n",
            "STUB_GIT_STATUS_TRACKED": " M backend_server/src/app.py\n",
            "STUB_GIT_LS_TREE": "100644 blob 0123456789abcdef\tbackend_server/src/app.py\n",
        })
        assert got == "", "a tracked file edited locally must empty the id: the tree on disk is not the tree hashed"

    def test_the_status_probe_asks_git_for_the_tracked_files_only(self, tmp_path, script_text):
        log = tmp_path / "git.log"
        _code_id(script_text, "server", str(tmp_path), {
            **_fake_git(tmp_path),
            "STUB_GIT_LOG": str(log),
            "STUB_GIT_STATUS_ALL": "?? backend_server/src/app.py.new\n",
            "STUB_GIT_STATUS_TRACKED": "",
            "STUB_GIT_LS_TREE": "100644 blob 0123456789abcdef\tbackend_server/src/app.py\n",
        })
        probes = [line for line in log.read_text(encoding="utf-8").splitlines() if " status " in line]
        assert probes, "the deploy script never asked git for the status of the server tree"
        assert all("--untracked-files=no" in line for line in probes), probes

    def test_a_real_untracked_file_in_the_server_tree_keeps_the_code_id(self, tmp_path, script_text):
        repo = _real_repo(tmp_path)
        (repo / "backend_server" / "src" / "app.py.new").write_text("draft\n", encoding="utf-8")
        assert _code_id(script_text, "server", str(repo)) == _server_tree_hash(repo), (
            "one untracked file in backend_server/ emptied the server code id"
        )

    def test_a_real_untracked_file_in_the_host_tree_keeps_the_host_code_id(self, tmp_path, script_text):
        repo = _real_repo(tmp_path)
        (repo / "backend_host" / "src" / "host.py.new").write_text("draft\n", encoding="utf-8")
        assert _code_id(script_text, "host", str(repo)) != "", "an untracked file emptied the host code id"

    def test_a_real_modified_tracked_file_empties_the_code_id(self, tmp_path, script_text):
        repo = _real_repo(tmp_path)
        (repo / "backend_server" / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")
        assert _code_id(script_text, "server", str(repo)) == "", (
            "a tracked file edited locally must empty the id"
        )


# ─── what the caller does with an empty id ───────────────────────────────────

# A fake `ssh`: the last argument is the remote command, the one before it the target.
# The banner `run_ssh` prints belongs to run_ssh, not to the remote output. The tests drive the
# REAL run_ssh, so the banner really is in the way of a value read, exactly as in production
# (a stubbed run_ssh that printed no banner tested a fiction).
SSH_MARKER_STUB = r'''#!/usr/bin/env bash
cmd="${*: -1}"
case "$cmd" in
  *"cat ~/.vpt_server_code_id"*) [[ -f "${STUB_MARKER_FILE}" ]] && cat "${STUB_MARKER_FILE}"; exit 0 ;;
  *"echo "*" > ~/.vpt_server_code_id"*)
      id="$(printf '%s' "$cmd" | sed -n 's/^echo \([^ ]*\) > .*$/\1/p')"
      printf '%s\n' "$id" > "${STUB_MARKER_FILE}"
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
    stub.write_text(SSH_MARKER_STUB, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return {"PATH": f"{bindir}:{os.environ['PATH']}"}


CALLER_HARNESS = r'''
set -u
SSH_USER="vpt_user"
SSH_KEY="${SSH_KEY:-/nonexistent/key}"
SSH_OPTS="-i ${SSH_KEY} -o BatchMode=yes"
HOST_CODE_ID=""
SERVER_CODE_ID="${SERVER_CODE_ID:-}"
HOST_CODE_MARKER='.vpt_host_code_id'
SERVER_CODE_MARKER='.vpt_server_code_id'
HOST_SERVICE="vpt-host.service"
SERVER_SERVICE="vpt-server.service"
DEPLOY_PHASE=server
PROGRESS_ROLE=""
STUB_LOG="${STUB_LOG}"
STUB_MARKER_FILE="${STUB_MARKER_FILE}"
rsync_push() { echo "RSYNC $1" >> "$STUB_LOG"; return 0; }
defer_busy_host_restart() { return 1; }
restart_and_status() { echo "RESTART $1 $2" >> "$STUB_LOG"; progress "$1" restart ok "$2"; return 0; }
'''


class TestAnEmptyIdMeansRestart:
    """Empty = unknown = restart. It must never mean "the code is unchanged, skip"."""

    def _run(self, script_text: str, tmp_path, server_code_id: str, marker: str = "") -> str:
        log = tmp_path / "calls.log"
        marker_file = tmp_path / "marker"
        marker_file.write_text(marker, encoding="utf-8")
        script = (CALLER_HARNESS
                  + _functions(script_text, "is_ipv4_target", "build_ssh_target", "run_ssh")
                  + _optional_functions(script_text, "read_remote")
                  + _functions(script_text, "ip_host_name")
                  + _optional_functions(script_text, "target_identities", "is_secondary_server_host")
                  + _functions(script_text, "progress_json_escape", "progress", "sync_and_restart")
                  + '\nsync_and_restart "srv" "vpt-server.service"\n')
        result = _run_bash(script, {**_fake_ssh(tmp_path), "STUB_LOG": str(log),
                                    "STUB_MARKER_FILE": str(marker_file),
                                    "SERVER_CODE_ID": server_code_id,
                                    "HOME": str(tmp_path / "home")})
        assert result.returncode == 0, result.stderr[-2000:]
        return log.read_text(encoding="utf-8")

    def test_an_empty_server_code_id_restarts_the_service(self, tmp_path, script_text):
        calls = self._run(script_text, tmp_path, "")
        assert "RESTART srv vpt-server.service" in calls, calls

    def test_a_known_server_code_id_may_skip_the_restart(self, tmp_path, script_text):
        """The other half of the rule: a known id that matches the marker still skips."""
        calls = self._run(script_text, tmp_path, "abc123", marker="abc123")
        assert "RESTART srv vpt-server.service" not in calls, calls


# ─── the secondary-server catch-up ────────────────────────────────────────────

CATCHUP_HARNESS = r'''
set -u
SSH_USER="vpt_user"
SSH_KEY="${SSH_KEY:-/nonexistent/key}"
SSH_OPTS="-i ${SSH_KEY} -o BatchMode=yes"
SERVER_CODE_ID="${SERVER_CODE_ID:-}"
SERVER_CODE_MARKER='.vpt_server_code_id'
SERVER_SERVICE="vpt-server.service"
SERVER_IP="srv,pi-secondary"
DEPLOY_PHASE=host
PROGRESS_ROLE=""
SECONDARY_CATCHUP=()
STUB_LOG="${STUB_LOG}"
STUB_MARKER_FILE="${STUB_MARKER_FILE}"
restart_and_status() {
  local host="$1" service="$2"
  echo "RESTART $host $service" >> "$STUB_LOG"
  progress "${host}" restart ok "${service}"
  return 0
}
'''


class TestSecondaryServerCatchUp:
    """The catch-up is the only path that restarts a secondary server whose server code went stale."""

    def _run(self, script_text: str, tmp_path, server_code_id: str, marker: str, host: str = "pi-secondary"):
        log = tmp_path / "calls.log"
        log.write_text("", encoding="utf-8")
        marker_file = tmp_path / "marker"
        marker_file.write_text(marker, encoding="utf-8")
        script = (CATCHUP_HARNESS
                  + _functions(script_text, "is_ipv4_target", "build_ssh_target", "run_ssh")
                  + _optional_functions(script_text, "read_remote")
                  + _functions(script_text, "ip_host_name")
                  + _optional_functions(script_text, "target_identities", "is_secondary_server_host")
                  + _functions(script_text, "progress_json_escape", "progress",
                               "server_secondary_names", "catch_up_secondary_server")
                  + f'\ncatch_up_secondary_server "{host}"\n')
        result = _run_bash(script, {**_fake_ssh(tmp_path),
                                    "STUB_LOG": str(log),
                                    "STUB_MARKER_FILE": str(marker_file),
                                    "SERVER_CODE_ID": server_code_id,
                                    "HOME": str(tmp_path / "home")})
        assert result.returncode == 0, result.stderr[-2000:]
        calls = log.read_text(encoding="utf-8")
        return result.stdout, calls, marker_file

    def test_an_unknown_code_id_restarts_the_secondary_server(self, tmp_path, script_text):
        """No id = we do not know what it runs: restart, never skip."""
        out, calls, _ = self._run(script_text, tmp_path, "", "")
        assert "RESTART pi-secondary vpt-server.service" in calls, (
            "an empty code id skipped the secondary server: that is how the catch-up stayed dead for a day"
        )
        assert "pi-secondary" in out and "identity unknown" in out, out

    def test_a_stale_secondary_server_is_restarted_and_its_marker_written(self, tmp_path, script_text):
        out, calls, marker_file = self._run(script_text, tmp_path, "abc123", "old-id")
        assert "RESTART pi-secondary vpt-server.service" in calls, calls
        assert marker_file.read_text(encoding="utf-8").strip() == "abc123", "the marker was not updated"
        assert "pi-secondary" in out and "stale" in out, out

    def test_a_current_secondary_server_is_not_restarted_but_is_reported(self, tmp_path, script_text):
        out, calls, _ = self._run(script_text, tmp_path, "abc123", "abc123")
        assert "RESTART pi-secondary vpt-server.service" not in calls, calls
        lines = [line for line in out.splitlines() if "pi-secondary" in line]
        assert lines, f"the catch-up said nothing about the secondary server:\n{out}"
        assert any("not restarted" in line.lower() for line in lines), out

    def test_a_current_secondary_server_pushes_a_progress_event(self, tmp_path, script_text):
        out, _, _ = self._run(script_text, tmp_path, "abc123", "abc123")
        events = [json.loads(line[len("VPT_PROGRESS "):]) for line in out.splitlines()
                  if line.startswith("VPT_PROGRESS ")]
        assert events, "the catch-up pushed no progress event: it looked like it had never run"
        event = next((e for e in events
                      if e.get("host") == "pi-secondary" and "secondary server" in e.get("detail", "")), None)
        assert event is not None, events
        assert event["state"] == "skipped", event

    def test_a_host_that_is_not_a_secondary_server_is_left_alone(self, tmp_path, script_text):
        out, calls, _ = self._run(script_text, tmp_path, "", "", host="some-other-host")
        assert "RESTART" not in calls, calls
        assert "secondary server" not in out, out


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
  *"is-active"*) exit 1 ;;
  *"cat ~/.vpt_server_code_id"*) [[ -f "$home/$target/.vpt_server_code_id" ]] && cat "$home/$target/.vpt_server_code_id" ;;
  *" > ~/.vpt_server_code_id"*)
      mkdir -p "$home/$target"
      id="$(printf '%s' "$cmd" | sed -n 's/^echo \([^ ]*\) > .*$/\1/p')"
      printf '%s\n' "$id" > "$home/$target/.vpt_server_code_id"
      ;;
esac
exit 0
'''

RSYNC_STUB = r'''#!/usr/bin/env bash
exit 0
'''

LEASE_STUB = r'''#!/usr/bin/env bash
case "$1" in
  validate) exit 3 ;;
  claim) case " $* " in *" --help "*) echo "usage: vpt-lease claim ... [--wait]";; *) echo "lease-stub-1";; esac ;;
esac
exit 0
'''


def _git_repo(tmp_path) -> Path:
    """A clone of a local origin, with the code paths tracked (the ids need a tree)."""
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "-C", str(origin), "init", "-q", "-b", "main"], check=True,
                   capture_output=True)
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


class TestWholeScriptWithASecondaryServer:
    """The end-to-end shape of the bug: a deploy with an untracked file in the server tree.

    The untracked file used to empty the server code id, the catch-up skipped an empty id, and the
    deploy summary said "OK (1)" - so nobody could see that the secondary server was never checked.
    """

    def _run(self, tmp_path, untracked: bool):
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
        if untracked:
            (repo / "backend_server" / "f.txt.new").write_text("draft\n", encoding="utf-8")
        # the node's own server plus one secondary server, which is also a host
        text = SCRIPT.read_text(encoding="utf-8")
        for key, value in (("SERVER_IP", "srv,pi-secondary"), ("HOST_IPS", "pi-secondary")):
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
        result = subprocess.run(["bash", str(script), "main", "--server", "--host"],
                                capture_output=True, text=True, env={**os.environ, **env}, timeout=180)
        return result

    def test_the_deploy_says_what_it_did_with_the_secondary_server(self, tmp_path):
        result = self._run(tmp_path, untracked=True)
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
        lines = [line for line in result.stdout.splitlines() if "pi-secondary" in line]
        assert lines, f"the deploy never mentioned the secondary server:\n{result.stdout[-3000:]}"
        assert any("secondary server" in line for line in lines), lines
        assert "SECONDARY SERVER (catch-up)" in result.stdout, result.stdout[-3000:]
