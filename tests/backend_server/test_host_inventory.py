"""Verify all expected VPT hosts are registered and online.

Calls getAllHosts and checks that every host in EXPECTED_HOSTS is present
and reports 'online' status. Run with:

    cd tests && python -m pytest backend_server/test_host_inventory.py -v

Override SERVER_URL/API_KEY via environment variables (see conftest.py).
"""

import pytest

# ── Expected hosts ───────────────────────────────────────────────────
# Update this list when VMs are added/removed.
# Format: (host_name, expected_ip, expected_host_type)

EXPECTED_HOSTS = [
    # VNC hosts actually registered on the staging test server.
    # NOTE: android hosts, host-clone-2, host-clone-3 and runner-01 are not provisioned;
    # excluded so their four parametrised tests each run instead of skipping with
    # "<host> not registered". Re-add a host here once it is genuinely registered —
    # GET /server/system/getAllHosts is the source of truth.
    # The sample-app-* fleet is registered but deliberately excluded: it belongs to sample-app
    # testing, not the VirtualPyTest CI matrix.
    ("host-clone-1", "192.168.0.109", "host_vnc"),
]


# ── Helpers ──────────────────────────────────────────────────────────

def _fetch_all_hosts(get, api_headers):
    """Fetch hosts from server, return dict keyed by host_name."""
    response = get(
        "/server/system/getAllHosts",
        headers=api_headers,
        params={
            "include_actions": "false",
            "include_system_stats": "false",
            "force_refresh": "true",
        },
    )
    assert response.status_code == 200, f"getAllHosts returned {response.status_code}"
    data = response.json()

    # API may return list directly or wrapped in {"hosts": [...]}
    if isinstance(data, list):
        hosts = data
    elif isinstance(data, dict):
        hosts = data.get("hosts", data.get("data", []))
        if isinstance(hosts, dict):
            hosts = list(hosts.values())
    else:
        hosts = []

    return {h.get("host_name", ""): h for h in hosts if isinstance(h, dict)}


# ── Tests ────────────────────────────────────────────────────────────

class TestHostInventory:
    """Verify all expected hosts are registered and online."""

    @pytest.fixture(autouse=True)
    def _hosts(self, get, api_headers):
        self.hosts = _fetch_all_hosts(get, api_headers)

    @pytest.mark.parametrize(
        "host_name,expected_ip,expected_type",
        EXPECTED_HOSTS,
        ids=[h[0] for h in EXPECTED_HOSTS],
    )
    def test_host_registered(self, host_name, expected_ip, expected_type):
        """Each expected host must be present in getAllHosts."""
        # Assert, don't skip. Skipping on absence made the one test whose entire purpose is
        # "this host is registered" incapable of ever failing: an unregistered host reported
        # green. A name is in EXPECTED_HOSTS because it is meant to be there — if it is not,
        # that is the regression.
        assert host_name in self.hosts, (
            f"{host_name} not registered — registered hosts: {sorted(self.hosts)}"
        )

    @pytest.mark.parametrize(
        "host_name,expected_ip,expected_type",
        EXPECTED_HOSTS,
        ids=[h[0] for h in EXPECTED_HOSTS],
    )
    def test_host_online(self, host_name, expected_ip, expected_type):
        """Each expected host must report online status."""
        assert host_name in self.hosts, f"{host_name} not registered"
        host = self.hosts[host_name]
        status = host.get("status", "unknown")
        assert status == "online", f"{host_name} is '{status}', expected 'online'"

    @pytest.mark.parametrize(
        "host_name,expected_ip,expected_type",
        EXPECTED_HOSTS,
        ids=[h[0] for h in EXPECTED_HOSTS],
    )
    def test_host_ip(self, host_name, expected_ip, expected_type):
        """Each host must have the expected IP (extracted from host_api_url)."""
        assert host_name in self.hosts, f"{host_name} not registered"
        host = self.hosts[host_name]
        # IP is embedded in host_api_url: "http://192.168.0.X:6109"
        api_url = host.get("host_api_url", "")
        actual_ip = api_url.replace("http://", "").split(":")[0] if api_url else ""
        assert actual_ip == expected_ip, (
            f"{host_name}: IP is '{actual_ip}' (from {api_url}), expected '{expected_ip}'"
        )

    @pytest.mark.parametrize(
        "host_name,expected_ip,expected_type",
        EXPECTED_HOSTS,
        ids=[h[0] for h in EXPECTED_HOSTS],
    )
    def test_host_type(self, host_name, expected_ip, expected_type):
        """Each host must have the expected host_type."""
        assert host_name in self.hosts, f"{host_name} not registered"
        host = self.hosts[host_name]
        actual_type = host.get("host_type", "")
        assert actual_type == expected_type, (
            f"{host_name}: type is '{actual_type}', expected '{expected_type}'"
        )

    def test_no_unexpected_offline(self):
        """No registered host should be offline."""
        # This used to call pytest.warns(...) as a bare statement, which builds a context
        # manager and discards it — the test passed whatever the fleet looked like. A host
        # the server still lists but cannot reach is exactly the regression this file is for,
        # so it fails now. Unlike EXPECTED_HOSTS this covers every host actually registered.
        offline = sorted(
            name for name, h in self.hosts.items()
            if h.get("status") == "offline"
        )
        assert not offline, f"registered but offline: {offline}"
