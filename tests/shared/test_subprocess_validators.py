"""Regression tests for the validators on subprocess-tainted argv in the
CodeQL 'Uncontrolled command line' family. The route layer is the primary
defense everywhere a Flask endpoint ultimately reaches subprocess; these
validators are the function-boundary defense-in-depth that closes the
taint path at the helper boundary so future callers (tests, scripts,
internal calls) cannot bypass it.

Run: pytest tests/shared/test_subprocess_validators.py -v
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.utils.system_utils import (  # noqa: E402
    validate_systemctl_action,
    validate_systemd_unit_name,
    validate_journalctl_level,
    normalize_journal_since,
    _validate_service_name,  # back-compat alias
    _validate_journal_level,  # back-compat alias
)


# ---------- systemd unit name ----------

@pytest.mark.parametrize("value", [
    "vpt-host",
    "vpt-stream",
    "vpt-server@1",
    "vpt.emulator.fifo",
    "my.service_2-3",
    "a",
])
def test_validate_systemd_unit_name_accepts(value):
    assert validate_systemd_unit_name(value) == value


@pytest.mark.parametrize("value", [
    "",                       # empty
    "-rf",                    # leading hyphen (would be a flag)
    "foo bar",                # space
    "foo;rm",                 # shell metacharacter
    "foo|bar",                # pipe
    "foo&bar",                # background
    "foo$bar",                # shell var
    "foo`bar`",               # command sub
    "foo\nbar",               # newline
    "../etc/passwd",          # path traversal
    "vpt-host; rm -rf /",     # injection payload
    "$(rm -rf /)",            # command substitution payload
])
def test_validate_systemd_unit_name_rejects(value):
    with pytest.raises(ValueError):
        validate_systemd_unit_name(value)


# ---------- systemctl action ----------

@pytest.mark.parametrize("value", [
    "start", "stop", "restart", "reload",
    "reload-or-restart", "try-reload-or-restart",
    "kill", "is-active", "status",
    "enable", "disable", "mask", "unmask", "reset-failed",
])
def test_validate_systemctl_action_accepts(value):
    assert validate_systemctl_action(value) == value


@pytest.mark.parametrize("value", [
    "",
    "--help",
    "edit",
    "shell",
    "condreload",
    "help",  # not a real systemctl verb
    "foo",
    "reboot",  # not a systemctl verb (sudo systemctl reboot is its own cmd)
])
def test_validate_systemctl_action_rejects(value):
    with pytest.raises(ValueError):
        validate_systemctl_action(value)


# ---------- journalctl -p level ----------

@pytest.mark.parametrize("value", [
    "emerg", "alert", "crit", "err", "warning", "notice", "info", "debug",
    "0", "1", "3", "7",
    "info..debug", "0..7", "emerg..alert",
])
def test_validate_journalctl_level_accepts(value):
    assert validate_journalctl_level(value) == value


@pytest.mark.parametrize("value", [
    "",
    "foo",
    "8",  # journalctl priority digits are 0-7
    "9",
    "10",
    "info debug",         # space
    "--output=json",      # flag injection
    "info; rm -rf /",     # shell metacharacter
    "emerg..foo",         # half-range
    "emerg..",            # open range
    "..debug",            # open range
    "  info",             # leading whitespace (must be trimmed by caller)
    "info  ",             # trailing whitespace
])
def test_validate_journalctl_level_rejects(value):
    with pytest.raises(ValueError):
        validate_journalctl_level(value)


# ---------- normalize_journal_since ----------

@pytest.mark.parametrize("inp,expected", [
    # relative spans we map
    ("1h", "-1h"),
    ("30min", "-30min"),
    ("2 weeks", "-2week"),
    # signed relatives pass through
    ("-1h", "-1h"),
    ("+30min", "+30min"),
    # keywords pass through
    ("today", "today"),
    ("yesterday", "yesterday"),
    ("now", "now"),
    ("tomorrow", "tomorrow"),
    # absolute timestamps pass through
    ("2026-05-19", "2026-05-19"),
    ("2026-05-19 08:00", "2026-05-19 08:00"),
    ("2026-05-19 08:00:00", "2026-05-19 08:00:00"),
    ("2026-05-19T08:00:00", "2026-05-19T08:00:00"),
])
def test_normalize_journal_since_accepts(inp, expected):
    assert normalize_journal_since(inp) == expected


@pytest.mark.parametrize("inp", [
    None,
    "",
    "   ",
    "foo bar",
    "1 hour ago --output=json",  # injection-style since
    "yesterday; rm -rf /",
    "1.5h",                       # fractional unit (we don't parse)
    "tomorrows",                  # typo / unknown unit
    "2026/05/19",                 # wrong date format
])
def test_normalize_journal_since_rejects(inp):
    """Anything that doesn't fit the documented systemd.time(7) syntax we
    accept must return None, not pass through verbatim (the old behavior
    would have let 'yesterday --output=json' reach journalctl as one argv
    slot, which was a taint trap)."""
    assert normalize_journal_since(inp) is None


# ---------- back-compat aliases ----------

def test_back_compat_service_alias():
    assert _validate_service_name("vpt-host") == "vpt-host"
    with pytest.raises(ValueError):
        _validate_service_name("foo; rm")


def test_back_compat_level_alias():
    assert _validate_journal_level("info") == "info"
    with pytest.raises(ValueError):
        _validate_journal_level("foo")
