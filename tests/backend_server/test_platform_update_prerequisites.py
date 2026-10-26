"""TASK-101 G2: the 12 prerequisite checks, the required/aggregate logic. All machine access mocked."""
import os
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import db_backup, prerequisites as pr  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

GB = 1024 ** 3
SECRET = "glpat-ABCDEFGHIJKLMNOP"


def host_report(**over):
    rep = {"success": True, "supports_apply_bundle": True, "version": "1.0", "ok": True,
           "disk": {"ok": True, "project_free": 9 * GB, "backup_free": 9 * GB, "need_backup": GB},
           "tools": {"ok": True, "missing": []},
           "sudo": {"ok": True, "restart": {"ok": True, "detail": ""}, "reconcile": {"ok": True, "detail": ""}},
           "download": {"ok": True, "url": "https://s/ping", "detail": "downloaded and verified"}}
    rep.update(over)
    return rep


class FakeBackend:
    def __init__(self, can=True):
        self.can_execute = can


def make_deps(hosts=("h1", "h2"), reports=None, health=200, env=None, run=None, status=None, backend=None,
              locks=None, http=None, free=10 * GB, which=lambda n: "/usr/bin/" + n, db=None):
    reports = reports or {}
    status = status or {"tracker": "ready", "total": 5, "applied": 5, "pending": []}

    def call_host(host, endpoint, method="GET", timeout=9):
        name = host["host_name"]
        if endpoint == "/host/system/health":
            return {}, (health[name] if isinstance(health, dict) else health)
        r = reports.get(name, host_report())
        return (r, 200) if not isinstance(r, int) else ({"error": "nf"}, r)

    def default_run(argv, timeout, env=None):
        if argv[:1] == ["bash"]:
            return subprocess.CompletedProcess(argv, 0, "5\n", "")
        return subprocess.CompletedProcess(argv, 0, "ok\n", "")

    return pr.Deps(
        run=run or default_run, which=which, disk_free=lambda p: free,
        hosts=lambda: [{"host_name": h} for h in hosts], call_host=call_host,
        http_get=http or (lambda url, headers, timeout: type("R", (), {"status_code": 200, "json": lambda s: {"version": "16.0"}})()),
        locks=lambda: locks or {}, migration_status=lambda: (status, backend or FakeBackend()),
        build_root=lambda: "/tmp", env=env if env is not None else {"FRONTEND_DEPLOY_HOST": "none"},
        gitlab_credentials=lambda: ("https://gl.example", SECRET), github_token=lambda: "",
        core_remote=lambda: "https://github.com/x/y.git",
        db_backup=lambda: db or db_backup.Deps(env=env if env is not None else {}, report=lambda: {"filename": "f.dump", "size": "1M", "nfs_copy": True,
                                         "timestamp_iso": datetime.now(timezone.utc).isoformat()},
                                         http=lambda m, u, h, t: (404, {})),
    )


def by_id(out):
    return {c["id"]: c for c in out["checks"]}


def test_all_fields_and_all_twelve_checks():
    out = pr.run_all("github", "none", make_deps())
    assert [c["id"] for c in out["checks"]] == pr.ORDER and len(out["checks"]) == 12
    for c in out["checks"]:
        assert set(c) == {"id", "title", "required", "status", "detail", "log", "fix", "doc_anchor", "actions", "update_hosts"}
        assert c["status"] in ("ok", "ko", "na") and c["doc_anchor"] and c["title"]
    assert out["ok"] is True and out["total"] == out["passed"] + len([c for c in out["checks"] if c["status"] == "ko"])


def test_required_depends_on_the_chosen_sources():
    c = by_id(pr.run_all("zip", "none", make_deps()))
    assert c["github"]["status"] == "na" and not c["github"]["required"]
    assert c["gitlab"]["status"] == "na"
    c = by_id(pr.run_all("github", "gitlab", make_deps()))
    assert c["github"]["status"] == "ok" and c["github"]["required"]
    assert c["gitlab"]["status"] == "ok" and c["gitlab"]["required"]
    c = by_id(pr.run_all("zip", "github", make_deps()))
    assert c["github"]["required"]
    assert by_id(pr.run_all("bogus", "bogus", make_deps()))["github"]["status"] == "ok"  # unknown -> defaults


