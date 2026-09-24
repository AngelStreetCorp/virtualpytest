"""Tests for the host-side admin-token gate.

The gate adds a second factor on top of the global /host/* API key
check: callers must also send `Authorization: Admin <VPT_HOST_ADMIN_TOKEN>`.
We exercise it by importing the decorator directly and wrapping a Flask
view function; no Flask app required.
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)


@pytest.fixture(autouse=True)
def _clean_admin_env(monkeypatch):
    """Always start without VPT_HOST_ADMIN_TOKEN; tests opt in explicitly."""
    monkeypatch.delenv("VPT_HOST_ADMIN_TOKEN", raising=False)


@pytest.fixture
def app_and_view():
    """Build a tiny Flask app wrapping a trivial view behind the decorator,
    so we can exercise it as a WSGI request without spinning up the
    full backend_host."""
    from flask import Flask, jsonify
    from backend_host.src.lib.utils.admin_token import require_admin_token

    app = Flask(__name__)

    @require_admin_token
    def view():
        return jsonify({"success": True, "ok": True})

    # Bind the wrapped view to /admin-only-test (unused — we invoke
    # the wrapper directly via app.test_request_context below).
    app.add_url_rule("/admin-only-test", view_func=view)
    return app, view


def _call(app, view, headers):
    """Invoke the wrapped view in a request context and return
    `(response_json_body_or_default, status_code)` for easy assertion.

    The wrapped function can return either a Flask Response (from
    `jsonify`) or a `(body, status)` tuple. We normalize both to the
    tuple shape so tests can pattern-match.
    """
    with app.test_request_context("/admin-only-test", headers=headers):
        ret = view()
    if isinstance(ret, tuple):
        body, status = ret
    else:
        # Flask Response; expose its JSON body and status_code.
        body, status = ret, ret.status_code
    # Ensure json fixture data is loaded for body.json access.
    if hasattr(body, "get_json"):
        body.get_json(silent=True)
    return body, status


def test_unconfigured_denies_closed(app_and_view):
    """No VPT_HOST_ADMIN_TOKEN in env -> always 403."""
    app, view = app_and_view
    resp = _call(app, view, {"Authorization": "Admin anything"})
    assert resp[1] == 403
    assert "not configured" in resp[0].json["error"]


def test_missing_header_denied(app_and_view, monkeypatch):
    monkeypatch.setenv("VPT_HOST_ADMIN_TOKEN", "secret-abc")
    app, view = app_and_view
    resp = _call(app, view, {})
    assert resp[1] == 403
    assert "missing or malformed" in resp[0].json["error"]


def test_wrong_scheme_denied(app_and_view, monkeypatch):
    monkeypatch.setenv("VPT_HOST_ADMIN_TOKEN", "secret-abc")
    app, view = app_and_view
    resp = _call(app, view, {"Authorization": "Bearer secret-abc"})
    assert resp[1] == 403
    assert "missing or malformed" in resp[0].json["error"]


def test_wrong_token_denied(app_and_view, monkeypatch):
    monkeypatch.setenv("VPT_HOST_ADMIN_TOKEN", "secret-abc")
    app, view = app_and_view
    resp = _call(app, view, {"Authorization": "Admin secret-wrong"})
    assert resp[1] == 403
    assert "mismatch" in resp[0].json["error"]


def test_correct_token_allowed(app_and_view, monkeypatch):
    monkeypatch.setenv("VPT_HOST_ADMIN_TOKEN", "secret-abc")
    app, view = app_and_view
    resp = _call(app, view, {"Authorization": "Admin secret-abc"})
    # happy path returns the wrapped view's normal response
    assert resp[1] == 200
    assert resp[0].json["success"] is True


def test_scheme_case_insensitive(app_and_view, monkeypatch):
    monkeypatch.setenv("VPT_HOST_ADMIN_TOKEN", "secret-abc")
    app, view = app_and_view
    for variant in ("admin", "ADMIN", "Admin", "aDmIn"):
        resp = _call(app, view, {"Authorization": f"{variant} secret-abc"})
        assert resp[1] == 200, f"scheme '{variant}' should have been accepted"


def test_trailing_whitespace_in_token_still_denied(app_and_view, monkeypatch):
    """Env var parsing strips surrounding whitespace; the supplied value
    must match exactly (no leading/trailing space)."""
    monkeypatch.setenv("VPT_HOST_ADMIN_TOKEN", "secret-abc")
    app, view = app_and_view
    resp = _call(app, view, {"Authorization": "Admin  secret-abc"})
    assert resp[1] == 403


def test_token_rotation_at_runtime(monkeypatch):
    """Operator rotates VPT_HOST_ADMIN_TOKEN; the next request must see
    the new value, no restart required."""
    from flask import Flask, jsonify
    from backend_host.src.lib.utils.admin_token import require_admin_token

    app = Flask(__name__)

    @require_admin_token
    def view():
        return jsonify({"ok": True})

    def status_of(ret):
        return ret.status_code if not isinstance(ret, tuple) else ret[1]

    monkeypatch.setenv("VPT_HOST_ADMIN_TOKEN", "old-token")
    with app.test_request_context("/x", headers={"Authorization": "Admin old-token"}):
        assert status_of(view()) == 200

    monkeypatch.setenv("VPT_HOST_ADMIN_TOKEN", "new-token")
    with app.test_request_context("/x", headers={"Authorization": "Admin old-token"}):
        assert status_of(view()) == 403
    with app.test_request_context("/x", headers={"Authorization": "Admin new-token"}):
        assert status_of(view()) == 200


def test_both_endpoints_carry_the_decorator():
    """Sanity-check that the two Critical endpoints from the audit are
    actually gated. fail loudly if either is missing the @require_admin_token
    so a future merge cannot quietly drop the decorator.

    Both routes should have __wrapped__ pointing at the original view
    function — the wrapper chain is require_admin_token ->
    route_exception_handler -> view.
    """
    from backend_host.src.routes import host_desktop_bash_routes
    from backend_host.src.routes import host_system_routes

    bash_fn = host_desktop_bash_routes.execute_bash_command
    rcmd_fn = host_system_routes.run_command

    # require_admin_token uses functools.wraps, which sets __wrapped__.
    # The chain depth tells us how many decorators are stacked.
    def depth(fn):
        d = 0
        while getattr(fn, "__wrapped__", None) is not None:
            fn = fn.__wrapped__
            d += 1
        return d

    # We require at least 2 stacked decorators
    # (require_admin_token + route_exception_handler). Anything less means
    # someone dropped the admin gate.
    assert depth(bash_fn) >= 2, (
        f"execute_bash_command has only {depth(bash_fn)} decorator layer(s); "
        "expected require_admin_token + route_exception_handler"
    )
    assert depth(rcmd_fn) >= 2, (
        f"run_command has only {depth(rcmd_fn)} decorator layer(s); "
        "expected require_admin_token + route_exception_handler"
    )
