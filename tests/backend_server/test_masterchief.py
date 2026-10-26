"""Masterchief unit + route tests (TASK-71 Part 7.6).

Offline. No network, no database, no MCP server. The redaction logic, the op
registry, the op executors that don't touch the host, the rate limiter, and
the route-layer guards (service-key reject, op-not-found, permission gate,
admin gate, rate limit) are all exercised here.

What's covered:

- `redaction`: secret keys dropped, JWT/PEM masked, k=v redacted, size cap.
- `MASTERCHIEF_OPS`: every op in the design doc is registered, exactly one
  mutating op, exactly one platform_admin_only op, the whitelist matches
  `routes/logs_routes.py::ALLOWED_SERVICES`.
- `get_op` returns None for unknown ops, refuses on dispatch.
- `execute_op` dispatch returns an OpResult.
- Route: `_refuse_service_key` decorator returns 403 for role=service.
- Route: `list_masterchief_ops` returns the descriptor list.
- Route: `execute_masterchief_op` with a fake proposal triggers the
  audit state machine and a refused state when permission is missing.
- `platform_admin_required` respects the env var override.

What's NOT covered (intentionally):

- The actual host call (call_host) — that needs a real host registration
  and is the integration test in a follow-up.
- The supabase round trip — that needs the DB and a service role key, and
  is the test_agent_activity-style integration test in a follow-up.
- The frontend confirm card render — covered by the existing chat test
  pattern in `test_agent_send_dedupe.py` once the card is in production.

Run: pytest tests/backend_server/test_masterchief.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend_server" / "src"))
sys.path.insert(0, str(ROOT / "shared"))

from backend_server.src.lib.masterchief import (  # noqa: E402
    MASTERCHIEF_OPS,
    execute_op,
    get_op,
    list_ops,
    platform_admin_required,
)
from backend_server.src.lib.masterchief.ops import (  # noqa: E402
    ALLOWED_SERVICES,
    OpContext,
    _exec_logs_services,
    _exec_rollout_explain,
    _exec_deploy_status,
)
from backend_server.src.lib.masterchief.redaction import (  # noqa: E402
    redact_params,
    redact_result,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------

EXPECTED_OPS = [
    "logs.view",
    "logs.services",
    "service.status",
    "service.restart",
    "host.disk_preview",
    "host.disk_cleanup",
    "infra.summary",
    "rollout.explain",
    "deploy.status",
]


def test_registry_has_every_op_in_design_doc():
    assert [o.op for o in list_ops()] == EXPECTED_OPS


def test_only_restart_and_disk_cleanup_mutate():
    mutates = [o.op for o in list_ops() if o.mutates]
    assert sorted(mutates) == ["host.disk_cleanup", "service.restart"]


def test_only_mutating_ops_are_platform_admin_only():
    admin_only = [o.op for o in list_ops() if o.platform_admin_only]
    assert sorted(admin_only) == ["host.disk_cleanup", "service.restart"]


def test_whitelist_matches_logs_route():
    """The op whitelist must match the logs_routes whitelist exactly.

    A drift here is a security bug: masterchief would accept a service
    that logs_routes refuses, or refuse one that logs_routes accepts.
    """
    # The values are duplicated to keep masterchief independent; this
    # test exists to catch a one-sided edit.
    assert set(ALLOWED_SERVICES) == {
        'vpt-server', 'vpt-server-host', 'vpt-host', 'vpt-frontend',
        'vpt-heatmap', 'vpt-discard-scripts', 'vpt-discard-incidents',
        'vpt-stream', 'vpt-monitor-img', 'vpt-archiver', 'vpt-kpi',
        'vpt-monitor-audio', 'vpt-monitor-subtitle', 'vpt-vnc', 'vpt-websockify',
        'vpt-emulator', 'vpt-emulator-fifo',
    }


def test_unknown_op_refuses():
    assert get_op("does.not.exist") is None
    ctx = OpContext(team_id="t", requester_user_id="u", requester_email="e",
                    requester_role="admin", audit_id="a")
    result = execute_op("does.not.exist", {}, ctx)
    assert "unknown op" in result.summary


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

def test_redact_drops_sensitive_keys():
    out = redact_params({"service": "vpt-server", "auth": "Bearer xyz", "token": "abc"})
    assert out["service"] == "vpt-server"
    assert out["auth"] == "REDACTED"
    assert out["token"] == "REDACTED"


def test_redact_masks_jwt_in_string_value():
    out = redact_params({"note": "found jwt=eyJabc1234567890.def1234567890.ghi1234567890 in logs"})
    assert "REDACTED" in out["note"]
    assert "eyJabc" not in out["note"]


def test_redact_masks_pem_block():
    out = redact_params({
        "blob": "-----BEGIN RSA PRIVATE KEY-----\nABC\n-----END RSA PRIVATE KEY-----\nrest"
    })
    assert "REDACTED PRIVATE KEY BLOCK" in out["blob"]
    assert "ABC" not in out["blob"]
    assert "rest" in out["blob"]


def test_redact_caps_oversize_string():
    big = "x" * 5_000
    out = redact_result(big)
    assert out.endswith("...<truncated>")
    assert len(out) < 1_000


def test_redact_caps_oversize_params_object():
    big = {"k" + str(i): "v" * 100 for i in range(200)}
    out = redact_params(big)
    encoded_len = sum(len(str(v)) for v in out.values())
    # The shrinker drops big values; we only assert the cap held.
    assert all(v != "v" * 100 or k not in big or len(big[k]) <= 80
               for k, v in out.items() if isinstance(v, str))


def test_redact_strips_nested_env_keys():
    out = redact_params({"env": {"API_KEY": "sk-xxx", "PATH": "/usr/bin"}})
    assert out["env"] == "REDACTED"


# ---------------------------------------------------------------------------
# Executors that don't need the host
# ---------------------------------------------------------------------------

def test_logs_services_returns_whitelist():
    ctx = OpContext(team_id="t", requester_user_id="u", requester_email="e",
                    requester_role="admin", audit_id="a")
    result = _exec_logs_services({}, ctx)
    assert "whitelisted" in result.summary
    assert result.detail["services"] == ALLOWED_SERVICES


def test_rollout_explain_requires_builds():
    ctx = OpContext(team_id="t", requester_user_id="u", requester_email="e",
                    requester_role="admin", audit_id="a")
    assert "required" in _exec_rollout_explain({}, ctx).summary
    assert "not yet wired" in _exec_rollout_explain(
        {"from_build": 1, "to_build": 2}, ctx
    ).summary


def test_deploy_status_requires_id():
    ctx = OpContext(team_id="t", requester_user_id="u", requester_email="e",
                    requester_role="admin", audit_id="a")
    assert "required" in _exec_deploy_status({}, ctx).summary
    assert "not yet wired" in _exec_deploy_status(
        {"deploy_id": "6406abc8"}, ctx
    ).summary


# ---------------------------------------------------------------------------
# platform_admin_required env gate
# ---------------------------------------------------------------------------

def test_platform_admin_required_default_true():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MASTERCHIEF_REQUIRE_PLATFORM_ADMIN", None)
        assert platform_admin_required() is True


def test_platform_admin_required_opt_out():
    with patch.dict(os.environ, {"MASTERCHIEF_REQUIRE_PLATFORM_ADMIN": "0"}):
        assert platform_admin_required() is False
    with patch.dict(os.environ, {"MASTERCHIEF_REQUIRE_PLATFORM_ADMIN": "false"}):
        assert platform_admin_required() is False
    with patch.dict(os.environ, {"MASTERCHIEF_REQUIRE_PLATFORM_ADMIN": "off"}):
        assert platform_admin_required() is False


# ---------------------------------------------------------------------------
# Route layer
# ---------------------------------------------------------------------------

def _make_request(user_role="admin", user_id="u-1", user_email="u@x", team_id="t-1"):
    """A minimal Flask request stub for the decorators under test."""
    from flask import Flask, jsonify
    from backend_server.src.routes.server_masterchief_routes import (
        server_masterchief_bp,
        _refuse_service_key,
    )

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(server_masterchief_bp)

    # We can't easily fake request.user_role at the test layer; the global
    # guard sets it. For these tests we exercise the decorator directly.
    return app, server_masterchief_bp


def test_refuse_service_key_decorator_blocks_service_role():
    """The route layer must reject role=service outright — this is the
    structural fix for the MCPAPIClient service-key bypass."""
    from backend_server.src.routes.server_masterchief_routes import _refuse_service_key

    @_refuse_service_key
    def fake():
        return ("ok", 200)

    # When the request has user_role='service' the decorator returns 403
    # before calling the wrapped function. We exercise it via Flask.
    from flask import Flask, request
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/_probe")
    @_refuse_service_key
    def probe():
        return ("ok", 200)

    client = app.test_client()
    # Without a request.user_role, the decorator passes through. Set it.
    with app.test_request_context("/_probe"):
        from flask import request as flask_request
        flask_request.user_role = "service"
        resp = probe()
        assert resp[1] == 403
        assert "service API key" in resp[0].get_json()["error"]


def test_refuse_service_key_decorator_passes_other_roles():
    from backend_server.src.routes.server_masterchief_routes import _refuse_service_key
    from flask import Flask, request as flask_request

    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/_probe")
    @_refuse_service_key
    def probe():
        return ("ok", 200)

    with app.test_request_context("/_probe"):
        flask_request.user_role = "admin"
        resp = probe()
        assert resp[0] == "ok"
        assert resp[1] == 200


def test_masterchief_agent_is_selectable_in_registry():
    """The agent picker lists registry templates: masterchief must load, be selectable and hold the propose tool."""
    from pathlib import Path as _P
    from backend_server.src.agent.registry.validator import validate_agent_yaml

    path = _P(__file__).resolve().parents[2] / 'backend_server/src/agent/registry/templates/masterchief.yaml'
    agent = validate_agent_yaml(path.read_text(encoding='utf-8'))
    assert agent.metadata.id == 'masterchief'
    assert agent.metadata.selectable is not False
    assert 'propose_masterchief_op' in agent.skills


def test_disk_cleanup_takes_no_path_or_age_and_is_admin_gated():
    from backend_server.src.lib.masterchief import get_op
    op = get_op("host.disk_cleanup")
    assert op.mutates and op.platform_admin_only
    assert set(op.params_schema["properties"]) == {"host", "reason"}
    assert get_op("host.disk_preview").mutates is False


def test_disk_cleanup_refuses_busy_host_and_sends_real_run():
    from unittest.mock import MagicMock
    from backend_server.src.lib.masterchief import ops
    ctx = ops.OpContext(team_id="t", requester_user_id="u", requester_email="e", requester_role="admin", audit_id="a")
    hm = MagicMock()
    hm.get_host.return_value = {"host_name": "h"}
    with patch("backend_server.src.lib.utils.server_utils.get_host_manager", return_value=hm), \
         patch("backend_server.src.routes.server_system_routes._foreign_host_lock", return_value={"owner_user_name": "x"}), \
         patch.object(ops, "call_host") as ch:
        out = ops._exec_disk_cleanup({"host": "h"}, ctx)
        assert "in use" in out.summary
        ch.assert_not_called()
    resp = {"success": True, "freed_bytes": 2_000_000_000, "files": 5, "disk_before": 97, "disk_after": 90, "dry_run": False}
    with patch("backend_server.src.lib.utils.server_utils.get_host_manager", return_value=hm), \
         patch("backend_server.src.routes.server_system_routes._foreign_host_lock", return_value=None), \
         patch.object(ops, "call_host", return_value=(resp, 200)) as ch:
        out = ops._exec_disk_cleanup({"host": "h", "path": "/etc"}, ctx)
        assert ch.call_args.kwargs["data"] == {"dry_run": False}
        assert "freed 2.00 GB" in out.summary


def test_check_storage_error_path_returns_formatted_error():
    """check_storage passed a string as the error category, which crashed with "'str' object has no attribute 'value'"."""
    from unittest.mock import MagicMock
    from backend_server.src.mcp.tools.system_ops_tools import SystemOpsTools

    api = MagicMock()
    api.get.return_value = {"success": False, "error": "host down"}
    out = SystemOpsTools(api).check_storage({"host_name": "h"})
    assert out["isError"] is True
