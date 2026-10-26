"""Tests for the League of Legends walkthrough episode schema (TASK-121 §11.1.2).

Covers:

* :mod:`shared.src.lib.game.leagueoflegends.contracts_episode` (typed schema)
* :mod:`shared.src.lib.game.leagueoflegends.episode_recorder` (in-memory recorder)

No real League client interaction; no ``pyautogui``; no League process names.
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from shared.src.lib.game.leagueoflegends.contracts_episode import (
    LabelEnvelope,
    WalkthroughEpisode,
    WalkthroughFrame,
)
from shared.src.lib.game.leagueoflegends.episode_recorder import EpisodeRecorder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_label(**overrides):
    """Build a valid minimal :class:`LabelEnvelope` payload."""
    payload = {
        "current_step": 1,
        "next_intended_action": "operator launches the Riot Client",
        "expected_outcome": "Riot Client window is in the foreground",
        "operator_note": "",
        "unknown": False,
    }
    payload.update(overrides)
    return payload


def _minimal_frame(frame_id=0, **overrides):
    """Build a valid minimal :class:`WalkthroughFrame` payload."""
    payload = {
        "frame_id": frame_id,
        "frame_hash": "deadbeef",
        "acquired_at_monotonic_ns": 1_000_000_000,
        "source_dimensions": (1280, 720),
        "focus_app": "Riot Client",
        "app_windows_rect": (100, 100, 1280, 720),
        "label": _minimal_label(),
    }
    payload.update(overrides)
    return payload


def _minimal_episode(**overrides):
    """Build a valid minimal :class:`WalkthroughEpisode` payload."""
    payload = {
        "schema_version": "league-episode/v1",
        "episode_id": "walkthrough_20261017_01",
        "operator": "op-anon-001",
        "host_fingerprint": "vpt-win-host-A",
        "started_at_utc": datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc),
        "frames": [],
        "simulator_target_kind": "community-sim",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Schema tests (contracts_episode.py)
# ---------------------------------------------------------------------------


def test_walkthrough_episode_valid_minimal() -> None:
    """An empty-frames episode with all required metadata is accepted."""
    ep = WalkthroughEpisode(**_minimal_episode())

    # Provenance round-trips.
    assert ep.schema_version == "league-episode/v1"
    assert ep.episode_id == "walkthrough_20261017_01"
    assert ep.operator == "op-anon-001"
    assert ep.host_fingerprint == "vpt-win-host-A"
    assert ep.started_at_utc == datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
    assert ep.started_at_utc.tzinfo is not None
    assert ep.started_at_utc.utcoffset().total_seconds() == 0  # UTC

    # No frames yet — the labeler is allowed to instantiate an episode
    # before the first frame arrives.
    assert ep.frames == []

    # Simulator target accepted.
    assert ep.simulator_target_kind == "community-sim"


def test_walkthrough_episode_id_format_required() -> None:
    """``episode_id`` must match ``walkthrough_<YYYYMMDD>_<NN>`` (NN >= 2 digits)."""
    # Accepted: the canonical §11.1.2 form, plus a few-digit counter.
    WalkthroughEpisode(**_minimal_episode(episode_id="walkthrough_20261017_01"))
    WalkthroughEpisode(**_minimal_episode(episode_id="walkthrough_20261017_12"))
    WalkthroughEpisode(**_minimal_episode(episode_id="walkthrough_20261017_999"))

    # Rejected: dashes inside the date, single-digit counter, wrong prefix,
    # and missing counter.
    bad_ids = [
        "walkthrough_2026-10-17_01",  # dashes inside the YYYYMMDD
        "walkthrough_20261017_1",    # single-digit counter (NN >= 2 required)
        "ep_20261017_01",            # wrong prefix
        "walkthrough_20261017",      # missing counter
    ]
    for bad_id in bad_ids:
        with pytest.raises(ValidationError):
            WalkthroughEpisode(**_minimal_episode(episode_id=bad_id))


def test_walkthrough_episode_rejects_simulator_real_league() -> None:
    """``simulator_target_kind="real-league"`` is rejected (defense in depth).

    The :class:`WalkthroughEpisode` Literal excludes ``real-league`` by
    construction; this test pins the boundary so a refactor that
    accidentally widens the Literal (or a typo that picks the wrong string)
    cannot silently reintroduce the real client as an execution target.
    """
    # The Literal ``simulator_target_kind`` is one of the three simulator
    # families — "real-league" must NOT be coerced into any of them.
    with pytest.raises(ValidationError):
        WalkthroughEpisode(
            **_minimal_episode(simulator_target_kind="real-league")
        )

    # And an int is rejected by strict mode (no coercion from 0/1 to a
    # Literal index).
    with pytest.raises(ValidationError):
        WalkthroughEpisode(**_minimal_episode(simulator_target_kind=0))

    # The three allowed families are all accepted.
    for kind in ("community-sim", "custom-moba", "stand-in-game"):
        ep = WalkthroughEpisode(**_minimal_episode(simulator_target_kind=kind))
        assert ep.simulator_target_kind == kind


def test_walkthrough_step_2_through_12_literals() -> None:
    """``current_step`` accepts each of 1-12; rejects 0, 13, -1, "1"."""
    # Every legal step is accepted (covers all 12 branches of the Literal).
    for step in range(1, 13):
        # And the envelope directly: same Literal type.
        env = LabelEnvelope(**_minimal_label(current_step=step))
        assert env.current_step == step

        # The envelope is reachable via WalkthroughFrame too — round-trip
        # so we know the field is wired through both layers.
        frame = WalkthroughFrame(
            **_minimal_frame(
                frame_id=step - 1, label=_minimal_label(current_step=step)
            )
        )
        assert frame.label.current_step == step

    # Every rejected value must raise — including a string "1" that the
    # strict mode will not coerce to the int Literal 1.
    for bad in (0, 13, -1, "1"):
        with pytest.raises(ValidationError):
            LabelEnvelope(**_minimal_label(current_step=bad))


def test_walkthrough_frame_rejects_extra_field() -> None:
    """``extra='forbid'`` blocks unknown keys on :class:`WalkthroughFrame`."""
    with pytest.raises(ValidationError) as excinfo:
        WalkthroughFrame(
            **_minimal_frame(not_a_field="boom"),  # type: ignore[arg-type]
        )
    # The error names the offending key — a future refactor that silently
    # swallows extras would fail this assertion too.
    assert "not_a_field" in str(excinfo.value)

    # And the same guard fires on the inner envelope.
    with pytest.raises(ValidationError):
        LabelEnvelope(**_minimal_label(not_a_field="boom"))  # type: ignore[arg-type]

    # And on the outer episode.
    with pytest.raises(ValidationError):
        WalkthroughEpisode(
            **_minimal_episode(not_a_field="boom"),  # type: ignore[arg-type]
        )


def test_walkthrough_frame_rejects_zero_dimensions() -> None:
    """``source_dimensions`` requires W >= 1 and H >= 1; ``app_windows_rect`` requires non-negative."""
    # Zero width and zero height both rejected.
    with pytest.raises(ValidationError):
        WalkthroughFrame(**_minimal_frame(source_dimensions=(0, 720)))
    with pytest.raises(ValidationError):
        WalkthroughFrame(**_minimal_frame(source_dimensions=(1280, 0)))

    # Negative width / height also rejected (defensive — strict mode already
    # accepts any int, the field validator is the real guard).
    with pytest.raises(ValidationError):
        WalkthroughFrame(**_minimal_frame(source_dimensions=(-1, 720)))

    # Negative ``app_windows_rect`` coordinates rejected too.
    with pytest.raises(ValidationError):
        WalkthroughFrame(**_minimal_frame(app_windows_rect=(-1, 0, 1280, 720)))
    with pytest.raises(ValidationError):
        WalkthroughFrame(**_minimal_frame(app_windows_rect=(0, 0, -1, 720)))

    # Edge case: (1, 1) is accepted (smallest legal capture).
    frame = WalkthroughFrame(
        **_minimal_frame(
            frame_id=0, source_dimensions=(1, 1), app_windows_rect=(0, 0, 1, 1)
        )
    )
    assert frame.source_dimensions == (1, 1)
    assert frame.app_windows_rect == (0, 0, 1, 1)


def test_label_envelope_unknown_true_with_empty_note() -> None:
    """``unknown=True`` with ``operator_note=""`` is accepted.

    Per §11.1.2, ``unknown`` is set when the operator is unsure of the
    current step. An empty operator_note is also a legal reading — they
    may have nothing to add. The schema must not require a note when
    the operator is uncertain.
    """
    env = LabelEnvelope(
        current_step=6,
        next_intended_action="operator adds bots and starts the match",
        expected_outcome="lobby fills, match starts",
        operator_note="",
        unknown=True,
    )
    assert env.unknown is True
    assert env.operator_note == ""
    assert env.current_step == 6


# ---------------------------------------------------------------------------
# Recorder tests (episode_recorder.py)
# ---------------------------------------------------------------------------


def test_walkthrough_frame_monotonic_in_episode_recorder() -> None:
    """``EpisodeRecorder.record`` enforces strictly-monotonic ``frame_id``."""
    rec = EpisodeRecorder(
        episode_id="walkthrough_20261017_01",
        operator="op-anon-001",
        host_fingerprint="vpt-win-host-A",
        simulator_target_kind="community-sim",
    )

    # First frame at frame_id=0 is OK.
    rec.record(WalkthroughFrame(**_minimal_frame(frame_id=0)))
    assert len(rec) == 1

    # Second frame at frame_id=1 (strictly greater) is OK.
    rec.record(WalkthroughFrame(**_minimal_frame(frame_id=1)))
    assert len(rec) == 2

    # Second frame at frame_id=0 (equal to last) is rejected.
    rec2 = EpisodeRecorder(
        episode_id="walkthrough_20261017_02",
        operator="op-anon-001",
        host_fingerprint="vpt-win-host-A",
        simulator_target_kind="community-sim",
    )
    rec2.record(WalkthroughFrame(**_minimal_frame(frame_id=0)))
    with pytest.raises(ValueError):
        rec2.record(WalkthroughFrame(**_minimal_frame(frame_id=0)))

    # Decreasing is also rejected (defense in depth).
    rec3 = EpisodeRecorder(
        episode_id="walkthrough_20261017_03",
        operator="op-anon-001",
        host_fingerprint="vpt-win-host-A",
        simulator_target_kind="community-sim",
    )
    rec3.record(WalkthroughFrame(**_minimal_frame(frame_id=5)))
    with pytest.raises(ValueError):
        rec3.record(WalkthroughFrame(**_minimal_frame(frame_id=3)))


def test_episode_recorder_snapshot_is_independent() -> None:
    """``snapshot()`` returns a deep copy; mutating it does not change the recorder."""
    rec = EpisodeRecorder(
        episode_id="walkthrough_20261017_01",
        operator="op-anon-001",
        host_fingerprint="vpt-win-host-A",
        simulator_target_kind="community-sim",
    )
    rec.record(WalkthroughFrame(**_minimal_frame(frame_id=0)))
    rec.record(WalkthroughFrame(**_minimal_frame(frame_id=1)))

    snap = rec.snapshot()
    assert len(snap.frames) == 2

    # Mutate the snapshot — append a frame, change the operator name.
    snap.frames.append(WalkthroughFrame(**_minimal_frame(frame_id=2)))
    snap_dict = snap.model_dump()
    snap_dict["operator"] = "op-anon-mutated"

    # Recorder's internal state is unchanged: still 2 frames, original operator.
    assert len(rec) == 2
    fresh = rec.snapshot()
    assert len(fresh.frames) == 2
    assert fresh.operator == "op-anon-001"
    assert all(f.frame_id < 100 for f in fresh.frames)


def test_episode_recorder_context_manager() -> None:
    """``EpisodeRecorder`` works as a context manager; ``__exit__`` returns False."""
    rec_ref: dict = {}

    with EpisodeRecorder(
        episode_id="walkthrough_20261017_01",
        operator="op-anon-001",
        host_fingerprint="vpt-win-host-A",
        simulator_target_kind="community-sim",
    ) as rec:
        rec_ref["recorder"] = rec
        rec.record(WalkthroughFrame(**_minimal_frame(frame_id=0)))
        assert len(rec) == 1

    # ``with`` assigned ``rec`` (the return value of __enter__).
    assert rec_ref["recorder"] is rec  # type: ignore[comparison-overlap]

    # After the block, the recorder still works (no resource cleanup needed).
    assert len(rec_ref["recorder"]) == 1

    # __exit__ returns False — genuine exceptions propagate. We exercise
    # this by raising inside the ``with`` body and asserting it bubbles.
    with pytest.raises(RuntimeError, match="boom"):
        with EpisodeRecorder(
            episode_id="walkthrough_20261017_02",
            operator="op-anon-001",
            host_fingerprint="vpt-win-host-A",
            simulator_target_kind="community-sim",
        ) as rec2:
            rec2.record(WalkthroughFrame(**_minimal_frame(frame_id=0)))
            raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Static guard: the two wave-2 modules never import pyautogui or any
# League-process helper (TASK-121 §6 FR-13).
# ---------------------------------------------------------------------------


def test_episode_recorder_never_imports_pyautogui() -> None:
    """AST-walk our two module sources; fail on ``pyautogui`` or League-process substrings.

    We check this two ways:

    1. AST walk over our two modules' sources — fails if either contains an
       ``import pyautogui`` / ``from pyautogui import …`` line, or imports
       from a module whose name contains a League/Riot process substring.
       This is the real guard against accidental coupling.
    2. Attribute presence on the module dict — fails if the import somehow
       sneaks in via a side-effect of another import.

    We deliberately avoid asserting ``"pyautogui" not in sys.modules`` because
    the broader test suite (e.g. ``backend_host`` desktop controllers) is
    free to import it for unrelated reasons; that pollution is not our
    concern.
    """
    import shared.src.lib.game.leagueoflegends.contracts_episode as contracts_mod  # noqa: F401
    import shared.src.lib.game.leagueoflegends.episode_recorder as recorder_mod  # noqa: F401

    # ``pyautogui`` is the one concrete desktop-automation library the
    # brief calls out. The League-process substrings are the ones named
    # in §13 operational safeguards (the windows the agent must never
    # drive) and §6 FR-13 (the real-client helpers).
    forbidden_top_level = {"pyautogui"}
    forbidden_substrings = (
        "RiotClientServices",  # Riot launcher executable
        "LeagueClientUx",      # LCU API client library
        "RiotClient",          # Riot client process / launcher
    )

    def _check_no_forbidden(mod) -> None:
        src = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in forbidden_top_level:
                        pytest.fail(
                            f"{mod.__name__} has 'import {alias.name}' — forbidden by "
                            f"TASK-121 §6 FR-13."
                        )
                    for bad in forbidden_substrings:
                        if bad in alias.name:
                            pytest.fail(
                                f"{mod.__name__} imports '{alias.name}' which references "
                                f"a League/Riot process."
                            )
            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                root = mod_name.split(".")[0]
                if root in forbidden_top_level:
                    pytest.fail(
                        f"{mod.__name__} has 'from {mod_name} import …' — forbidden by "
                        f"TASK-121 §6 FR-13."
                    )
                for bad in forbidden_substrings:
                    if bad in mod_name:
                        pytest.fail(
                            f"{mod.__name__} imports from '{mod_name}' which references "
                            f"a League/Riot process."
                        )

    _check_no_forbidden(contracts_mod)
    _check_no_forbidden(recorder_mod)

    # And the modules must not expose pyautogui as an attribute (defensive).
    assert "pyautogui" not in contracts_mod.__dict__
    assert "pyautogui" not in recorder_mod.__dict__