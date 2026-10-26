"""Unit tests: a campaign step's script parameters become the right CLI flags.

A campaign stores a step's parameter keys WITH their dashes
(`"--userinterface": "pokemon-blue-web"`). The executor rebuilt the flag by prefixing
"--" again, so argparse saw "----userinterface pokemon-blue-web" and the script died
with "Unknown argument(s) for <script>" before it started. The nightly web deployment
failed its Pokemon step (and every other virtual script with a parameter dict) every
night.

No DB, no device, no HTTP: only the pure flag builder is exercised.
Repo root is 2 levels up from tests/shared/ (same bootstrap as the other unit tests here).
"""
import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from shared.src.lib.executors.campaign_executor import build_script_parameter_parts


def test_dashed_key_is_not_prefixed_twice():
    """The nightly web deployment's Pokemon step: the key carries its dashes already."""
    parts, names = build_script_parameter_parts({"--userinterface": "pokemon-blue-web"})
    assert parts == ["--userinterface", "pokemon-blue-web"]
    assert names == {"userinterface"}


def test_bare_key_gets_the_dashes():
    parts, names = build_script_parameter_parts({"userinterface": "pokemon-blue-web"})
    assert parts == ["--userinterface", "pokemon-blue-web"]
    assert names == {"userinterface"}


def test_host_and_device_are_seen_under_either_spelling():
    """The executor skips its own --host/--device when the step already sets them."""
    _, dashed = build_script_parameter_parts({"--host": "host-clone-1", "--device": "host"})
    _, bare = build_script_parameter_parts({"host": "host-clone-1", "device": "host"})
    assert "host" in dashed and "device" in dashed
    assert "host" in bare and "device" in bare


def test_argparse_accepts_the_built_flags():
    """The guard that matters: the flags argparse sees are the ones the script declares."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--userinterface", type=str, default=None)
    parser.add_argument("--max_duration", type=int, default=None)

    parts, _names = build_script_parameter_parts(
        {"--userinterface": "pokemon-blue-web", "--max_duration": 2000}
    )
    args, unknown = parser.parse_known_args(parts)
    assert unknown == []
    assert args.userinterface == "pokemon-blue-web"
    assert args.max_duration == 2000


def test_empty_and_blank_keys_are_skipped():
    parts, names = build_script_parameter_parts({"--": "x", "  ": "y", "--userinterface": "u"})
    assert parts == ["--userinterface", "u"]
    assert names == {"userinterface"}


def test_no_parameters_gives_no_parts():
    assert build_script_parameter_parts({}) == ([], set())
    assert build_script_parameter_parts(None) == ([], set())
