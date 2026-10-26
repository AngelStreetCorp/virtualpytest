"""TASK-128 G10 + G11: package-manager detection and install lines, `tools` actions per machine, host_version actions."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import prerequisites as pr  # noqa: E402
from backend_host.src.lib.utils import bundle_apply  # noqa: E402
from shared.src.lib.utils import package_install as pi  # noqa: E402
from tests.backend_server.test_platform_update_prerequisites import by_id, host_report, make_deps  # noqa: E402


def only(*names):
    return lambda n: "/usr/bin/" + n if n in names else None


def test_detect_picks_the_first_supported_manager():
    assert pi.detect(only("apt-get")) == "apt-get"
    assert pi.detect(only("dnf")) == "dnf"
    assert pi.detect(only("apk")) == "apk"
    assert pi.detect(only("pacman")) == "pacman"
    assert pi.detect(only("zypper")) == ""


@pytest.mark.parametrize("manager,expected", [
    ("apt-get", "sudo apt-get install -y rsync zip"),
    ("dnf", "sudo dnf install -y rsync zip"),
    ("apk", "sudo apk add rsync zip"),
    ("pacman", "sudo pacman -S --noconfirm rsync zip"),
])
def test_install_command_per_manager(manager, expected):
    assert pi.install_command(manager, ["rsync", "zip"]) == expected


def test_tool_to_package_mapping_and_edge_cases():
    assert pi.packages_for("apt-get", ["git", "tar", "bash", "python3"]) == ["git", "tar", "bash", "python3"]
    assert pi.packages_for("pacman", ["python3", "git"]) == ["python", "git"]
    assert pi.packages_for("apt-get", ["zip", "zip"]) == ["zip"]
    assert pi.install_command("", ["zip"]) == "" and pi.install_command("zypper", ["zip"]) == ""
    assert pi.install_command("apt-get", []) == ""
    # sudo itself missing: the line must be run as root, so no sudo prefix
    assert pi.install_command("apt-get", ["sudo", "rsync"]) == "apt-get install -y sudo rsync"


def test_host_self_check_reports_pkg_manager_and_missing(tmp_path):
    def run(argv, timeout, env=None):
        import subprocess
        return subprocess.CompletedProcess(argv, 0, "", "")
    out = bundle_apply.self_check(project_root=str(tmp_path), backup_root=str(tmp_path), host_name="h", server_url="",
                                  headers={}, run=run, which=only("tar", "bash", "sudo", "dnf"))
    assert out["tools"]["missing"] == ["rsync"] and out["tools"]["pkg_manager"] == "dnf"


def test_tools_ko_has_one_command_per_machine_with_its_own_manager():
    reports = {"h1": host_report(tools={"ok": False, "missing": ["rsync", "tar"], "pkg_manager": "dnf"}),
               "h2": host_report(tools={"ok": False, "missing": ["bash"], "pkg_manager": "apk"})}
    c = by_id(pr.run_all("zip", "none", make_deps(reports=reports, which=lambda n: None if n == "zip" else "/usr/bin/" + n)))["tools"]
    assert c["status"] == "ko"
    got = {a["machine"]: a["command"] for a in c["actions"]}
    assert got["this server"] == "sudo apt-get install -y zip"
    assert got["h1"] == "sudo dnf install -y rsync tar" and got["h2"] == "sudo apk add bash"
    assert "root" in c["fix"]


def test_tools_without_known_manager_has_no_command_and_ok_has_none():
    reports = {"h1": host_report(tools={"ok": False, "missing": ["rsync"], "pkg_manager": ""})}
    c = by_id(pr.run_all("zip", "none", make_deps(reports=reports)))["tools"]
    assert c["status"] == "ko" and c["actions"] == []
    assert by_id(pr.run_all("zip", "none", make_deps()))["tools"]["actions"] == []


def test_host_version_old_host_gets_button_and_both_manual_commands():
    c = by_id(pr.run_all("zip", "none", make_deps(reports={"h2": 404})))["host_version"]
    assert c["status"] == "ko" and c["update_hosts"] == ["h2"]
    cmds = [a["command"] for a in c["actions"]]
    assert len(cmds) == 2 and all(a["machine"] == "h2" for a in c["actions"])
    assert cmds[0].startswith("cd /opt/virtualpytest && git pull --ff-only")
    assert cmds[1].startswith("rsync -a --exclude=.env") and "/mnt/shared/code/virtualpytest/" in cmds[1]
    assert all(cmd.endswith("sudo systemctl restart vpt-host") for cmd in cmds)


def test_host_version_other_ko_states_get_no_button_and_ok_has_none():
    unsupported = host_report(supports_apply_bundle=False, error="pull updates are not available on Windows hosts")
    c = by_id(pr.run_all("zip", "none", make_deps(reports={"h2": unsupported})))["host_version"]
    assert c["status"] == "ko" and c["update_hosts"] == [] and c["actions"] == []
    ok = by_id(pr.run_all("zip", "none", make_deps()))["host_version"]
    assert ok["status"] == "ok" and ok["update_hosts"] == []
