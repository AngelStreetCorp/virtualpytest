"""
API registration tests — opt-in flag behaviour + per-route gates.

These tests pin the acceptance criteria:

- ``VPT_MOBILITY_ENABLED=false`` → ``register(app)`` is a no-op (no blueprint
  added, no routes).
- ``VPT_MOBILITY_ENABLED=true`` → blueprint added; ``/host/mobility/health``
  returns 200.
- Without ``mobility:run`` (i.e. non-admin ``X-Mobility-Role`` header),
  endpoints return 403.

We construct a Flask app in-process rather than starting a server. The
``register`` hook is the contract; the routes' HTTP-level behaviour is
exercised through Flask's test client.
"""
from __future__ import annotations

import os

import pytest

try:
    from flask import Flask
except ImportError:  # pragma: no cover
    Flask = None  # type: ignore


# Skip the whole module if Flask is unavailable. The host app already
# imports Flask unconditionally, but the test should be explicit.
pytestmark = pytest.mark.skipif(Flask is None, reason="Flask not installed")


@pytest.fixture
def clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("VPT_MOBILITY_") or key == "DISABLED_FEATURES":
            monkeypatch.delenv(key, raising=False)
    yield monkeypatch


# ---------------------------------------------------------------------------
# register(app) is a no-op when the flag is off
# ---------------------------------------------------------------------------


def test_register_is_noop_when_flag_off(clean_env):
    clean_env.setenv("VPT_MOBILITY_ENABLED", "false")
    app = Flask(__name__)
    # Pre-count routes
    initial_routes = sum(1 for _ in app.url_map.iter_rules())
    from backend_host.src.mobility.api import register

    count = register(app)
    final_routes = sum(1 for _ in app.url_map.iter_rules())
    assert count == 0
    assert final_routes == initial_routes


def test_register_is_noop_when_flag_unset(clean_env):
    clean_env.delenv("VPT_MOBILITY_ENABLED", raising=False)
    app = Flask(__name__)
    from backend_host.src.mobility.api import register

    count = register(app)
    assert count == 0


def test_register_registers_blueprint_when_flag_on(clean_env):
    clean_env.setenv("VPT_MOBILITY_ENABLED", "true")
    app = Flask(__name__)
    from backend_host.src.mobility.api import register

    count = register(app)
    assert count > 0
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/host/mobility/health" in rules
    assert "/host/mobility/state" in rules
    assert "/host/mobility/missions" in rules
    assert "/host/mobility/estop" in rules
    assert "/host/mobility/estop/clear" in rules


# ---------------------------------------------------------------------------
# /host/mobility/health — no permission required
# ---------------------------------------------------------------------------


def _make_app(flag: bool):
    app = Flask(__name__)
    if flag:
        os.environ["VPT_MOBILITY_ENABLED"] = "true"
    else:
        os.environ["VPT_MOBILITY_ENABLED"] = "false"
    from backend_host.src.mobility.api import register

    register(app)
    return app


def test_health_endpoint_returns_200(clean_env):
    clean_env.setenv("VPT_MOBILITY_ENABLED", "true")
    app = _make_app(True)
    client = app.test_client()
    resp = client.get("/host/mobility/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["feature"] == "mobility"
    assert body["enabled"] is True
    assert "sidewalk_100m" in body["scenarios"]


def test_health_endpoint_unavailable_when_flag_off(clean_env):
    clean_env.setenv("VPT_MOBILITY_ENABLED", "false")
    app = _make_app(False)
    client = app.test_client()
    resp = client.get("/host/mobility/health")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Permission gate
# ---------------------------------------------------------------------------


def test_state_endpoint_rejects_non_admin(clean_env):
    clean_env.setenv("VPT_MOBILITY_ENABLED", "true")
    app = _make_app(True)
    client = app.test_client()
    resp = client.get(
        "/host/mobility/state",
        headers={"X-Mobility-Role": "tester"},
    )
    assert resp.status_code == 403
    body = resp.get_json()
    assert body["reason_code"] == "PERMISSION_DENIED"


def test_state_endpoint_allows_admin(clean_env):
    clean_env.setenv("VPT_MOBILITY_ENABLED", "true")
    app = _make_app(True)
    client = app.test_client()
    resp = client.get(
        "/host/mobility/state",
        headers={"X-Mobility-Role": "admin"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert "state" in body


def test_run_mission_endpoint_allows_admin(clean_env):
    clean_env.setenv("VPT_MOBILITY_ENABLED", "true")
    app = _make_app(True)
    client = app.test_client()
    resp = client.post(
        "/host/mobility/missions",
        json={"scenario_id": "sidewalk_100m", "seed": 0, "operator_id": "admin"},
        headers={"X-Mobility-Role": "admin"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["result"]["status"] in ("pass", "fail", "needs_review")


def test_run_mission_endpoint_rejects_unknown_scenario(clean_env):
    clean_env.setenv("VPT_MOBILITY_ENABLED", "true")
    app = _make_app(True)
    client = app.test_client()
    resp = client.post(
        "/host/mobility/missions",
        json={"scenario_id": "does_not_exist"},
        headers={"X-Mobility-Role": "admin"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["reason_code"] == "UNKNOWN_SCENARIO"


def test_estop_endpoint_round_trip(clean_env):
    clean_env.setenv("VPT_MOBILITY_ENABLED", "true")
    app = _make_app(True)
    client = app.test_client()
    headers = {"X-Mobility-Role": "admin"}
    # Engage
    resp = client.post("/host/mobility/estop", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["estop_engaged"] is True
    # Clear
    resp = client.post("/host/mobility/estop/clear", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["estop_engaged"] is False


# ---------------------------------------------------------------------------
# is_enabled / package surface
# ---------------------------------------------------------------------------


def test_is_enabled_observes_flag(clean_env):
    from backend_host.src.mobility import is_enabled

    clean_env.delenv("VPT_MOBILITY_ENABLED", raising=False)
    assert is_enabled() is False
    clean_env.setenv("VPT_MOBILITY_ENABLED", "yes")
    assert is_enabled() is True
    clean_env.setenv("VPT_MOBILITY_ENABLED", "false")
    assert is_enabled() is False


# ---------------------------------------------------------------------------
# Lazy import — no ROS 2 / Gazebo pulled in
# ---------------------------------------------------------------------------


def test_importing_api_does_not_import_heavy_deps():
    import sys

    forbidden = ["rclpy", "rospy", "gazebo", "geometry_msgs", "tf2_ros"]
    leaked = [m for m in forbidden if m in sys.modules]
    assert leaked == []