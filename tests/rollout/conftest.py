"""Rollout tooling tests (customer bundle builder).

The `unit` marker is registered in `tests/backend_server/conftest.py`, which does not reach this
directory. Registering it here keeps the tests marked as what they are — pure logic, no network,
no device, no live backend — and silences the unknown-mark warning. Nothing in this directory
skips on a probe today; the marker says that is intentional rather than accidental.
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "unit: pure unit test — runs without a live backend server")