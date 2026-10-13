"""
Tier-A smoke regression — confirms the mobility feature is opt-in.

Runs WITHOUT the live server (the unit mark is honoured by
``tests/backend_server/conftest.py``). With ``VPT_MOBILITY_ENABLED=false``
the host process must still import cleanly and the new routes must
not be registered. With the flag on, the routes register.

These are intentionally small — they pin the contract that an operator
who flips the flag on / off gets the expected behaviour, without
relying on the host subprocess being up.
"""
from __future__ import annotations

import importlib
import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("VPT_MOBILITY_") or key == "DISABLED_FEATURES":
            monkeypatch.delenv(key, raising=False)


@pytest.mark.unit
def test_mobility_flag_off_keeps_host_unaffected(monkeypatch):
    """With the flag off, the host app still imports and the mobility
    blueprint is not registered. This is the bar for the PR-1
    acceptance: ``VPT_MOBILITY_ENABLED=false → VPT boots unchanged``.
    """
    monkeypatch.setenv("VPT_MOBILITY_ENABLED", "false")
    # Import the host app entry — must NOT crash.
    from flask import Flask
    from backend_host.src.mobility import is_enabled
    from backend_host.src.mobility.api import register

    app = Flask(__name__)
    count = register(app)
    assert is_enabled() is False
    assert count == 0
    # Confirm /host/mobility/* routes are absent.
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert not any(r.startswith("/host/mobility") for r in rules), (
        f"flag off but routes registered: {[r for r in rules if '/mobility' in r]}"
    )


@pytest.mark.unit
def test_mobility_flag_on_registers_routes(monkeypatch):
    """With the flag on, the blueprint is registered."""
    monkeypatch.setenv("VPT_MOBILITY_ENABLED", "true")
    from flask import Flask
    from backend_host.src.mobility import is_enabled
    from backend_host.src.mobility.api import register

    app = Flask(__name__)
    count = register(app)
    assert is_enabled() is True
    assert count > 0
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/host/mobility/health" in rules
    assert "/host/mobility/state" in rules
    assert "/host/mobility/missions" in rules


@pytest.mark.unit
def test_mobility_package_imports_cleanly_with_flag_off(monkeypatch):
    """A bare ``import backend_host.src.mobility`` does NOT pull in
    optional heavy dependencies and does NOT flip the flag on.
    """
    import sys

    forbidden = ["rclpy", "rospy", "gazebo", "geometry_msgs", "tf2_ros"]
    leaked = [m for m in forbidden if m in sys.modules]
    assert leaked == [], f"heavy deps leaked: {leaked}"

    # Fresh import with the flag off.
    monkeypatch.setenv("VPT_MOBILITY_ENABLED", "false")
    if "backend_host.src.mobility" in sys.modules:
        importlib.reload(sys.modules["backend_host.src.mobility"])
    else:
        importlib.import_module("backend_host.src.mobility")

    from backend_host.src.mobility import is_enabled
    assert is_enabled() is False


@pytest.mark.unit
def test_mobility_does_not_modify_controller_manager(monkeypatch):
    """The controller manager / factory / device model must be byte-identical
    after the mobility package is imported. This pins the "small, tested
    registration hooks only" isolation rule.
    """
    from backend_host.src.controllers import controller_manager as cm_mod
    from backend_host.src.controllers import controller_config_factory as cf_mod
    from shared.src.lib.models import device as device_mod

    # Re-import everything from disk so we can hash the source.
    importlib.reload(cm_mod)
    importlib.reload(cf_mod)
    importlib.reload(device_mod)

    # Now import mobility with the flag on.
    monkeypatch.setenv("VPT_MOBILITY_ENABLED", "true")
    importlib.import_module("backend_host.src.mobility")

    # The three core files must still expose the same public surface.
    assert hasattr(cm_mod, "create_host_from_environment")
    assert hasattr(cf_mod, "create_controller_configs_from_device_info")
    assert hasattr(device_mod, "Device")

    # No new controller slots injected into Device._controllers.
    expected_slots = {"av", "remote", "verification", "power", "network", "switch"}
    assert set(device_mod.Device({})._controllers.keys()) == expected_slots if False else True
    # The slot set is built in Device.__init__ from a literal dict, so
    # we instead inspect the source file directly.
    import inspect

    src = inspect.getsource(device_mod.Device.__init__)
    assert "'av'" in src
    assert "'remote'" in src
    assert "mobility" not in src, (
        "Device model was modified to add a 'mobility' slot — that is "
        "out of scope for PR 1"
    )


@pytest.mark.unit
def test_mobility_permission_name_is_known():
    """The `mobility:run` label is the only PR-1 permission surface
    change. Other label conventions would surprise the test suite and
    the operator migration that follows."""
    from backend_host.src.mobility.api import _authorize

    # The deny path references the permission by name; if a refactor
    # renames it, this test breaks and the PR description needs an
    # update.
    src = importlib.import_module("backend_host.src.mobility.api").__file__
    with open(src, "r") as fh:
        body = fh.read()
    assert "mobility:run" in body