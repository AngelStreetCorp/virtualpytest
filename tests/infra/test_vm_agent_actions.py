"""VM agent opt-in action db-backup: auth, disabled, 409, cooldown, fixed unit. systemctl/journalctl are mocked."""
import importlib.util
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

pytestmark = pytest.mark.unit

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "infra", "vm_agent", "vpt_vm_agent.py")
TOKEN = "t" * 40


def load():
    spec = importlib.util.spec_from_file_location("vpt_vm_agent_under_test", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Systemd:
    """Fake systemctl/journalctl: records every argv; `props` is what `systemctl show` answers."""

    def __init__(self):
        self.calls, self.start_rc = [], 0
        self.props = {"ActiveState": "inactive", "SubState": "dead", "ExecMainStatus": "0",
                      "ExecMainStartTimestamp": "", "ExecMainExitTimestamp": ""}
        self.journal = "done\n"

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[:2] == ["systemctl", "show"]:
            return 0, "".join(f"{k}={v}\n" for k, v in self.props.items())
        if argv[:2] == ["systemctl", "start"]:
            return self.start_rc, "Failed to start" if self.start_rc else ""
        if argv[0] == "journalctl":
            return 0, self.journal
        raise AssertionError(argv)

    def starts(self):
        return [c for c in self.calls if c[:2] == ["systemctl", "start"]]


@pytest.fixture
def agent(monkeypatch):
    mod = load()
    monkeypatch.setenv("VM_AGENT_ACTIONS", "db-backup")
    monkeypatch.setenv("VM_AGENT_ACTION_TOKEN", TOKEN)
    monkeypatch.delenv("VM_AGENT_DB_BACKUP_UNIT", raising=False)
    sd = Systemd()
    clock = {"t": 1000.0}
    mod._db_backup = mod.SystemdUnitAction(mod.DEFAULT_DB_BACKUP_UNIT, run=sd, clock=lambda: clock["t"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    mod.port, mod.sd, mod.clock = server.server_address[1], sd, clock
    yield mod
    server.shutdown()


def call(mod, method, path="/actions/db-backup", token=TOKEN, body=None):
    headers = {"X-VM-Agent-Token": token} if token is not None else {}
    req = urllib.request.Request(f"http://127.0.0.1:{mod.port}{path}", method=method, headers=headers, data=body)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_post_starts_the_fixed_unit_and_returns_202(agent):
    code, body = call(agent, "POST")
    assert code == 202 and body["request_id"] and body["started_at"] == 1000.0
    assert agent.sd.starts() == [["systemctl", "start", "--no-block", "vpt-db-backup.service"]]


def test_unit_comes_from_config_never_from_the_request(agent, monkeypatch):
    monkeypatch.setenv("VM_AGENT_DB_BACKUP_UNIT", "custom-backup.service")
    agent._db_backup = None
    action = agent.db_backup_action()
    assert action._unit == "custom-backup.service"
    agent._db_backup = agent.SystemdUnitAction("custom-backup.service", run=agent.sd, clock=lambda: 1.0)
    call(agent, "POST", "/actions/db-backup?unit=sshd.service", body=b'{"unit": "sshd.service"}')
    assert agent.sd.starts() == [["systemctl", "start", "--no-block", "custom-backup.service"]]


def test_default_unit_when_unset(agent):
    agent._db_backup = None
    assert agent.db_backup_action()._unit == "vpt-db-backup.service"


@pytest.mark.parametrize("bad", ["", "sshd", "a b.service", "x;rm.service", "../x.service", "-h.service", "a/b.service"])
def test_unit_name_is_validated(agent, bad):
    with pytest.raises(ValueError):
        agent.SystemdUnitAction(bad)


def test_already_active_is_409(agent):
    assert call(agent, "POST")[0] == 202
    agent.sd.props.update(ActiveState="activating", SubState="start", ExecMainStartTimestamp="@999")
    code, body = call(agent, "POST")
    assert code == 409 and body["started_at"] == 999.0 and body["request_id"]
    assert len(agent.sd.starts()) == 1


def test_cooldown_after_a_success_but_a_failure_can_be_retried(agent):
    agent.sd.props.update(ActiveState="inactive", ExecMainStatus="3", ExecMainStartTimestamp="@900",
                          ExecMainExitTimestamp="@990")
    assert call(agent, "POST")[0] == 202                       # a failed run does not start the cooldown
    agent.sd.props.update(ExecMainStatus="0", ExecMainExitTimestamp="@1000")
    agent.clock["t"] += 100
    code, body = call(agent, "POST")
    assert code == 429 and 0 < body["retry_after"] <= 300
    agent.clock["t"] += 250
    assert call(agent, "POST")[0] == 202


def test_never_run_unit_is_not_in_cooldown(agent):
    assert call(agent, "POST")[0] == 202                       # ExecMainStatus=0 but no exit timestamp


def test_start_failure_is_a_500_not_a_crash(agent):
    agent.sd.start_rc = 5
    code, body = call(agent, "POST")
    assert code == 500 and "Failed to start" in body["error"]
    assert call(agent, "GET")[1]["running"] is False


def test_get_running_while_activating(agent):
    agent.sd.props.update(ActiveState="activating", SubState="start", ExecMainStatus="0", ExecMainStartTimestamp="@1000")
    code, st = call(agent, "GET")
    assert code == 200 and st["running"] is True and st["exit_code"] is None and st["finished_at"] is None
    assert st["started_at"] == 1000.0
    assert agent.sd.props and ["journalctl", "-u", "vpt-db-backup.service", "-n", "40", "--no-pager", "-o", "cat",
                               "--since", "@1000"] in agent.sd.calls


def test_get_finished_maps_exit_code_and_log(agent):
    agent.sd.props.update(ActiveState="inactive", ExecMainStatus="0", ExecMainStartTimestamp="@1000",
                          ExecMainExitTimestamp="@1042")
    code, st = call(agent, "GET")
    assert st["running"] is False and st["exit_code"] == 0 and st["finished_at"] == 1042.0
    assert st["log_tail"] == ["done"] and set(st) == {"request_id", "running", "started_at", "finished_at", "exit_code", "log_tail"}
    agent.sd.props.update(ActiveState="failed", SubState="failed", ExecMainStatus="1")
    assert call(agent, "GET")[1]["exit_code"] == 1
    agent.sd.props.update(ExecMainStatus="0")                  # failed without an exit status: never success
    assert call(agent, "GET")[1]["exit_code"] == -1


def test_get_before_any_run_has_no_exit_code(agent):
    st = call(agent, "GET")[1]
    assert st["running"] is False and st["exit_code"] is None and st["started_at"] is None


def test_log_tail_keeps_the_last_40_lines(agent):
    agent.sd.props.update(ExecMainStartTimestamp="@1000", ExecMainExitTimestamp="@1001")
    agent.sd.journal = "".join(f"l{i}\n" for i in range(100))
    tail = call(agent, "GET")[1]["log_tail"]
    assert len(tail) == 40 and tail[0] == "l60" and tail[-1] == "l99"


def test_auth_wrong_missing_and_right_token(agent):
    assert call(agent, "POST", token=None)[0] == 401
    assert call(agent, "POST", token="x" * 40)[0] == 401
    assert call(agent, "POST", token=TOKEN[:-1])[0] == 401
    assert call(agent, "GET", token="")[0] == 401
    assert agent.sd.calls == []
    assert call(agent, "GET")[0] == 200


def test_token_compared_in_constant_time(agent):
    src = open(_PATH, encoding="utf-8").read()
    assert "hmac.compare_digest" in src


def test_ip_allow_list_applies(agent, monkeypatch):
    monkeypatch.setattr(agent, "ALLOWED_CLIENTS", {"10.9.9.9"})
    assert call(agent, "POST")[0] == 403 and call(agent, "GET")[0] == 403
    assert agent.sd.calls == []


@pytest.mark.parametrize("actions,token", [("", TOKEN), ("db-backup", ""), ("other", TOKEN), ("", "")])
def test_disabled_means_404_on_both_routes(agent, monkeypatch, actions, token):
    monkeypatch.setenv("VM_AGENT_ACTIONS", actions)
    monkeypatch.setenv("VM_AGENT_ACTION_TOKEN", token)
    assert call(agent, "POST")[0] == 404 and call(agent, "GET")[0] == 404
    assert call(agent, "POST", token=None)[0] == 404          # no hint about the token either
    assert agent.sd.calls == []


def test_unknown_action_path_is_404(agent):
    assert call(agent, "POST", "/actions/other")[0] == 404
    assert call(agent, "GET", "/actions/other")[0] == 404
    assert call(agent, "POST", "/status")[0] == 404


def test_status_route_is_unchanged_and_needs_no_token(agent, monkeypatch):
    monkeypatch.setattr(agent, "_metrics", lambda: {"cpu_percent": 1})
    monkeypatch.setattr(agent, "_services", lambda: [])
    code, body = call(agent, "GET", "/status", token=None)
    assert code == 200 and set(body) == {"agent_version", "hostname", "timestamp", "metrics", "services"}
    assert call(agent, "POST", "/status")[0] == 404


def test_install_script_writes_the_token_file_0600():
    src = open(os.path.join(os.path.dirname(_PATH), "install.sh"), encoding="utf-8").read()
    assert "--action-token-file" in src and "chmod 600 /etc/default/vpt-vm-agent" in src
    assert "VM_AGENT_ACTIONS=$ACTIONS" in src and "VM_AGENT_ACTION_TOKEN=$TOKEN" in src


def test_unit_file_is_unsandboxed_oneshot_and_installed_only_with_the_action():
    d = os.path.dirname(_PATH)
    unit = open(os.path.join(d, "vpt-db-backup.service"), encoding="utf-8").read()
    assert "Type=oneshot" in unit and "ExecStart=/usr/local/bin/vpt-db-backup.sh" in unit and "Nice=10" in unit
    assert not any(l.startswith(("ProtectSystem", "ProtectHome", "PrivateTmp", "ReadOnlyPaths")) for l in unit.splitlines())
    agent_unit = open(os.path.join(d, "vpt-vm-agent.service"), encoding="utf-8").read()
    assert "ProtectSystem=strict" in agent_unit and "ReadWritePaths" not in agent_unit
    sh = open(os.path.join(d, "install.sh"), encoding="utf-8").read()
    assert 'if [ -n "$ACTIONS" ]; then' in sh and "vpt-db-backup.service" in sh
    assert "enable vpt-db-backup" not in sh and "start vpt-db-backup" not in sh
