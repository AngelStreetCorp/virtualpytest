"""mobile-app feature — backend_server routes + nginx phone-link location (TASK-17 W2).

Tier A: server API + static source, no device and no phone. The pairing/slot lifecycle
itself (bridge, sim, controller round-trip) is W1's tier — tests/backend_host/test_mobile_app_bridge.py.

Two things are pinned here:

  * every nginx template that proxies `/host/{name}/api/` also carries the WebSocket-
    capable `/host/{name}/phone/socket.io/` location (TASK-17 §1.4) — the api/ block has
    no Upgrade headers and rewrites the URI to "/", so it cannot carry Socket.IO traffic.
    Static / unit: no nginx binary needed, so it runs everywhere `pytest` does.
  * `/server/mobile-app/*` — 401 with no credentials, 400/404 shape of the pairing
    endpoints, and that GET /hosts only ever lists phone_agent slots.
"""

import re
from pathlib import Path

import pytest

from .conftest import assert_not_auth_failure

NGINX_CONFIG_DIR = Path(__file__).resolve().parents[2] / "infra/proxy/nginx/config"
API_LOCATION_RE = re.compile(r"location ~ \^/host/\(\[\^/\]\+\)/api/")
PHONE_LOCATION_RE = re.compile(r"location ~ \^/host/\(\[\^/\]\+\)/phone/socket\\\.io/")


def _touched_templates():
    """Every *.conf under infra/proxy/nginx/config that proxies the /host/{name}/api/ block."""
    templates = sorted(NGINX_CONFIG_DIR.glob("*.conf"))
    assert templates, f"no .conf templates found under {NGINX_CONFIG_DIR}"
    return [t for t in templates if API_LOCATION_RE.search(t.read_text())]


class TestNginxPhoneLocationStatic:
    """@pytest.mark.unit — pure static checks on the template files, no server needed."""

    @pytest.mark.unit
    def test_every_api_template_also_has_phone_socketio_location(self):
        touched = _touched_templates()
        assert touched, "expected at least one template with the /host/{name}/api/ location"
        for template in touched:
            text = template.read_text()
            assert PHONE_LOCATION_RE.search(text), (
                f"{template.name}: has the /host/{{name}}/api/ location but no "
                f"/host/{{name}}/phone/socket.io/ location (TASK-17 C10)"
            )
            # find the phone location block and confirm it upgrades the connection —
            # the whole point of this location is the Upgrade header the api/ block lacks.
            match = PHONE_LOCATION_RE.search(text)
            block_start = match.start()
            block_end = text.index("\n    }", block_start)
            block = text[block_start:block_end]
            assert "proxy_set_header Upgrade $http_upgrade;" in block, (
                f"{template.name}: phone socket.io location does not set the Upgrade header"
            )

    @pytest.mark.unit
    def test_touched_templates_have_balanced_braces(self):
        touched = _touched_templates()
        for template in touched:
            text = template.read_text()
            opens = text.count("{")
            closes = text.count("}")
            assert opens == closes, (
                f"{template.name}: unbalanced braces after the phone-link edit "
                f"({opens} '{{' vs {closes} '}}')"
            )


class TestMobileAppApi:
    """Live-server tests. Auto-skip (conftest.require_server_reachable) when no server answers."""

    def test_hosts_requires_credentials(self, get):
        response = get("/server/mobile-app/hosts")
        assert response.status_code in (401, 403, 500), response.text[:300]

    def test_list_hosts_shape_and_phone_only_slots(self, get, api_headers):
        response = get("/server/mobile-app/hosts", headers=api_headers)
        assert_not_auth_failure(response, "listing mobile-app hosts")
        assert response.status_code == 200, response.text[:300]

        body = response.json()
        assert body.get("success") is True
        hosts = body.get("hosts")
        assert isinstance(hosts, list)
        for host in hosts:
            assert host.get("host_name"), host
            slots = host.get("slots")
            assert isinstance(slots, list), host
            # every host listed must have been filtered to phone_agent devices only —
            # a non-phone device leaking in here would mean the DEVICE_MODEL filter broke.
            assert slots, f"{host.get('host_name')} listed with no slots at all"

    def test_create_pairing_missing_fields_is_400(self, post, api_headers):
        response = post("/server/mobile-app/pairings", json={}, headers=api_headers)
        assert_not_auth_failure(response, "creating a pairing with no body")
        assert response.status_code == 400, response.text[:300]
        assert response.json().get("success") is False

    def test_create_pairing_unknown_host_is_404(self, post, api_headers):
        response = post(
            "/server/mobile-app/pairings",
            json={"host_name": "no-such-host-xyz", "device_id": "device1"},
            headers=api_headers,
        )
        assert_not_auth_failure(response, "creating a pairing on an unknown host")
        assert response.status_code == 404, response.text[:300]
        assert response.json().get("success") is False

    def test_delete_pairing_unknown_host_is_404(self, delete, api_headers):
        response = delete("/server/mobile-app/pairings/no-such-host-xyz/device1", headers=api_headers)
        assert_not_auth_failure(response, "deleting a pairing on an unknown host")
        assert response.status_code == 404, response.text[:300]
