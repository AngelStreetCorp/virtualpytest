"""
The storage signing routes must not sign a data: URI (BUG-0798).

A capture that arrived inline as `data:image/jpeg;base64,...` was sent to
`POST /server/storage/signed-url` like any other path. The server signed the
base64 payload as if it were a key, and the browser asked for
`/virtualpytest/data%3Aimage/jpeg%3Bbase64%2C/...` — a 404, and an empty grey
box where the thumbnail should be.
"""

import pytest
from flask import Flask, request

pytestmark = pytest.mark.unit  # no live server: the route is exercised on its own

from backend_server.src.lib import auth_middleware
from backend_server.src.routes import server_storage_routes as routes


DATA_URI = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth_middleware, "_is_request_auto_signed", lambda: True)
    app = Flask(__name__)

    @app.before_request
    def _principal():
        # What the auth middleware puts on the request.
        request.user_email = "tester@example.com"
        request.user_id = "11111111-1111-1111-1111-111111111111"
        request.user_role = "admin"

    app.register_blueprint(routes.server_storage_bp)
    return app.test_client()


def test_a_data_uri_cannot_be_signed(client, monkeypatch):
    signed = []

    class FakeUploader:
        def generate_presigned_url(self, path, expires_in=3600):
            signed.append(path)
            return {"success": True, "url": f"https://signed/{path}", "expires_in": expires_in,
                    "expires_at": "2026-10-22T18:00:00Z"}

    monkeypatch.setattr(routes, "get_cloudflare_utils", lambda: FakeUploader())

    resp = client.post("/server/storage/signed-url", json={"path": DATA_URI})

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert "data:" in body["error"]
    # Nothing was signed.
    assert signed == []


def test_a_real_path_is_still_signed(client, monkeypatch):
    class FakeUploader:
        def generate_presigned_url(self, path, expires_in=3600):
            return {"success": True, "url": f"https://signed/{path}", "expires_in": expires_in,
                    "expires_at": "2026-10-22T18:00:00Z"}

    monkeypatch.setattr(routes, "get_cloudflare_utils", lambda: FakeUploader())

    resp = client.post("/server/storage/signed-url", json={"path": "captures/device1/a.jpg"})

    assert resp.status_code == 200
    assert resp.get_json()["url"] == "https://signed/captures/device1/a.jpg"


def test_a_batch_reports_the_data_uri_as_failed(client, monkeypatch):
    class FakeUploader:
        def generate_presigned_urls_batch(self, paths, expires_in=3600):
            return {
                "success": True,
                "urls": [{"path": p, "url": f"https://signed/{p}", "expires_at": "2026-10-22T18:00:00Z"}
                         for p in paths],
                "failed": [],
                "generated_count": len(paths),
                "failed_count": 0,
            }

    monkeypatch.setattr(routes, "get_cloudflare_utils", lambda: FakeUploader())

    resp = client.post("/server/storage/signed-urls-batch",
                       json={"paths": ["captures/device1/a.jpg", DATA_URI]})

    assert resp.status_code == 200
    body = resp.get_json()
    assert [u["path"] for u in body["urls"]] == ["captures/device1/a.jpg"]
    assert [f["path"] for f in body["failed"]] == [DATA_URI]
    assert body["failed_count"] == 1
