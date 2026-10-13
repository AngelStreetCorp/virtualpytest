"""dns_lookuptime.py: `--dns` must be a DNS server address, never a hostname.

Since 2026-09-02 `--url` is the name to resolve and `--dns` the server to ask. A deployment still
passing `--dns <hostname>` failed hourly with a misleading "couldn't get address" (nslookup tried to
resolve the hostname to find a server).

Run: pytest tests/test_scripts/test_dns_lookuptime_args.py -v
"""
import os
import sys

import pytest

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from test_scripts.gw.dns_lookuptime import validate_dns_server  # noqa: E402


@pytest.mark.parametrize("value", ["", "8.8.8.8", "192.168.0.1", "2001:4860:4860::8888", "fe80::1%eth0"])
def test_accepts_empty_and_ip_addresses(value):
    assert validate_dns_server(value) is None


@pytest.mark.parametrize("value", ["epg.prod.ch.dmdsdp.com", "google.com", "dns.google"])
def test_rejects_hostnames_and_points_to_url(value):
    err = validate_dns_server(value)
    assert err and "--url " + value in err