def test_frontend_none_is_na_and_never_blocks():
    c = by_id(pr.run_all("zip", "none", make_deps(env={"FRONTEND_DEPLOY_HOST": "none"})))["frontend_ssh"]
    assert c["status"] == "na" and c["required"] is False


def test_frontend_host_unset_is_ko_with_the_instruction():
    out = pr.run_all("zip", "none", make_deps(env={}))
    c = by_id(out)["frontend_ssh"]
    assert c["status"] == "ko" and c["required"] and out["ok"] is False
    assert "FRONTEND_DEPLOY_HOST" in c["detail"] and "host, local or none" in c["fix"]


def test_frontend_local_checks_the_server_itself():
    seen = []

    def run(argv, timeout, env=None):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "5\n" if argv[0] == "bash" else "", "")
    c = by_id(pr.run_all("zip", "none", make_deps(env={"FRONTEND_DEPLOY_HOST": "local"}, run=run)))["frontend_ssh"]
    assert c["status"] == "ok" and c["required"] and "local" in c["detail"]
    assert not any(a[0] == "ssh" for a in seen)
    assert ["sudo", "-n", "-l", "systemctl", "restart", "vpt-frontend"] in seen

    def no_unit(argv, timeout, env=None):
        bad = argv[:2] == ["systemctl", "cat"]
        return subprocess.CompletedProcess(argv, 1 if bad else 0, "5\n" if argv[0] == "bash" else "", "Unit not found" if bad else "")
    c = by_id(pr.run_all("zip", "none", make_deps(env={"FRONTEND_DEPLOY_HOST": "local"}, run=no_unit)))["frontend_ssh"]
    assert c["status"] == "ko" and "vpt-frontend unit exists" in c["detail"] and "no vpt-frontend unit" in c["fix"]


def test_frontend_host_value_is_the_ssh_target():
    from backend_server.src.lib.platform_update import frontend_ssh as fs
    assert fs.config({"FRONTEND_DEPLOY_HOST": "10.0.0.5"})["mode"] == "ssh"
    assert fs.config({"FRONTEND_DEPLOY_HOST": "10.0.0.5"})["host"] == "10.0.0.5"
    for value, mode in (("local", "local"), ("LOCAL", "local"), ("none", "none"), ("", "unset")):
        cfg = fs.config({"FRONTEND_DEPLOY_HOST": value})
        assert cfg["mode"] == mode and cfg["host"] == ""


def test_old_deploy_path_has_no_hardcoded_lab_host(monkeypatch):
    from backend_server.src.routes import server_system_routes as sysr
    assert not hasattr(sysr, "DEFAULT_FRONTEND_DEPLOY_HOST")
    monkeypatch.delenv("FRONTEND_DEPLOY_HOST", raising=False)
    assert sysr._frontend_remote_config()["host"] == ""
    monkeypatch.setenv("FRONTEND_DEPLOY_HOST", "local")
    assert sysr._frontend_remote_config()["host"] == ""             # local = no ssh target
    monkeypatch.setenv("FRONTEND_DEPLOY_HOST", "192.0.2.7")
    assert sysr._frontend_remote_config()["host"] == "192.0.2.7"


def test_frontend_ssh_ok_ko_and_password_masked():
    env = {"FRONTEND_DEPLOY_HOST": "fe", "FRONTEND_DEPLOY_SSH_USER": "deploy"}
    seen = []

    def run(argv, timeout, env=None):
        seen.append((argv, env))
        return subprocess.CompletedProcess(argv, 0, "ok", "")
    c = by_id(pr.run_all("zip", "none", make_deps(env=env, run=run)))["frontend_ssh"]
    assert c["status"] == "ok" and c["required"]
    argvs = [a for a, _ in seen if a[0] == "ssh"]
    assert len(argvs) == 4 and "BatchMode=yes" in argvs[0] and "deploy@fe" in argvs[0]

    def denied(argv, timeout, env=None):
        return subprocess.CompletedProcess(argv, 255, "", "Permission denied (publickey).")
    c = by_id(pr.run_all("zip", "none", make_deps(env=env, run=denied)))["frontend_ssh"]
    assert c["status"] == "ko" and "ssh login" in c["detail"] and "Server key" in c["fix"] and "Permission denied" in c["log"]

    def sudo_denied(argv, timeout, env=None):
        bad = "sudo" in argv[-1] and "true" in argv[-1]
        return subprocess.CompletedProcess(argv, 1 if bad else 0, "", "sudo: a password is required" if bad else "")
    c = by_id(pr.run_all("zip", "none", make_deps(env=env, run=sudo_denied)))["frontend_ssh"]
    assert c["status"] == "ko" and "sudo as the service user" in c["detail"]

    pw = {**env, "FRONTEND_DEPLOY_SSH_PASSWORD": "hunter2-secret"}

    def leaky(argv, timeout, env=None):
        assert "hunter2-secret" not in " ".join(argv[:-1]) and env == {"SSHPASS": "hunter2-secret"}
        return subprocess.CompletedProcess(argv, 1, "", "sudo said hunter2-secret")
    c = by_id(pr.run_all("zip", "none", make_deps(env=pw, run=leaky)))["frontend_ssh"]
    assert c["status"] == "ko" and "hunter2-secret" not in c["log"]


