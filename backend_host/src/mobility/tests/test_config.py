"""
Config tests — fail-safe defaults, garbage-value recovery, enable parsing.

The gate reads ``VPT_MOBILITY_ENABLED`` at every evaluation, so the parser
must be re-callable and observe monkeypatched env changes without a process
restart. These tests pin it down.
"""
from __future__ import annotations

import math
import os

import pytest

from backend_host.src.mobility import config as cfg_mod
from backend_host.src.mobility.config import DEFAULTS, MobilityConfig


# All tests start from a clean VPT_MOBILITY_* env so a developer's shell
# config cannot leak in.
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("VPT_MOBILITY_"):
            monkeypatch.delenv(key, raising=False)


# ---- defaults ---------------------------------------------------------------


def test_defaults_match_spec_when_no_env_set():
    cfg = MobilityConfig.from_env()
    assert cfg.enabled is False
    assert cfg.max_speed_mps == DEFAULTS["max_speed_mps"]
    assert cfg.max_turn_radps == DEFAULTS["max_turn_radps"]
    assert cfg.max_duration_s == DEFAULTS["max_duration_s"]
    assert cfg.geofence_min_x == DEFAULTS["geofence_min_x"]
    assert cfg.geofence_max_x == DEFAULTS["geofence_max_x"]
    assert cfg.geofence_min_y == DEFAULTS["geofence_min_y"]
    assert cfg.geofence_max_y == DEFAULTS["geofence_max_y"]
    assert cfg.heartbeat_timeout_ms == DEFAULTS["heartbeat_timeout_ms"]
    assert cfg.require_auth_token is True
    assert cfg.auth_token_max_age_s == DEFAULTS["auth_token_max_age_s"]
    assert cfg.nonce_window == DEFAULTS["nonce_window"]


def test_all_defaults_are_finite():
    cfg = MobilityConfig.from_env()
    for field_name in (
        "max_speed_mps",
        "max_turn_radps",
        "max_duration_s",
        "geofence_min_x",
        "geofence_max_x",
        "geofence_min_y",
        "geofence_max_y",
    ):
        assert math.isfinite(getattr(cfg, field_name)), field_name


# ---- numeric parsing --------------------------------------------------------


@pytest.mark.parametrize("env_key", [
    "VPT_MOBILITY_MAX_SPEED_MPS",
    "VPT_MOBILITY_MAX_TURN_RADPS",
    "VPT_MOBILITY_MAX_DURATION_S",
    "VPT_MOBILITY_GEOFENCE_MIN_X",
    "VPT_MOBILITY_GEOFENCE_MAX_X",
    "VPT_MOBILITY_GEOFENCE_MIN_Y",
    "VPT_MOBILITY_GEOFENCE_MAX_Y",
])
def test_numeric_env_overrides_apply(monkeypatch, env_key):
    monkeypatch.setenv(env_key, "2.5")
    cfg = MobilityConfig.from_env()
    short = env_key.replace("VPT_MOBILITY_", "").lower()
    assert getattr(cfg, short) == 2.5


def test_garbage_value_falls_back_with_warning(monkeypatch, capsys):
    monkeypatch.setenv("VPT_MOBILITY_MAX_SPEED_MPS", "abc")
    cfg = MobilityConfig.from_env()
    assert cfg.max_speed_mps == DEFAULTS["max_speed_mps"]
    captured = capsys.readouterr()
    assert "VPT_MOBILITY_MAX_SPEED_MPS" in captured.err
    assert "WARNING" in captured.err


def test_non_finite_value_falls_back_with_warning(monkeypatch, capsys):
    monkeypatch.setenv("VPT_MOBILITY_MAX_SPEED_MPS", "inf")
    cfg = MobilityConfig.from_env()
    assert cfg.max_speed_mps == DEFAULTS["max_speed_mps"]
    captured = capsys.readouterr()
    assert "WARNING" in captured.err


def test_empty_value_treated_as_unset(monkeypatch):
    monkeypatch.setenv("VPT_MOBILITY_MAX_SPEED_MPS", "")
    cfg = MobilityConfig.from_env()
    assert cfg.max_speed_mps == DEFAULTS["max_speed_mps"]


# ---- integer parsing --------------------------------------------------------


