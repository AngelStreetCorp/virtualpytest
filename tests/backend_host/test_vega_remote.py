"""Unit tests for VegaRemoteController. No device, no adb binary required."""

from __future__ import annotations

import base64
from typing import Any, List, Tuple

import pytest

from backend_host.src.controllers.remote.vega import (
    SHELL_MAX_ATTEMPTS,
    SHELL_SERVICE_ERROR,
    VegaRemoteController,
)


# 8-byte PNG signature + filler.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

# Real-world `vlcm list` output captured on a Vega Fire TV.
VLCM_LIST_SAMPLE = (
    "application                                      type      pid     "
    "id      state       lifespan       timeout container                               "
    "launch args\n"
    "com.amazon.kcp.component.service                 S         1732    "
    "2       READY       PERMANENT      n/a     framework.slice/essential/1732          "
    "<none>\n"
    "tv.arte.plus7.main                               I         9767    "
    "153     VISIBLE     PERMANENT      n/a     framework.slice/essential/9767          "
    "<none>\n"
)

VPM_INFO_SAMPLE = (
    "package: com.amazon.kcp.component.service\n"
    "version: 1.0.0\n"
    "lib path:     /var/lib/pkgmgrd/packages/kepler-package-main/lib/armv7\n"
)

VPM_LIST_SAMPLE = (
    "category: com.amazon.category.main\n"
    "component ids:\n"
    "\tcom.amazon.kcp.component.service\n"
    "\ttv.arte.plus7.main\n"
    "\tcom.netflix.kepler.main\n"
)


class AdbFake:
    """Records every ``_adb`` call and serves preloaded responses."""

    def __init__(self) -> None:
        self.shell_queue: List[Tuple[int, Any, str]] = []
        self.other_queue: List[Tuple[int, Any, str]] = []
        self.exec_out_bytes: bytes = PNG_BYTES
        self.calls: List[Tuple[str, tuple]] = []
        self.sleep_calls: List[float] = []

    def adb(
        self, args: List[str], timeout: int = 20, binary: bool = False
    ) -> Tuple[int, Any, str]:
        self.calls.append(("adb", tuple(args)))
        if args and args[0] == "shell":
            if self.shell_queue:
                return self.shell_queue.pop(0)
            return (0, "", "")
        if args and args[0] == "devices":
            return (
                0,
                "List of devices attached\nfake-target\tdevice\n",
                "",
            )
        if args and args[0] == "exec-out":
            return (0, self.exec_out_bytes, "")
        if self.other_queue:
            return self.other_queue.pop(0)
        return (0, "", "")

    def connect(self) -> Tuple[int, str, str]:
        self.calls.append(("connect", ()))
        return (0, "connected to fake-target\n", "")

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)


@pytest.fixture
def vega(monkeypatch: pytest.MonkeyPatch):
    fake = AdbFake()
    # Response served to the connect-time `echo vega-ok` probe.
    fake.shell_queue.append((0, "vega-ok\n", ""))
    monkeypatch.setattr(
        VegaRemoteController,
        "_adb",
        lambda self, args, timeout=20, binary=False: fake.adb(args, timeout, binary),
    )
    monkeypatch.setattr(
        VegaRemoteController, "_run_adb_connect", lambda self: fake.connect()
    )
    monkeypatch.setattr(
        VegaRemoteController,
        "_retry_sleep",
        lambda self, seconds: fake.sleep(seconds),
    )
    ctrl = VegaRemoteController(adb_serial="fake-target")
    return ctrl, fake


def _shell_calls(fake: AdbFake):
    return [
        c for c in fake.calls
        if c[0] == "adb" and c[1] and c[1][0] == "shell"
    ]


# ------------------------------------------------------------- key map --


def test_press_key_ok_maps_to_key_enter(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, "Injecting Button Press: KEY_ENTER\n", ""))
    assert ctrl.press_key("OK") is True
    args = _shell_calls(fake)[-1][1]
    assert args == ("shell", "inputd-cli button_press KEY_ENTER")