def test_frontend_ssh_missing_user_or_tool():
    c = by_id(pr.run_all("zip", "none", make_deps(env={"FRONTEND_DEPLOY_HOST": "fe"})))["frontend_ssh"]
    assert c["status"] == "ko" and "SSH_USER" in c["detail"]
    env = {"FRONTEND_DEPLOY_HOST": "fe", "FRONTEND_DEPLOY_SSH_USER": "u"}
    c = by_id(pr.run_all("zip", "none", make_deps(env=env, which=lambda n: None if n == "rsync" else "/x")))["frontend_ssh"]
    assert c["status"] == "ko" and "rsync" in c["detail"]


def test_hosts_api():
    c = by_id(pr.run_all("zip", "none", make_deps(health={"h1": 200, "h2": 503})))["hosts_api"]
    assert c["status"] == "ko" and "h2" in c["detail"] and "FAIL h2" in c["log"] and c["fix"]
    assert by_id(pr.run_all("zip", "none", make_deps(hosts=())))["hosts_api"]["status"] == "na"


def test_old_host_without_endpoint_is_ko_with_manual_update_hint():
    out = pr.run_all("zip", "none", make_deps(reports={"h2": 404}))
    c = by_id(out)
    assert c["host_version"]["status"] == "ko" and "h2" in c["host_version"]["detail"]
    assert "update this host once" in c["host_version"]["log"]
    assert out["ok"] is False


