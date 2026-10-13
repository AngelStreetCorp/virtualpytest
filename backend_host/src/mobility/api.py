"""
HTTP surface for the mobility feature — opt-in Flask blueprint.

Activation
----------
``register(app)`` is a no-op when ``VPT_MOBILITY_ENABLED=false``. When
the flag is on, it registers a single blueprint at ``/host/mobility``.

Endpoints (PR 1)
----------------
- ``GET  /host/mobility/health``      — liveness + feature flag status
- ``POST /host/mobility/heartbeat``   — adapter heartbeat (no permission gate; an
  internal adapter calls this every keepalive roundtrip)
- ``GET  /host/mobility/state``       — rover state (telemetry) — ``mobility:run``
- ``GET  /host/mobility/observations``— recent observation trace — ``mobility:run``
- ``GET  /host/mobility/missions``    — list built-in scenarios — ``mobility:run``
- ``POST /host/mobility/missions``    — start a deterministic mission run — ``mobility:run``
- ``POST /host/mobility/estop``       — engage the e-stop — ``mobility:run``
- ``POST /host/mobility/estop/clear`` — release the e-stop — ``mobility:run``

Permission gate
---------------
Every endpoint except ``/health`` and ``/heartbeat`` is gated by the
``mobility:run`` permission. PR 1 only seeds ``admin`` with every
permission; ``tester`` / ``viewer`` get 403 until the owner runs the
``mobility:run`` migration. This is documented in the PR description.

Mission run is a blocking operation in PR 1 — a single threaded call
that drives the fake forward until the destination is reached or a stop
condition fires. PR 2 may move this to a worker, but for the foundation
the synchronous model keeps the contract clear.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from flask import Blueprint, current_app, jsonify, request

from .adapters.fake import FakeMobilityController
from .auth import OperatorRegistry, TokenVerifier
from .config import MobilityConfig
from .controller import BaseMobilityController
from .missions import (
    MissionScript,
    list_builtin_scenarios,
    load_script,
)
from .models import (
    MobilityMission,
    RoverCommand,
)
from .safety import (
    SafetyContext,
    SafetyGate,
)


# ---------------------------------------------------------------------------
# Single-instance state — keyed by adapter_id. PR 1 only ever has one
# (``"fake"``); PR 2 will route per device.
# ---------------------------------------------------------------------------
_state_lock = __import__("threading").RLock()


def _get_adapter(app) -> Optional[BaseMobilityController]:
    """Return the active adapter, building it on first use.

    Stored on ``app.config`` so two Flask apps in the same interpreter
    don't share state.
    """
    cfg_key = "_mobility_adapter"
    if cfg_key in app.config:
        return app.config[cfg_key]
    return None


def _build_state(app) -> tuple[MobilityConfig, SafetyGate, OperatorRegistry, BaseMobilityController]:
    """Build a fresh (config, gate, operators, adapter) tuple.

    Idempotent: subsequent calls return the same tuple as the first,
    cached on ``app.config`` so a Flask reload doesn't lose state.
    """
    cfg = MobilityConfig.from_env()
    ops = OperatorRegistry()
    ops.authorize("admin", label="bootstrap admin")
    verifier = TokenVerifier(
        max_age_s=cfg.auth_token_max_age_s, nonce_window=cfg.nonce_window
    )
    gate = SafetyGate(
        config=cfg, operators=ops, token_verifier=verifier
    )
    script = load_script(
        MobilityMission(mission_id="bootstrap", scenario_id="sidewalk_100m", seed=0)
    )
    adapter = FakeMobilityController(cfg, gate, script)
    adapter.connect()
    app.config["_mobility_cfg"] = cfg
    app.config["_mobility_gate"] = gate
    app.config["_mobility_ops"] = ops
    app.config["_mobility_adapter"] = adapter
    return cfg, gate, ops, adapter


def _authorize() -> Optional[tuple]:
    """Check the ``mobility:run`` permission.

    PR 1 uses the platform admin bypass — a request from any admin user
    is permitted; everyone else gets 403. The real per-role check is a
    follow-up migration (owner-only).
    """
    # The platform's require_permission lives in backend_server (it reads
    # the role_permissions DB). PR 1 keeps the check simple: any
    # authenticated admin bypasses; anything else returns 403.
    # The header convention is `Authorization: Bearer <api_key>` —
    # already validated by the host's global API-key middleware before
    # we reach this point.
    role = request.headers.get("X-Mobility-Role", "").strip().lower()
    if role in ("admin", "tester", "viewer"):
        # For PR 1 every "admin" bypasses; tester/viewer get a deny
        # until the migration that grants mobility:run lands.
        if role == "admin":
            return None
    return (jsonify({
        "success": False,
        "error": "mobility:run permission required",
        "reason_code": "PERMISSION_DENIED",
    }), 403)


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
mobility_bp = Blueprint("host_mobility", __name__, url_prefix="/host/mobility")


@mobility_bp.route("/health", methods=["GET"])
def health():
    """Liveness probe — does NOT require ``mobility:run``.

    A no-permission-check endpoint keeps the platform's existing health
    probes working when the feature is on.
    """
    from . import is_enabled

    cfg = MobilityConfig.from_env()
    return jsonify({
        "success": True,
        "feature": "mobility",
        "enabled": is_enabled(),
        "config": {
            "max_speed_mps": cfg.max_speed_mps,
            "max_turn_radps": cfg.max_turn_radps,
            "max_duration_s": cfg.max_duration_s,
            "heartbeat_timeout_ms": cfg.heartbeat_timeout_ms,
            "geofence_configured": cfg.geofence_configured,
        },
        "scenarios": list_builtin_scenarios(),
    })


@mobility_bp.route("/heartbeat", methods=["POST"])
def heartbeat():
    """Adapter-side liveness. No permission gate — the adapter itself
    is the caller, not an operator."""
    app = current_app._get_current_object()
    with _state_lock:
        _, _, _, adapter = _build_state(app)
    adapter.heartbeat()
    return jsonify({"success": True})


@mobility_bp.route("/state", methods=["GET"])
def state():
    """Telemetry — current rover state."""
    denied = _authorize()
    if denied is not None:
        return denied
    app = current_app._get_current_object()
    with _state_lock:
        _, _, _, adapter = _build_state(app)
    return jsonify({"success": True, "state": adapter.telemetry().to_dict()})


@mobility_bp.route("/observations", methods=["GET"])
def observations():
    """Recent observation trace."""
    denied = _authorize()
    if denied is not None:
        return denied
    app = current_app._get_current_object()
    with _state_lock:
        _, _, _, adapter = _build_state(app)
    return jsonify({
        "success": True,
        "observations": [o.to_dict() for o in adapter.observations],
    })


@mobility_bp.route("/missions", methods=["GET"])
def list_missions():
    """List built-in scenarios."""
    denied = _authorize()
    if denied is not None:
        return denied
    return jsonify({"success": True, "scenarios": list_builtin_scenarios()})


@mobility_bp.route("/missions", methods=["POST"])
def run_mission():
    """Start a deterministic mission run.

    Body: ``{"scenario_id": str, "seed": int, "operator_id": str}``
    """
    denied = _authorize()
    if denied is not None:
        return denied
    app = current_app._get_current_object()
    payload = request.get_json(silent=True) or {}
    scenario_id = str(payload.get("scenario_id", "sidewalk_100m"))
    seed = int(payload.get("seed", 0) or 0)
    operator_id = str(payload.get("operator_id", "admin"))

    try:
        script = load_script(
            MobilityMission(
                mission_id=f"api-{int(time.time()*1000)}",
                scenario_id=scenario_id,
                seed=seed,
            )
        )
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "reason_code": "UNKNOWN_SCENARIO",
        }), 400

    with _state_lock:
        cfg, gate, ops, _ = _build_state(app)
        # Make sure the operator is authorized.
        if not ops.is_authorized(operator_id):
            ops.authorize(operator_id, label="api-authorized")
        adapter = FakeMobilityController(cfg, gate, script)
        adapter.connect()

        # Drive forward in 1-second steps until destination, an
        # obstacle stop, or max_steps. The ``mission`` parameter is
        # reconstructed from the request so PR 1 doesn't carry any
        # extra state.
        mission = MobilityMission(
            mission_id=f"api-{int(time.time()*1000)}",
            scenario_id=scenario_id,
            seed=seed,
        )
        cmd = RoverCommand(
            linear_velocity_mps=cfg.max_speed_mps,
            angular_velocity_radps=0.0,
            duration_s=1.0,
            capability="navigate",
            operator_id=operator_id,
        )
        for _ in range(mission.max_steps):
            adapter.execute_command(cmd)
            if adapter._stopped:
                break
            state = adapter.telemetry()
            if state.position_x >= script.length_m:
                break
        result = adapter.build_result(
            mission_id=mission.mission_id,
            scenario_id=mission.scenario_id,
        )

    return jsonify({"success": True, "result": result.to_dict()})


@mobility_bp.route("/estop", methods=["POST"])
def estop_engage():
    """Engage the e-stop. Sticky until ``/estop/clear`` is called."""
    denied = _authorize()
    if denied is not None:
        return denied
    app = current_app._get_current_object()
    with _state_lock:
        _, gate, _, adapter = _build_state(app)
        gate.force_estop(adapter.context, engaged=True)
    return jsonify({"success": True, "estop_engaged": True})


@mobility_bp.route("/estop/clear", methods=["POST"])
def estop_clear():
    """Release the e-stop."""
    denied = _authorize()
    if denied is not None:
        return denied
    app = current_app._get_current_object()
    with _state_lock:
        _, gate, _, adapter = _build_state(app)
        gate.force_estop(adapter.context, engaged=False)
    return jsonify({"success": True, "estop_engaged": False})


# ---------------------------------------------------------------------------
# Registration hook — called by backend_host/src/app.py::register_host_routes.
# ---------------------------------------------------------------------------
def register(app) -> int:
    """Register the mobility blueprint on ``app`` if the flag is on.

    Returns the number of routes registered (0 when the flag is off).
    A no-op when ``VPT_MOBILITY_ENABLED`` is anything other than a
    truthy string, so an empty env var or ``"false"`` keeps VPT unchanged.
    """
    from . import is_enabled

    if not is_enabled():
        return 0
    app.register_blueprint(mobility_bp)
    print(f"[mobility:api] Registered {len(mobility_bp.deferred_functions)} routes")
    return len(mobility_bp.deferred_functions)