"""Regression test for the server's Tello status proxy (BUG-0500).

``/server/drone/tello/status`` asked the host for ``/host/remote/getStatus`` —
an address that has never existed. The ``/host/remote`` blueprint only exposes
takeScreenshot, screenshotAndDump, getApps, tapCoordinates, executeCommand,
dumpUi and getOrientation, so every call 404'd.

That is worse than a wrong answer: the Device tile's poll aborts on any non-2xx,
so the tile never reached its scan step and could only ever render its
catch-all error state. The user never saw the real state, not even "the drone is
off".

Pinned here because the route name looks plausible and would silently drift
back to the generic remote namespace again.

Lives under tests/drone/ rather than tests/backend_server/ because that
directory is live-HTTP only — its conftest skips the whole module unless a
running backend answers /server/health, which would silently skip exactly the
regression this test exists to catch. This is a pure route-wiring test: Flask's
own test_client, no network.
"""

from __future__ import annotations

from flask import Flask

from backend_server.src.routes import server_drone_routes


def _app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(server_drone_routes.server_drone_bp)
    return app


def _capture(monkeypatch):
    """Record what the route asks the host for, and answer 200."""
    seen: dict = {}

    def _proxy(endpoint, method="GET", data=None, query_params=None, *_a, **_k):
        seen["endpoint"] = endpoint
        seen["method"] = method
        seen["data"] = data
        return {"success": True, "linked": False, "last_error": None}, 200

    monkeypatch.setattr(server_drone_routes, "proxy_to_host_with_params", _proxy)
    return seen


def test_status_proxies_to_the_drone_route_not_the_generic_remote_one(monkeypatch) -> None:
    seen = _capture(monkeypatch)
    client = _app().test_client()

    res = client.get("/server/drone/tello/status?host_name=vpt-pi4&device_id=device3")

    assert res.status_code == 200
    assert seen["endpoint"] == "/host/drone/tello/status", (
        "must proxy to the host's drone route; /host/remote/getStatus does not exist"
    )
    assert seen["method"] == "POST"
    assert seen["data"] == {"device_id": "device3"}


def test_status_passes_a_no_link_answer_through_untouched(monkeypatch) -> None:
    """linked=false is a valid answer, not an error — it must survive the proxy
    so the tile can fall through to its scan step."""
    _capture(monkeypatch)
    client = _app().test_client()

    body = client.get("/server/drone/tello/status?host_name=vpt-pi4&device_id=device3").get_json()

    assert body["linked"] is False


def test_status_requires_host_name_and_device_id(monkeypatch) -> None:
    _capture(monkeypatch)
    client = _app().test_client()

    assert client.get("/server/drone/tello/status").status_code == 400
    assert client.get("/server/drone/tello/status?host_name=vpt-pi4").status_code == 400
    assert client.get("/server/drone/tello/status?device_id=device3").status_code == 400