def test_hosts_download_and_sudo_and_disk_and_tools_from_reports():
    bad = host_report(download={"ok": False, "url": "https://s/ping", "detail": "HTTP 401"},
                      sudo={"ok": False, "restart": {"ok": False, "detail": "a password is required"},
                            "reconcile": {"ok": True, "detail": ""}},
                      disk={"ok": False, "project_free": GB // 10, "backup_free": GB, "need_backup": GB},
                      tools={"ok": False, "missing": ["rsync"]})
    c = by_id(pr.run_all("zip", "none", make_deps(reports={"h1": bad})))
    assert c["hosts_download"]["status"] == "ko" and "h1" in c["hosts_download"]["detail"] and "HTTP 401" in c["hosts_download"]["log"]
    assert c["host_sudo"]["status"] == "ko" and "password" in c["host_sudo"]["log"] and "sudoers" in c["host_sudo"]["fix"]
    assert "h1" in c["host_sudo"]["detail"] and "this server" not in c["host_sudo"]["detail"]
    assert c["disk"]["status"] == "ko" and "h1" in c["disk"]["detail"]
    assert c["tools"]["status"] == "ko" and "rsync (h1)" in c["tools"]["detail"]
    good = by_id(pr.run_all("zip", "none", make_deps()))
    for cid in ("hosts_download", "host_sudo", "disk", "tools", "host_version"):
        assert good[cid]["status"] == "ok", cid


def test_server_disk_low_and_tools_missing_and_old_bash():
    c = by_id(pr.run_all("zip", "none", make_deps(free=GB)))["disk"]
    assert c["status"] == "ko" and "server" in c["detail"]
    c = by_id(pr.run_all("zip", "none", make_deps(which=lambda n: None if n == "zip" else "/x")))["tools"]
    assert c["status"] == "ko" and "zip (server)" in c["detail"]
    # zip is not needed for a tar.gz bundle
    out = pr.run_all("zip", "none", make_deps(which=lambda n: None if n == "zip" else "/x"), fmt="tar.gz")
    assert by_id(out)["tools"]["status"] == "ok"

    def old_bash(argv, timeout, env=None):
        return subprocess.CompletedProcess(argv, 0, "3\n", "")
    c = by_id(pr.run_all("zip", "none", make_deps(run=old_bash)))["tools"]
    assert c["status"] == "ko" and "bash" in c["detail"]


def test_database_required_only_when_pending():
    ok = by_id(pr.run_all("zip", "none", make_deps()))["database"]
    assert ok["status"] == "ok" and ok["required"] is False
    pending = {"tracker": "ready", "total": 5, "applied": 3, "pending": ["a.sql", "b.sql"]}
    c = by_id(pr.run_all("zip", "none", make_deps(status=pending)))["database"]
    assert c["status"] == "ok" and c["required"] is True
    c = by_id(pr.run_all("zip", "none", make_deps(status=pending, backend=FakeBackend(can=False))))["database"]
    assert c["status"] == "ko" and c["required"] and "PLATFORM_UPDATE_DB_URI" in c["fix"]
    out = pr.run_all("zip", "none", make_deps(backend=FakeBackend(can=False)))
    c = by_id(out)["database"]
    assert c["status"] == "ko" and c["required"] is False and out["ok"] is True      # nothing pending: only a warning
    missing = {"tracker": "missing", "total": 5, "applied": 0, "pending": []}
    c = by_id(pr.run_all("zip", "none", make_deps(status=missing)))["database"]
    assert c["status"] == "ko" and c["required"] and "tracker" in c["detail"]


def test_database_unreadable_is_required_ko():
    deps = make_deps()
    deps.migration_status = lambda: (_ for _ in ()).throw(RuntimeError("could not connect to server"))
    c = by_id(pr.run_all("zip", "none", deps))["database"]
    assert c["status"] == "ko" and c["required"]


def test_github_ko_masks_token_and_gitlab_states():
    def fail(argv, timeout, env=None):
        if argv[0] == "git":
            return subprocess.CompletedProcess(argv, 128, "", "fatal: unable to access 'https://x:glpat-ABCDEFGHIJKLMNOP@h/'")
        return subprocess.CompletedProcess(argv, 0, "5\n", "")
    c = by_id(pr.run_all("github", "none", make_deps(run=fail)))["github"]
    assert c["status"] == "ko" and c["required"] and SECRET not in c["log"] and "VPT_CORE_REMOTE" in c["fix"]

    def timeout(argv, t, env=None):
        if argv[0] == "git":
            raise subprocess.TimeoutExpired(argv, t)
        return subprocess.CompletedProcess(argv, 0, "5\n", "")
    assert "timed out" in by_id(pr.run_all("github", "none", make_deps(run=timeout)))["github"]["log"]

    http401 = lambda url, headers, t: type("R", (), {"status_code": 401, "json": lambda s: {}})()  # noqa: E731
    c = by_id(pr.run_all("zip", "gitlab", make_deps(http=http401)))["gitlab"]
    assert c["status"] == "ko" and "token" in c["detail"] and SECRET not in c["log"]

    def boom(url, headers, t):
        raise ConnectionError(f"cannot reach {url} with {SECRET}")
    c = by_id(pr.run_all("zip", "gitlab", make_deps(http=boom)))["gitlab"]
    assert c["status"] == "ko" and SECRET not in c["log"] + c["detail"]
    deps = make_deps()
    deps.gitlab_credentials = lambda: ("", "")
    c = by_id(pr.run_all("zip", "gitlab", deps))["gitlab"]
    assert c["status"] == "ko" and "Settings" in c["fix"]


def test_no_test_running_is_a_warning_not_a_blocker():
    busy = {"h1:device1": {"owner_type": "script", "lock_reason": "run"}, "h1:device2": {"owner_type": "manual_control"}}
    out = pr.run_all("zip", "none", make_deps(locks=busy))
    c = by_id(out)["no_test_running"]
    assert c["status"] == "ko" and c["required"] is False and "h1:device1" in c["log"] and out["ok"] is True
    manual = {"h1:device2": {"owner_type": "manual_control"}}
    assert by_id(pr.run_all("zip", "none", make_deps(locks=manual)))["no_test_running"]["status"] == "ok"


def test_a_raising_check_becomes_ko_and_a_slow_one_times_out(monkeypatch):
    def raising(ctx):
        raise ValueError("boom")
    monkeypatch.setitem(pr.CHECKS, "disk", raising)
    out = pr.run_all("zip", "none", make_deps())
    c = by_id(out)["disk"]
    assert c["status"] == "ko" and c["required"] and "boom" in c["detail"] and out["ok"] is False

    def slow(ctx):
        time.sleep(1.5)
    monkeypatch.setitem(pr.CHECKS, "tools", slow)
    t0 = time.monotonic()
    out = pr.run_all("zip", "none", make_deps(), timeout=0.3)
    assert time.monotonic() - t0 < 1.2
    assert "Timed out" in by_id(out)["tools"]["detail"] and by_id(out)["tools"]["status"] == "ko"


def test_aggregate_ok_logic():
    checks = [
        {"required": True, "status": "ok"}, {"required": True, "status": "na"},
        {"required": False, "status": "ko"}, {"required": False, "status": "ok"},
    ]
    s = pr.summarize(checks)
    assert s == {"ok": True, "passed": 2, "total": 3}
    checks.append({"required": True, "status": "ko"})
    assert pr.summarize(checks)["ok"] is False


def test_host_reports_fetched_once_per_run():
    calls = []
    deps = make_deps()
    inner = deps.call_host

    def counting(host, endpoint, method="GET", timeout=9):
        calls.append(endpoint)
        return inner(host, endpoint, method, timeout)
    deps.call_host = counting
    pr.run_all("zip", "none", deps)
    assert calls.count("/host/system/updatePrereqs") == 2          # 2 hosts, once each, despite 5 checks using them


def test_server_own_sudo_is_checked_too():
    def run(argv, timeout, env=None):
        if argv[:3] == ["sudo", "-n", "-l"]:
            return subprocess.CompletedProcess(argv, 1, "", "sudo: a password is required\n")
        return subprocess.CompletedProcess(argv, 0, "5\n", "")
    c = by_id(pr.run_all("zip", "none", make_deps(run=run)))["host_sudo"]
    assert c["status"] == "ko" and c["required"] and "this server" in c["detail"] and "vpt-server" in c["log"]
    # with no host at all the server's own rights still decide
    assert by_id(pr.run_all("zip", "none", make_deps(hosts=())))["host_sudo"]["status"] == "ok"


# -- GitHub auth: askpass, never argv (TASK-101 lab run 2026-10-14) -------------------------------------
def test_github_token_goes_through_askpass_never_argv(tmp_path):
    token = "ghp_" + "a" * 36
    seen = {}

    def run(argv, timeout, env=None):
        if argv[0] == "git":
            seen["argv"], seen["env"] = list(argv), dict(env or {})
            script = env["GIT_ASKPASS"]
            seen["script"] = script
            seen["mode"] = oct(os.stat(script).st_mode & 0o777)
            seen["user"] = subprocess.run([script, "Username for 'https://github.com': "], capture_output=True, text=True).stdout
            seen["pass"] = subprocess.run([script, "Password for 'https://x-access-token@github.com': "], capture_output=True, text=True).stdout
            return subprocess.CompletedProcess(argv, 0, "abc\tHEAD\n", "")
        return subprocess.CompletedProcess(argv, 0, "5\n", "")
    deps = make_deps(run=run, env={"FRONTEND_DEPLOY_HOST": "none", "GITHUB_TOKEN": token})
    deps.github_token = None                                   # read from env: VPT_GITHUB_TOKEN, else GITHUB_TOKEN
    deps.core_remote = lambda: "https://github.com/AngelStreetCorp/virtualpytest.git"
    c = by_id(pr.run_all("github", "none", deps))["github"]
    assert c["status"] == "ok"
    assert token not in " ".join(seen["argv"]) and "extraHeader" not in " ".join(seen["argv"])
    assert seen["user"] == "x-access-token" and seen["pass"] == token and seen["mode"] == "0o700"
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0" and seen["env"]["GIT_ASKPASS_REQUIRE"] == "force"
    assert not os.path.exists(seen["script"]) and not os.path.exists(os.path.dirname(seen["script"]))
    assert token not in c["log"] + c["detail"]


def test_github_token_prefers_vpt_token_and_is_not_sent_to_a_mirror():
    seen = []

    def run(argv, timeout, env=None):
        if argv[0] == "git":
            seen.append(dict(env or {}))
        return subprocess.CompletedProcess(argv, 0, "5\n", "")
    deps = make_deps(run=run, env={"FRONTEND_DEPLOY_HOST": "none", "VPT_GITHUB_TOKEN": "ghp_" + "b" * 36, "GITHUB_TOKEN": "ghp_" + "c" * 36})
    deps.github_token = None
    deps.core_remote = lambda: "https://git.corp.example/team/core.git"
    assert by_id(pr.run_all("github", "none", deps))["github"]["status"] == "ok"
    assert "GIT_ASKPASS" not in seen[0] and seen[0]["GIT_TERMINAL_PROMPT"] == "0"


# -- the reconcile helper (TASK-101 lab run 2026-10-14) --------------------------------------------------
def test_server_sudo_probes_the_installed_helper_not_the_tree():
    from shared.src.lib.utils import update_privileges as priv
    seen = []

    def run(argv, timeout, env=None):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "5\n", "")
    c = by_id(pr.run_all("zip", "none", make_deps(run=run, hosts=())))["host_sudo"]
    assert c["status"] == "ok"
    assert ["sudo", "-n", "-l", priv.HELPER, "--project-root", "/opt/virtualpytest"] in seen
    assert not any("reconcile_feature_units.sh" in " ".join(a) for a in seen)


