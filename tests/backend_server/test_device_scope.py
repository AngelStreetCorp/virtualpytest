"""BUG-0914: the devices an agent may act on in a turn. Pure unit tests, the incident replayed first."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend_server" / "src"))

try:
    from agent import device_scope as scope
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"agent runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit

PHONE = {"host_name": "host-clone-1", "device_id": "device2", "device_name": "Phone slot 1", "device_model": "phone_agent"}
DRONE = {"host_name": "host-clone-1", "device_id": "device5", "device_name": "Tello via phone", "device_model": "tello"}
DESKTOP = {"host_name": "host-clone-1", "device_id": "host", "device_name": "host-clone-1", "device_model": "host_vnc"}
ALL = [PHONE, DRONE, DESKTOP]


def ctx(devices, selected=("", ""), named=()):
    return {"available_devices": devices, "host_name": selected[0], "device_id": selected[1],
            "named_devices": [{"device_name": n} for n in named]}


# ---------------------------------------------------------------- the 2026-10-25 incident, replayed

def test_cap_5_cannot_take_the_drone_outside_the_page():
    """The page had only the phone; the model took control of the drone."""
    reason = scope.refusal("take_control", {"host_name": "host-clone-1", "device_id": "device5"}, ctx([PHONE]), "cap 5")
    assert reason and "not one of the devices of this chat" in reason


def test_cap_5_cannot_rotate_the_drone_even_when_listed():
    reason = scope.refusal("execute_device_action",
                           {"host_name": "host-clone-1", "device_id": "device5",
                            "actions": [{"command": "rotate", "params": {"deg": "30"}}]}, ctx(ALL), "cap 5")
    assert reason and "drone" in reason


def test_cap_5_cannot_drive_a_host_desktop():
    reason = scope.refusal("take_control", {"host_name": "labox-web", "device_id": "host"}, ctx(ALL), "cap 5")
    assert reason and "shared host" in reason


def test_cap_5_cannot_run_bash():
    reason = scope.refusal("execute_device_action",
                           {"host_name": "host-clone-1", "device_id": "device2",
                            "actions": [{"command": "execute_bash_command", "params": {"command": "curl …"}}]},
                           ctx(ALL), "cap 5")
    assert reason and "shell commands" in reason


# ---------------------------------------------------------------- what still works

def test_a_named_device_is_allowed():
    assert scope.refusal("execute_device_action", {"host_name": "host-clone-1", "device_id": "device2",
                                                   "actions": [{"command": "press_key"}]},
                         ctx(ALL), "press home on Phone slot 1") is None


def test_the_selected_target_is_allowed():
    assert scope.refusal("take_control", {"host_name": "host-clone-1", "device_id": "device2"},
                         ctx(ALL, selected=("host-clone-1", "device2")), "take control") is None


def test_the_drone_when_the_user_asks_for_it():
    assert scope.refusal("takeoff", {"host_name": "host-clone-1", "device_id": "device5"}, ctx(ALL), "take off the drone") is None
    assert scope.refusal("rotate", {"host_name": "host-clone-1", "device_id": "device5"}, ctx(ALL), "rotate Tello via phone") is None


def test_a_host_desktop_when_the_user_names_the_host():
    assert scope.refusal("take_control", {"host_name": "host-clone-1", "device_id": "host"}, ctx(ALL),
                         "open google in the browser of host-clone-1") is None


def test_bash_when_the_user_asks_for_a_command():
    assert scope.refusal("execute_device_action",
                         {"host_name": "host-clone-1", "device_id": "host",
                          "actions": [{"command": "execute_bash_command", "params": {"command": "df -h"}}]},
                         ctx(ALL), "run the command df -h on host-clone-1") is None


def test_reads_are_never_gated():
    for tool in ("capture_screenshot", "dump_ui_elements", "list_actions", "get_device_info", "list_hosts"):
        assert scope.refusal(tool, {"host_name": "labox-web", "device_id": "host"}, ctx([PHONE]), "cap 5") is None


def test_no_page_context_keeps_the_old_behaviour_for_ordinary_devices():
    """API callers send no device list: only the drone / desktop / bash rules apply."""
    assert scope.refusal("take_control", {"host_name": "h", "device_id": "device1"}, ctx([]), "take control of stb1") is None


def test_last_user_message():
    assert scope.last_user_message([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]) == "a"
    assert scope.last_user_message([]) == ""