def test_press_key_home_maps_to_key_homepage_not_key_home(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, "Injecting Button Press: KEY_HOMEPAGE\n", ""))
    assert ctrl.press_key("HOME") is True
    args = _shell_calls(fake)[-1][1]
    assert args == ("shell", "inputd-cli button_press KEY_HOMEPAGE")
    assert "KEY_HOME " not in " ".join(args)


def test_press_key_lowercase_is_accepted(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, "Injecting Button Press: KEY_UP\n", ""))
    assert ctrl.press_key("up") is True
    args = _shell_calls(fake)[-1][1]
    assert args == ("shell", "inputd-cli button_press KEY_UP")


def test_press_key_key_prefix_is_passthrough(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, "Injecting Button Press: KEY_FOO\n", ""))
    assert ctrl.press_key("KEY_FOO") is True
    args = _shell_calls(fake)[-1][1]
    assert args == ("shell", "inputd-cli button_press KEY_FOO")


def test_press_key_unknown_returns_false_without_shell_call(vega):
    ctrl, fake = vega
    before = len(_shell_calls(fake))
    assert ctrl.press_key("NOPE") is False
    assert len(_shell_calls(fake)) == before
    assert "NOPE" in (ctrl.last_error or "")


def test_press_key_invalid_button_value_is_treated_as_failure(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, "invalid button value\n", ""))
    assert ctrl.press_key("OK") is False
    assert "invalid button value" in (ctrl.last_error or "")


def test_press_key_retries_on_dev_shell_service_error_then_succeeds(vega):
    ctrl, fake = vega
    fake.shell_queue.append((1, f"{SHELL_SERVICE_ERROR}\n", ""))
    fake.shell_queue.append((1, f"{SHELL_SERVICE_ERROR}\n", ""))
    fake.shell_queue.append((0, "Injecting Button Press: KEY_ENTER\n", ""))
    assert ctrl.press_key("OK") is True
    # 3 attempts go to inputd-cli; the connect-time `echo vega-ok` is unrelated.
    inputd_calls = [
        c for c in _shell_calls(fake)
        if c[1][1].startswith("inputd-cli button_press")
    ]
    assert len(inputd_calls) == SHELL_MAX_ATTEMPTS
    assert len(fake.sleep_calls) == SHELL_MAX_ATTEMPTS - 1


# ----------------------------------------------------------------- apps --


def test_launch_app_builds_orpheus_uri(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, "Sending: orpheus://x.main\n", ""))
    assert ctrl.launch_app("x.main") is True
    args = _shell_calls(fake)[-1][1]
    assert args == ("shell", "vmsgr send orpheus://x.main")


def test_close_app_resolves_package_id_from_vpm_info(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, VPM_INFO_SAMPLE, ""))
    fake.shell_queue.append((0, "", ""))
    assert ctrl.close_app("com.amazon.kcp.component.service") is True
    calls = _shell_calls(fake)
    assert calls[-2][1] == ("shell", "vpm info com.amazon.kcp.component.service")
    assert calls[-1][1] == (
        "shell",
        "vlcm terminate-app --pkg-id kepler-package-main --force",
    )


def test_close_app_finds_package_of_a_js_app_with_empty_lib_path(vega):
    ctrl, fake = vega
    # Real `vpm info tv.arte.plus7.main`: a JS app has no lib path.
    fake.shell_queue.append((0, "lib path:     \nassets path:  /var/lib/pkgmgrd/packages/tv.arte.plus7/assets\n"
                                "data path:    /home/app_user/packages/tv.arte.plus7/data\n", ""))
    fake.shell_queue.append((0, "Force stopping pkg: tv.arte.plus7\n", ""))
    assert ctrl.close_app("tv.arte.plus7.main") is True
    assert _shell_calls(fake)[-1][1] == ("shell", "vlcm terminate-app --pkg-id tv.arte.plus7 --force")