def test_stale_helper_is_a_ko(tmp_path, monkeypatch):
    from shared.src.lib.utils import update_privileges as priv
    root = tmp_path / "proj"
    (root / "setup/proxmox/node/lib").mkdir(parents=True)
    (root / "setup/proxmox/node/reconcile_feature_units.sh").write_text("new")
    (root / "setup/proxmox/node/lib/feature_units.sh").write_text("lib")
    helper, libdir = tmp_path / "helper", tmp_path / "lib"
    libdir.mkdir()
    helper.write_text("new")
    (libdir / "feature_units.sh").write_text("lib")
    assert priv.helper_stale(str(root), str(helper), str(libdir)) is None
    helper.write_text("old")
    assert priv.helper_stale(str(root), str(helper), str(libdir)) == "installed reconcile helper is older than the tree"
    helper.write_text("new")
    (libdir / "feature_units.sh").write_text("old lib")
    assert priv.helper_stale(str(root), str(helper), str(libdir)) == priv.STALE
    assert priv.helper_stale(str(root), str(tmp_path / "absent"), str(tmp_path / "nolib")) is None   # not installed: sudo probe says so

    monkeypatch.setattr(priv, "helper_stale", lambda root, *a, **k: priv.STALE)
    c = by_id(pr.run_all("zip", "none", make_deps(hosts=())))["host_sudo"]
    assert c["status"] == "ko" and "older than the tree" in c["log"]