def test_int_env_override(monkeypatch):
    monkeypatch.setenv("VPT_MOBILITY_HEARTBEAT_TIMEOUT_MS", "750")
    assert MobilityConfig.from_env().heartbeat_timeout_ms == 750


def test_garbage_int_falls_back(monkeypatch):
    monkeypatch.setenv("VPT_MOBILITY_HEARTBEAT_TIMEOUT_MS", "abc")
    assert MobilityConfig.from_env().heartbeat_timeout_ms == DEFAULTS["heartbeat_timeout_ms"]


# ---- enable flag parsing ----------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "Yes"])
def test_enabled_truthy_values(monkeypatch, value):
    monkeypatch.setenv("VPT_MOBILITY_ENABLED", value)
    cfg = MobilityConfig.from_env()
    assert cfg.enabled is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "garbage", ""])
def test_enabled_falsy_values(monkeypatch, value):
    monkeypatch.setenv("VPT_MOBILITY_ENABLED", value)
    cfg = MobilityConfig.from_env()
    assert cfg.enabled is False


def test_enabled_default_is_false_without_env(monkeypatch):
    monkeypatch.delenv("VPT_MOBILITY_ENABLED", raising=False)
    assert MobilityConfig.from_env().enabled is False


# ---- re-read behavior (no module-level cache) ------------------------------


def test_from_env_re_reads_on_every_call(monkeypatch):
    monkeypatch.setenv("VPT_MOBILITY_ENABLED", "false")
    cfg1 = MobilityConfig.from_env()
    assert cfg1.enabled is False
    monkeypatch.setenv("VPT_MOBILITY_ENABLED", "true")
    cfg2 = MobilityConfig.from_env()
    assert cfg2.enabled is True


def test_package_helper_is_enabled_observes_monkeypatch(monkeypatch):
    """`is_enabled()` (re-exported in ``__init__.py``) reads env each time."""
    from backend_host.src.mobility import is_enabled

    monkeypatch.delenv("VPT_MOBILITY_ENABLED", raising=False)
    assert is_enabled() is False
    monkeypatch.setenv("VPT_MOBILITY_ENABLED", "yes")
    assert is_enabled() is True


def test_config_helper_returns_fresh_instance(monkeypatch):
    """The package-level ``current_config()`` (re-exported in ``__init__.py``)
    returns a fresh instance each call.

    The function name avoids shadowing the ``config`` submodule — a
    ``from backend_host.src.mobility.config import ...`` would otherwise
    rebind the package attribute to the submodule and silently make the
    helper uncallable.
    """
    import importlib

    pkg = importlib.import_module("backend_host.src.mobility")
    build_config = pkg.current_config

    monkeypatch.setenv("VPT_MOBILITY_MAX_SPEED_MPS", "0.75")
    c1 = build_config()
    monkeypatch.setenv("VPT_MOBILITY_MAX_SPEED_MPS", "1.25")
    c2 = build_config()
    assert c1.max_speed_mps == 0.75
    assert c2.max_speed_mps == 1.25


# ---- geofence convenience --------------------------------------------------


def test_geofence_unconfigured_when_all_zero():
    cfg = MobilityConfig(  # build without going through env
        enabled=True,
        max_speed_mps=1.0,
        max_turn_radps=0.5,
        max_duration_s=10.0,
        geofence_min_x=0.0,
        geofence_max_x=0.0,
        geofence_min_y=0.0,
        geofence_max_y=0.0,
        heartbeat_timeout_ms=2000,
        require_auth_token=True,
        auth_token_max_age_s=5,
        nonce_window=100,
    )
    assert cfg.geofence_configured is False
    assert cfg.is_inside_geofence(1.0, 1.0) is False


def test_geofence_configured_with_nonzero_bound():
    cfg = MobilityConfig.from_env()  # defaults are non-zero on min_x..max_y
    assert cfg.geofence_configured is True
    assert cfg.is_inside_geofence(50.0, 25.0) is True
    assert cfg.is_inside_geofence(-1.0, 25.0) is False
    assert cfg.is_inside_geofence(50.0, 999.0) is False


# ---- frozen dataclass -------------------------------------------------------


def test_config_is_frozen():
    cfg = MobilityConfig.from_env()
    with pytest.raises(Exception):  # FrozenInstanceError is a subclass of AttributeError
        cfg.max_speed_mps = 99.0  # type: ignore[misc]