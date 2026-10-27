"""
The unknown-screens page reports on ONE interface (BUG-0795).

`POST /server/userinterface/getUnknownScreens` used to answer 200 with an empty
report for an interface that does not exist, so `/configuration/interface/
no-such-interface/unknown` showed a healthy report — "Every screen this device
shows has a node in its tree" — and a typo looked like an interface without
unknown screens.
"""

import pytest
from flask import Flask

pytestmark = pytest.mark.unit  # no live server: the route is exercised on its own

from backend_server.src.routes import server_userinterface_routes as routes


TEAM = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "check_supabase", lambda: None)
    monkeypatch.setattr(routes, "list_unknown_screens",
                        lambda team_id, userinterface=None, include_resolved=False: [])
    app = Flask(__name__)
    app.register_blueprint(routes.server_userinterface_bp)
    return app.test_client()


def _post(client, name):
    return client.post(f"/server/userinterface/getUnknownScreens?team_id={TEAM}"
                       f"&userinterface={name}")


def test_an_interface_that_does_not_exist_is_not_an_all_clear(client, monkeypatch):
    monkeypatch.setattr(routes, "get_userinterface_by_name", lambda name, team, mode=None: None)

    resp = _post(client, "no-such-interface")

    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"] == 'User interface "no-such-interface" not found'


def test_an_interface_that_exists_still_reports(client, monkeypatch):
    monkeypatch.setattr(routes, "get_userinterface_by_name",
                        lambda name, team, mode=None: {"id": "ui-1", "name": name})

    resp = _post(client, "stb-testop")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["counts"]["needs_a_name"] == 0


def test_an_interface_that_exists_only_in_prod_still_reports(client, monkeypatch):
    """A published interface has a dev row too, but never assume it."""
    def by_name(name, team, mode=None):
        return {"id": "ui-1", "name": name} if mode == "prod" else None

    monkeypatch.setattr(routes, "get_userinterface_by_name", by_name)

    resp = _post(client, "stb-testop")

    assert resp.status_code == 200


def test_the_interface_name_is_required(client, monkeypatch):
    monkeypatch.setattr(routes, "get_userinterface_by_name",
                        lambda name, team, mode=None: {"id": "ui-1", "name": name})

    resp = client.post(f"/server/userinterface/getUnknownScreens?team_id={TEAM}")

    assert resp.status_code == 400
