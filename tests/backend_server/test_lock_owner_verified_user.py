"""Device locks record the verified login, not the id the browser sends (BUG-0424).

A logged-in user whose browser sent the built-in default user id was stored as
that default, so take-control sessions could not be traced to a person.
"""
import pytest
from flask import Flask, request

from backend_server.src.lib.utils.lock_utils import resolve_lock_owner

pytestmark = pytest.mark.unit

DEFAULT = 'eb6cfd93-44ab-4783-bd0c-129b734640f3'
REAL = '3f2b8c1e-6a4d-4e0b-9a7f-2c5d8e1f0a11'
app = Flask(__name__)


def _resolve(data, **principal):
    with app.test_request_context('/server/control/takeControl', method='POST'):
        for k, v in principal.items():
            setattr(request, k, v)
        return resolve_lock_owner(data)


def test_verified_login_wins_over_browser_default():
    assert _resolve({'user_id': DEFAULT, 'user_name': 'h.user'},
                    user_id=REAL, user_email='h.user@example.com') == (REAL, 'h.user')


def test_verified_login_without_display_name_uses_email():
    assert _resolve({'user_id': DEFAULT}, user_id=REAL, user_email='h.user@example.com') \
        == (REAL, 'h.user@example.com')


@pytest.mark.parametrize('principal', ['open_mode', 'service_api_key', 'auto_sign', None])
def test_no_personal_login_keeps_browser_values(principal):
    assert _resolve({'user_id': DEFAULT, 'user_name': 'x'}, user_id=principal) == (DEFAULT, 'x')


def test_takeover_reads_requested_by_user():
    with app.test_request_context('/', method='POST'):
        assert resolve_lock_owner({'requested_by_user': 'u1'}, user_key='requested_by_user') == ('u1', None)
