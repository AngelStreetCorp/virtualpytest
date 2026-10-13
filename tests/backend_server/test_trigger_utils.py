"""Unit tests for trigger.caller_user labelling (backend_server/src/lib/utils/trigger_utils.py).

Runs in a Flask test request context; the identity the auth guard would have set is
put on `request` directly.
"""

import pytest
from flask import Flask, request

from backend_server.src.lib.utils.trigger_utils import resolve_caller_user

pytestmark = pytest.mark.unit

BROWSER = {'Sec-Fetch-Site': 'same-origin', 'Sec-Fetch-Mode': 'cors'}
DEFAULT_UI_USER_ID = 'eb6cfd93-44ab-4783-bd0c-129b734640f3'


@pytest.fixture
def resolve():
    app = Flask(__name__)

    def _resolve(identity, body_user_id=None, user_name=None, headers=None, email=None, meta=None):
        with app.test_request_context('/server/script/execute', method='POST', headers=headers or {}):
            if identity:
                request.user_id = identity
                request.user_email = email
                request.user_metadata = meta or {}
            return resolve_caller_user(body_user_id, user_name)

    return _resolve


def test_logged_in_user_uses_jwt_identity_not_body_id(resolve):
    assert resolve('a1b2-real-user', DEFAULT_UI_USER_ID, 'Jane Doe', BROWSER) == 'vpt_user:Jane Doe'


def test_logged_in_user_without_name_falls_back_to_email(resolve):
    assert resolve('a1b2-real-user', DEFAULT_UI_USER_ID, None, BROWSER, email='jane@acme.io') == 'vpt_user:jane@acme.io'


def test_logged_in_user_name_from_jwt_metadata(resolve):
    assert resolve('a1b2-real-user', None, None, BROWSER, meta={'full_name': 'Jane Doe'}) == 'vpt_user:Jane Doe'


def test_service_api_key_keeps_external_label(resolve):
    assert resolve('service_api_key', None, None, {'X-User-ID': 'idp_scheduler'}) == 'idp_scheduler'


def test_open_mode_browser_is_vpt_user(resolve):
    assert resolve('open_mode', DEFAULT_UI_USER_ID, None, BROWSER) == 'vpt_user:open_mode'


def test_open_mode_direct_call_keeps_external_label(resolve):
    assert resolve('open_mode', None, None, {'X-User-ID': 'idp_scheduler'}) == 'idp_scheduler'


def test_auto_signed_script_keeps_its_own_label(resolve):
    assert resolve('auto_signed', 'fleet_health', None, {}) == 'fleet_health'
