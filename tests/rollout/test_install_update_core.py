"""The repo's deploy script must be installable on a node without losing the node's fleet config.

The deploy runs `bash update_core.sh` on the Proxmox node - the copy in the node's home
directory, not the repo file. The two copies drift on purpose: the repo file is the template
(default targets for a fresh node), the node's copy carries that node's own targets. A blind
`scp` overwrites the node's targets with the template's, and the node then deploys to the
wrong VMs (BUG-0728, 2026-10-20: the fix was in the repo, the node kept the old script, so
a deploy that changed host code did not restart vpt-host).

`install_update_core.py` merges instead: the repo's script with the node's config values.
"""
import importlib.util
import os
import subprocess

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
INSTALLER = os.path.join(REPO_ROOT, "setup", "proxmox", "node", "install_update_core.py")
DEPLOY_SCRIPT = os.path.join(REPO_ROOT, "setup", "proxmox", "node", "update_core.sh")


def _load_installer():
    if not os.path.exists(INSTALLER):
        pytest.skip(f"{INSTALLER} is not in this checkout")
    spec = importlib.util.spec_from_file_location("install_update_core", INSTALLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def installer():
    return _load_installer()


@pytest.fixture(scope="module")
def repo_script_text():
    if not os.path.exists(DEPLOY_SCRIPT):
        pytest.skip(f"{DEPLOY_SCRIPT} is not in this checkout")
    with open(DEPLOY_SCRIPT, "r", encoding="utf-8") as handle:
        return handle.read()


def _node_copy(repo_text: str) -> str:
    """The repo script as a node's copy would look: its own fleet targets, same logic."""
    node_text = repo_text.replace(
        'SERVER_IP="${SERVER_IP:-192.168.0.103}"',
        'SERVER_IP="10.99.0.1,fake-alpha"',
    ).replace(
        'HOST_IPS="${HOST_IPS:-192.168.0.109,192.168.0.110}"',
        'HOST_IPS="fake-host-a,fake-host-b"',
    ).replace(
        'DOCKER_IPS="${DOCKER_IPS:-}"',
        'DOCKER_IPS="fake-docker"',
    )
    assert node_text != repo_text
    return node_text


def test_the_repo_script_has_a_config_block(installer, repo_script_text):
    """The config block is the leading run of comments and single-line assignments."""
    preamble, config, rest = installer.split_script(repo_script_text)
    assert preamble and preamble[0].startswith("#!")
    values = installer.config_values(config)
    for key in ("SERVER_IP", "FRONTEND_IP", "HOST_IPS", "SSH_USER", "REPO_DIR"):
        assert key in values, f"{key} is not in the config block"
    # The deploy logic starts after the config block, not inside it.
    assert "compute_host_code_id()" in "".join(rest)


def test_the_merge_keeps_the_nodes_fleet_targets(installer, repo_script_text):
    node_text = _node_copy(repo_script_text)
    merged = installer.merge_config(repo_script_text, node_text)

    _, merged_config, _ = installer.split_script(merged)
    values = installer.config_values(merged_config)
    # The node's fleet becomes the DEFAULT of the repo's env-driven line: the node keeps its own
    # targets, and the environment can still point a deploy somewhere else.
    assert values["SERVER_IP"] == 'SERVER_IP="${SERVER_IP:-10.99.0.1,fake-alpha}"'
    assert values["HOST_IPS"] == 'HOST_IPS="${HOST_IPS:-fake-host-a,fake-host-b}"'
    assert values["DOCKER_IPS"] == 'DOCKER_IPS="${DOCKER_IPS:-fake-docker}"'


def test_the_merge_leaves_a_key_the_node_does_not_set_alone(installer, repo_script_text):
    node_text = _node_copy(repo_script_text).replace('DOCKER_IPS="fake-docker"\n', "")
    merged = installer.merge_config(repo_script_text, node_text)

    _, merged_config, _ = installer.split_script(merged)
    values = installer.config_values(merged_config)
    assert values["DOCKER_IPS"] == 'DOCKER_IPS="${DOCKER_IPS:-}"'


def test_a_node_value_equal_to_the_repo_default_leaves_the_line_unchanged(installer, repo_script_text):
    node_text = repo_script_text.replace(
        'SERVER_IP="${SERVER_IP:-192.168.0.103}"', 'SERVER_IP="192.168.0.103"'
    )
    merged = installer.merge_config(repo_script_text, node_text)

    _, merged_config, _ = installer.split_script(merged)
    values = installer.config_values(merged_config)
    assert values["SERVER_IP"] == 'SERVER_IP="${SERVER_IP:-192.168.0.103}"'


def test_a_node_line_that_is_not_a_plain_value_is_kept_verbatim(installer, repo_script_text):
    """An expansion is not a value that can be moved into "${KEY:-...}": the node's line stays."""
    node_text = repo_script_text.replace(
        'SERVER_IP="${SERVER_IP:-192.168.0.103}"', 'SERVER_IP="$SOME_OTHER_VAR"'
    )
    merged = installer.merge_config(repo_script_text, node_text)

    _, merged_config, _ = installer.split_script(merged)
    values = installer.config_values(merged_config)
    assert values["SERVER_IP"] == 'SERVER_IP="$SOME_OTHER_VAR"'


def test_merging_an_already_merged_copy_changes_nothing(installer, repo_script_text):
    """A node whose copy was installed before is already env-driven: installing again is a no-op."""
    merged_once = installer.merge_config(repo_script_text, _node_copy(repo_script_text))
    merged_twice = installer.merge_config(repo_script_text, merged_once)
    assert merged_twice == merged_once


def test_the_merge_takes_the_deploy_logic_from_the_repo(installer, repo_script_text):
    node_text = _node_copy(repo_script_text)
    # The node's copy is stale: it still computes the code id before the pull.
    node_text = node_text.replace(
        "\ncompute_host_code_id\ncompute_server_code_id\n",
        "",
    )
    merged = installer.merge_config(repo_script_text, node_text)

    pull = merged.find('git reset --hard "origin/')
    compute = merged.find("\ncompute_host_code_id\n", pull)
    assert compute > pull, "the merged script computes the code id before the pull"


def test_the_merge_keeps_a_config_key_only_the_node_knows(installer, repo_script_text):
    node_text = _node_copy(repo_script_text).replace(
        'SSH_USER="${SSH_USER:-$(id -un)}"',
        'SSH_USER="jndoye"',
    )
    merged = installer.merge_config(repo_script_text, node_text)
    _, merged_config, _ = installer.split_script(merged)
    values = installer.config_values(merged_config)
    # The node's whole line is kept - value and its trailing comment.
    assert values["SSH_USER"].startswith('SSH_USER="jndoye"')
    assert "${SSH_USER:-" not in values["SSH_USER"]


def test_the_merge_keeps_a_config_key_only_the_repo_knows(installer, repo_script_text):
    node_text = _node_copy(repo_script_text).replace('DOCKER_DIR="${DOCKER_DIR:-/x}"\n', "")
    if "DOCKER_DIR" not in node_text:
        pytest.skip("the repo script has no DOCKER_DIR config key")
    merged = installer.merge_config(repo_script_text, node_text)
    _, merged_config, _ = installer.split_script(merged)
    assert "DOCKER_DIR" in installer.config_values(merged_config)


def test_a_config_only_difference_is_no_logic_drift(installer, repo_script_text):
    node_text = _node_copy(repo_script_text)
    assert installer.logic_diff(repo_script_text, node_text) == "", (
        "a difference in the fleet targets only must not count as logic drift"
    )


def test_a_stale_node_copy_shows_logic_drift(installer, repo_script_text):
    node_text = _node_copy(repo_script_text).replace(
        "\ncompute_host_code_id\ncompute_server_code_id\n",
        "",
    )
    drift = installer.logic_diff(repo_script_text, node_text)
    assert "compute_host_code_id" in drift


def test_the_merged_script_is_valid_bash(installer, repo_script_text, tmp_path):
    node_text = _node_copy(repo_script_text)
    merged = installer.merge_config(repo_script_text, node_text)
    target = tmp_path / "update_core.sh"
    target.write_text(merged, encoding="utf-8")
    out = subprocess.run(["bash", "-n", str(target)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_the_installer_never_scp_over_the_node_config(installer, repo_script_text):
    """The merged script must not carry the template's default fleet targets."""
    node_text = _node_copy(repo_script_text)
    merged = installer.merge_config(repo_script_text, node_text)
    _, merged_config, _ = installer.split_script(merged)
    values = installer.config_values(merged_config)
    assert "192.168.0.109,192.168.0.110" not in values["HOST_IPS"]
    assert "192.168.0.103" not in values["SERVER_IP"]
