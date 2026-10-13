"""Backend twin of frontend/src/utils/targetCompatibility.ts: /server/script/execute must
refuse the targets the frontend would never offer. No network."""
from shared.src.lib.utils.script_target_rules_utils import target_incompatibility

HOST_RULES = {"target_type": "host", "host_os": "all", "device_model": "all"}

PI = {
    "host_name": "pi",
    "system_stats": {"platform": "Linux"},
    "devices": [
        {"device_id": "host", "device_model": "host_vnc"},
        {"device_id": "device1", "device_model": "local_video"},
    ],
}
NO_HOST_TARGET = {
    "host_name": "box",
    "system_stats": {"platform": "Linux"},
    "devices": [{"device_id": "device1", "device_model": "rtsp_video"}],
}


def test_host_script_on_host_target_is_allowed():
    assert target_incompatibility(HOST_RULES, PI, "host") == ""


def test_host_script_on_a_device_is_refused():
    assert "host target only" in target_incompatibility(HOST_RULES, PI, "device1")


def test_host_script_on_host_without_host_target_is_refused():
    assert "no host target" in target_incompatibility(HOST_RULES, NO_HOST_TARGET, "host")


def test_device_script_on_host_target_is_refused():
    rules = {"target_type": "device", "device_model": "all"}
    assert "runs on a device" in target_incompatibility(rules, PI, "host")


def test_device_model_rule_and_unknown_device():
    rules = {"target_type": "device", "device_model": "android_tv"}
    assert "requires device model" in target_incompatibility(rules, PI, "device1")
    assert "not found" in target_incompatibility({"target_type": "device"}, PI, "device9")
    assert target_incompatibility({"target_type": "device", "device_model": "local_video|android_tv"}, PI, "device1") == ""


def test_target_type_all_accepts_both():
    rules = {"target_type": "all"}
    assert target_incompatibility(rules, PI, "host") == ""
    assert target_incompatibility(rules, PI, "device1") == ""


def test_host_os_rule():
    rules = {"target_type": "host", "host_os": "windows"}
    assert "requires a windows host" in target_incompatibility(rules, PI, "host")
    assert target_incompatibility({"target_type": "host", "host_os": "linux"}, PI, "host") == ""