def test_close_app_uses_arg_as_package_id_when_vpm_info_has_no_packages_path(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, "", ""))  # vpm info: empty / no lib path:
    fake.shell_queue.append((0, "", ""))  # vlcm terminate-app
    assert ctrl.close_app("my-pkg-id") is True
    calls = _shell_calls(fake)
    assert calls[-1][1] == (
        "shell",
        "vlcm terminate-app --pkg-id my-pkg-id --force",
    )


def test_get_installed_apps_parses_tab_indented_component_ids(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, VPM_LIST_SAMPLE, ""))
    apps = ctrl.get_installed_apps()
    # /host/remote/getApps reads .package_name / .label, as from AndroidApp.
    assert [(a.package_name, a.label) for a in apps] == [
        ("com.amazon.kcp.component.service", "com.amazon.kcp.component.service"),
        ("tv.arte.plus7.main", "tv.arte.plus7.main"),
        ("com.netflix.kepler.main", "com.netflix.kepler.main"),
    ]


def test_press_key_fails_when_dev_shell_error_outlives_retries(vega):
    ctrl, fake = vega
    for _ in range(SHELL_MAX_ATTEMPTS):
        fake.shell_queue.append((0, f"{SHELL_SERVICE_ERROR}\n", ""))
    assert ctrl.press_key("OK") is False
    assert SHELL_SERVICE_ERROR in (ctrl.last_error or "")


def test_press_key_accepts_android_tv_dpad_names(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, "Injecting Button Press As Driver: KEY_UP State: short\n", ""))
    assert ctrl.press_key("DPAD_UP") is True
    assert _shell_calls(fake)[-1][1] == ("shell", "inputd-cli button_press KEY_UP")


def test_execute_command_drives_its_own_instance(monkeypatch):
    """Two Vega devices on one host: each execute_command must reach its own target."""
    targets = []

    def fake_adb(self, args, timeout=20, binary=False):
        targets.append((self.target, tuple(args)))
        if args[1].startswith("echo"):
            return (0, "vega-ok\n", "")
        return (0, "Injecting Button Press As Driver: KEY_UP State: short\n", "")

    monkeypatch.setattr(VegaRemoteController, "_adb", fake_adb)
    first = VegaRemoteController(adb_serial="first")
    second = VegaRemoteController(adb_serial="second")
    first.execute_command("press_key", {"key": "UP"})
    assert second.execute_command("press_key", {"key": "UP"})["success"] is True
    assert targets[-1][0] == "second"


def test_get_foreground_app_reads_vlcm_list(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, VLCM_LIST_SAMPLE, ""))
    assert ctrl.get_foreground_app() == "tv.arte.plus7.main"


# ----------------------------------------------------------- screenshot --


def test_take_screenshot_returns_base64_of_png_bytes(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, "", ""))  # gwsi-tool-screenshooter success
    ok, data, err = ctrl.take_screenshot()
    assert ok is True
    assert err == ""
    assert base64.b64decode(data) == PNG_BYTES


# ------------------------------------------------------- execute_command --


def test_execute_command_unknown_command_returns_error(vega):
    ctrl, _ = vega
    result = ctrl.execute_command("dance")
    assert result["success"] is False
    assert "Invalid command" in result["error"]
    assert "dance" in result["error"]
    assert "Valid commands" in result["error"]


def test_execute_command_take_screenshot_returns_screenshot_key(vega):
    ctrl, fake = vega
    fake.shell_queue.append((0, "", ""))  # screenshooter
    result = ctrl.execute_command("take_screenshot")
    assert result["success"] is True
    assert base64.b64decode(result["screenshot"]) == PNG_BYTES
    assert result["error"] == ""


def test_execute_command_get_pairing_status_returns_health(vega):
    ctrl, fake = vega
    # `get_health()` re-probes with `echo vega-ok`; serve that response too.
    fake.shell_queue.append((0, "vega-ok\n", ""))
    result = ctrl.execute_command("get_pairing_status")
    assert result["success"] is True
    assert "status" in result
    health = result["status"]
    assert health["device_present"] is True
    assert health["tx_probe_ok"] is True
    assert "detail" in health