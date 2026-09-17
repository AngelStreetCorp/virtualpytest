"""Unit tests for the /server/* authorization guard.

Runs entirely in a Flask test request context — no deployed server needed, unlike
the rest of tests/backend_server. Covers the two axes the guard keeps separate
(docs/agent/platform/SERVER_AUTH.md):

  * API_KEY / X-API-Key  — the credential of the server API, for machine callers.
    Validated strictly and never waived by SERVER_OPEN_MODE or by the JWT posture.
  * user login           — Supabase JWT; SERVER_OPEN_MODE waives *this* only, and
    only for requests that look like they came from a browser.
"""

import pytest
from flask import Flask

from backend_server.src.lib.auth_middleware import (
    enforce_user_auth_if_enabled_for_request as guard,
)

pytestmark = pytest.mark.unit  # no live backend needed (conftest: require_server_reachable)

API_KEY = 'unit-test-strong-key'

# Browsers set Sec-Fetch-* on every fetch/XHR/navigation; curl and requests do not.
BROWSER_XHR = {'Sec-Fetch-Site': 'same-origin', 'Sec-Fetch-Mode': 'cors'}
BROWSER_NAV = {'Sec-Fetch-Site': 'none', 'Sec-Fetch-Mode': 'navigate'}
DIRECT_CALL: dict = {}


@pytest.fixture
def status(monkeypatch):
    """Return a callable: (headers, **env) -> HTTP status the guard would answer."""
    app = Flask(__name__)

    def _status(headers, *, open_mode=False, api_key=API_KEY, jwt_secret=None, method='GET'):
        for name, value in (
            ('SERVER_OPEN_MODE', 'true' if open_mode else 'false'),
            ('API_KEY', api_key),
            ('SUPABASE_JWT_SECRET', jwt_secret),
            ('SERVER_PUBLIC_KEY', None),
            ('AUTO_SIGN_ENABLED', 'false'),
            ('ENFORCE_FRONTEND_JWT', None),
        ):
            monkeypatch.delenv(name, raising=False)
            if value:
                monkeypatch.setenv(name, value)

        with app.test_request_context('/server/system/info', method=method, headers=headers):
            rejection = guard()
            return 200 if rejection is None else rejection[1]

    return _status


# --------------------------------------------------------------- strict API key
@pytest.mark.parametrize('open_mode', [True, False])
def test_valid_api_key_is_accepted_in_every_posture(status, open_mode):
    assert status({'X-API-Key': API_KEY}, open_mode=open_mode) == 200


@pytest.mark.parametrize('open_mode', [True, False])
def test_wrong_api_key_is_401_and_never_falls_through(status, open_mode):
    """A present-but-invalid key is a hard 401 — it must not reach a later branch.

    It used to fall through, so a service with a typo'd key was silently admitted
    as admin on an open-mode deployment and rejected on a JWT one.
    """
    assert status({'X-API-Key': 'wrong'}, open_mode=open_mode) == 401


def test_wrong_api_key_is_401_even_with_jwt_enforced(status):
    assert status({'X-API-Key': 'wrong'}, jwt_secret='x' * 40) == 401


# --------------------------------------------- open mode waives login, not the key
def test_open_mode_lets_the_browser_in_without_any_credential(status):
    assert status(BROWSER_XHR, open_mode=True) == 200


def test_open_mode_lets_a_browser_navigation_in(status):
    """Report pages opened in a new tab carry no header — only Sec-Fetch-Mode: navigate."""
    assert status(BROWSER_NAV, open_mode=True) == 200


def test_open_mode_still_requires_the_key_from_a_direct_call(status):
    assert status(DIRECT_CALL, open_mode=True) == 401


def test_open_mode_accepts_a_direct_call_that_presents_the_key(status):
    assert status({'X-API-Key': API_KEY}, open_mode=True) == 200


def test_open_mode_without_api_key_configured_is_fully_open(status):
    """Nothing to enforce when the server has no API_KEY — unchanged behaviour."""
    assert status(DIRECT_CALL, open_mode=True, api_key=None) == 200


# ------------------------------------------------------------- closed postures
def test_closed_rejects_the_browser(status):
    assert status(BROWSER_XHR) == 401


def test_jwt_posture_rejects_a_browser_without_a_token(status):
    assert status(BROWSER_XHR, jwt_secret='x' * 40) == 401


def test_jwt_posture_still_accepts_the_service_key(status):
    assert status({'X-API-Key': API_KEY}, jwt_secret='x' * 40) == 200