def test_sudoers_dropin_grants_only_root_owned_paths():
    text = open(os.path.join(_repo_root, "setup/sudoers/vpt-update")).read()
    rules = [l.strip().rstrip(",\\ ") for l in text.splitlines() if l.strip().startswith("/")]
    assert "/usr/local/sbin/vpt-reconcile-feature-units --project-root /opt/virtualpytest" in rules
    assert {"/usr/bin/systemctl restart vpt-host", "/usr/bin/systemctl restart vpt-server", "/usr/bin/systemctl restart vpt-frontend"} <= set(rules)
    assert not any(r.startswith("/usr/bin/bash") or "/opt/virtualpytest/setup" in r for r in rules)
    assert "NOPASSWD: ALL" not in text


def test_installer_and_helper_scripts_parse():
    for rel in ("setup/sudoers/install_vpt_update_sudoers.sh", "setup/proxmox/node/reconcile_feature_units.sh"):
        assert subprocess.run(["bash", "-n", os.path.join(_repo_root, rel)]).returncode == 0


# -- db_backup: the agent action answers, or the last nightly backup is fresh --------------------------------
def _db(report=None, http=None, env=None, age_h=1.0):
    ts = (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat()
    rep = {"filename": "vpt_postgres_1.dump", "size": "1M", "nfs_copy": True, "timestamp_iso": ts} if report is None else report
    env = {"INFRA_VM_AGENTS": "database=10.0.0.2:9110", "VM_AGENT_ACTION_TOKEN": "t" * 32} if env is None else env
    return db_backup.Deps(env=env, report=lambda: rep, http=http or (lambda m, u, h, t: (200, {"running": False})))


def test_db_backup_ok_when_the_agent_action_answers_even_without_a_report():
    c = by_id(pr.run_all("zip", "none", make_deps(db=_db(report={}))))["db_backup"]
    assert c["status"] == "ok" and c["required"] and "agent answers" in c["detail"]


@pytest.mark.parametrize("code", [401, 404])
def test_db_backup_ko_when_agent_refuses_and_report_is_stale(code):
    c = by_id(pr.run_all("zip", "none", make_deps(db=_db(http=lambda m, u, h, t: (code, {}), age_h=30))))["db_backup"]
    assert c["status"] == "ko" and c["required"] and "backup" in c["fix"].lower() and "vpt-db-backup.sh" in c["fix"]
    assert str(code) in c["detail"]


def test_db_backup_falls_back_to_a_fresh_nightly_report():
    c = by_id(pr.run_all("zip", "none", make_deps(db=_db(env={}))))["db_backup"]
    assert c["status"] == "ok" and "nightly" in c["detail"]


def test_db_backup_ko_without_agent_and_with_stale_or_missing_report():
    assert by_id(pr.run_all("zip", "none", make_deps(db=_db(env={}, age_h=25))))["db_backup"]["status"] == "ko"
    c = by_id(pr.run_all("zip", "none", make_deps(db=_db(env={}, report={}))))["db_backup"]
    assert c["status"] == "ko" and "never reported" in c["detail"]


def test_db_backup_ko_when_the_agent_is_unreachable_and_never_leaks_the_token():
    def boom(m, u, h, t):
        raise OSError("down")
    c = by_id(pr.run_all("zip", "none", make_deps(db=_db(http=boom, age_h=50))))["db_backup"]
    assert c["status"] == "ko" and "t" * 32 not in str(c)


def test_tools_check_no_longer_needs_pg_dump():
    no_pg = lambda n: None if n == "pg_dump" else "/usr/bin/" + n  # noqa: E731
    env = {"FRONTEND_DEPLOY_HOST": "none", "PLATFORM_UPDATE_DB_URI": "postgresql://u:p@h/db"}
    c = by_id(pr.run_all("zip", "none", make_deps(which=no_pg, env=env)))["tools"]
    assert c["status"] == "ok" and "pg_dump" not in c["log"]


# -- TASK-128 G3: `actions` on the host_sudo KO row ---------------------------------------------------------------
def _sudo_bad(detail="a password is required"):
    return host_report(sudo={"ok": False, "restart": {"ok": False, "detail": detail},
                             "reconcile": {"ok": True, "detail": ""}})


def test_host_sudo_actions_name_each_failing_machine_with_its_own_project_root():
    reports = {"h1": _sudo_bad() | {"project_root": "/srv/vpt"}, "h2": _sudo_bad()}
    env = {"FRONTEND_DEPLOY_HOST": "none", "VPT_PROJECT_ROOT": "/opt/srv-root"}
    c = by_id(pr.run_all("zip", "none", make_deps(reports=reports, env=env)))["host_sudo"]
    acts = {a["machine"]: a for a in c["actions"]}
    assert set(acts) == {"h1", "h2"}
    assert acts["h1"]["command"] == "sudo bash /srv/vpt/setup/sudoers/install_vpt_update_sudoers.sh --project-root /srv/vpt"
    assert acts["h2"]["command"].endswith("--project-root /opt/srv-root")      # host without project_root: the server's
    assert acts["h1"]["reason"] == "a password is required"
    assert all(set(a) == {"machine", "command", "reason"} for a in c["actions"])


def test_host_sudo_stale_helper_action_is_the_same_command_with_the_stale_reason():
    from shared.src.lib.utils import update_privileges as priv
    stale = host_report(sudo={"ok": False, "restart": {"ok": True, "detail": ""},
                              "reconcile": {"ok": False, "detail": priv.STALE}})
    c = by_id(pr.run_all("zip", "none", make_deps(reports={"h1": stale})))["host_sudo"]
    assert [a["machine"] for a in c["actions"]] == ["h1"] and c["actions"][0]["reason"] == priv.STALE
    assert "install_vpt_update_sudoers.sh" in c["actions"][0]["command"]


def test_host_sudo_server_action_and_no_actions_when_ok_or_host_cannot_report():
    def run(argv, timeout, env=None):
        if argv[:3] == ["sudo", "-n", "-l"]:
            return subprocess.CompletedProcess(argv, 1, "", "sudo: a password is required\n")
        return subprocess.CompletedProcess(argv, 0, "5\n", "")
    c = by_id(pr.run_all("zip", "none", make_deps(run=run, hosts=("h1",))))["host_sudo"]
    assert [a["machine"] for a in c["actions"]] == ["this server"]       # one per machine, not per failing probe
    good = by_id(pr.run_all("zip", "none", make_deps()))
    assert all(x["actions"] == [] for x in good.values())
    old = by_id(pr.run_all("zip", "none", make_deps(reports={"h1": 404})))["host_sudo"]
    assert old["status"] == "ko" and old["actions"] == []                  # an unreachable host: no command can be built


# -- TASK-128 G5: a host that does not answer gets the one-line start command ---------------------------------------
def test_hosts_api_action_is_the_start_command_for_each_silent_host_only():
    c = by_id(pr.run_all("zip", "none", make_deps(health={"h1": 200, "h2": 503})))["hosts_api"]
    assert [(a["machine"], a["command"]) for a in c["actions"]] == [("h2", "sudo systemctl start vpt-host")]
    assert "h2 does not answer" in c["actions"][0]["reason"]
    ok = by_id(pr.run_all("zip", "none", make_deps()))["hosts_api"]
    assert ok["actions"] == []


# -- TASK-128 G8: the mismatch is named per host, the key value is never printed ----------------------------
def test_hosts_download_names_a_differing_server_url_with_the_env_line():
    bad = host_report(server_url="http://a:5109", project_root="/opt/virtualpytest",
                      download={"ok": False, "url": "http://a:5109/ping", "detail": "ConnectError"})
    env = {"FRONTEND_DEPLOY_HOST": "none", "SERVER_URL": "http://b:5109/"}
    c = by_id(pr.run_all("zip", "none", make_deps(env=env, reports={"h1": bad})))["hosts_download"]
    assert c["status"] == "ko" and "h1: SERVER_URL is http://a:5109, this server is http://b:5109" in c["detail"]
    assert c["actions"] == [{"machine": "h1", "command": "SERVER_URL=http://b:5109",
                             "reason": c["actions"][0]["reason"]}]
    assert "/opt/virtualpytest/.env" in c["actions"][0]["reason"]


def test_hosts_download_names_a_differing_api_key_without_printing_it():
    bad = host_report(server_url="http://b:5109", download={"ok": False, "url": "u", "detail": "the server answered HTTP 401"})
    env = {"FRONTEND_DEPLOY_HOST": "none", "SERVER_URL": "http://b:5109", "API_KEY": "sekret-key-value"}
    c = by_id(pr.run_all("zip", "none", make_deps(env=env, reports={"h1": bad})))["hosts_download"]
    assert "h1: API_KEY differs from this server's" in c["detail"]
    assert c["actions"][0]["command"] == "API_KEY=<copy API_KEY from the server's .env>"
    assert "sekret-key-value" not in repr(c)


def test_hosts_download_without_a_known_mismatch_has_no_actions():
    bad = host_report(server_url="http://b", download={"ok": False, "url": "u", "detail": "ConnectError"})
    c = by_id(pr.run_all("zip", "none", make_deps(env={"FRONTEND_DEPLOY_HOST": "none", "SERVER_URL": "http://b"}, reports={"h1": bad})))["hosts_download"]
    assert c["status"] == "ko" and c["actions"] == []


def test_hosts_api_401_names_the_api_key_not_a_stopped_service():
    c = by_id(pr.run_all("zip", "none", make_deps(health={"h1": 200, "h2": 401})))["hosts_api"]
    assert c["status"] == "ko" and "h2: API_KEY differs from this server's" in c["detail"]
    assert [a["machine"] for a in c["actions"]] == ["h2"] and c["actions"][0]["command"].startswith("API_KEY=<copy")


def test_the_host_report_carries_its_server_url():
    from backend_host.src.lib.utils import bundle_apply
    out = bundle_apply.self_check(project_root="/tmp", backup_root="/tmp", host_name="h", server_url="http://b:5109", headers={},
                                  get=lambda *a, **k: type("R", (), {"status_code": 500})())
    assert out["server_url"] == "http://b:5109"
