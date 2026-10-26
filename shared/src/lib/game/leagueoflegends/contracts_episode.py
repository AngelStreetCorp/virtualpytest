"""Typed contract for the League of Legends human-played walkthrough episode.

This is the **operator-side** typed vocabulary for walkthrough §11.1.1 (the
12-step reference walkthrough) and §11.1.2 (the capture contract). One full
operator run = one labeled episode; the agent never executes any of the 12
steps, it only trains on the resulting frames and labels.

The data source is human-driven (TASK-121 §6 FR-13, §13 operational
safeguards): the operator runs the practice-tool Garen match and VPT records
the labeled frames. The agent's autonomous play happens **only** against an
offline simulator target (§11.1.3, ``simulator_target_kind`` is therefore
constrained to ``{community-sim, custom-moba, stand-in-game}`` — never
``real-league``).

Hard policy (TASK-121 §6 FR-13, §8, §13):

* The real League client is a human-played data source only.
* The schema MUST never import ``pyautogui`` or any League-process helper.
* ``extra='forbid'`` so the schema cannot be silently extended by an LLM.
* ``strict=True`` so type coercion (string→int, bool→int, …) is impossible.
* ``schema_version`` is a single literal; future shapes must bump the version.
* ``simulator_target_kind`` is a literal that excludes ``real-league`` —
  defense in depth so a refactor cannot silently reintroduce the real client
  as the simulator target.
* No ``policy_mode`` field: this is human-driven, not agent-driven.

``SimulatorTargetKind`` is re-exported from :mod:`contracts_simulator`; that
module is the canonical home for the literal (§11.1.3). The
``WalkthroughEpisode`` field type stays identical so existing call sites and
validators do not change.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Literal, Tuple

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from .contracts_simulator import SimulatorTargetKind  # canonical home, FR-15


# ---------------------------------------------------------------------------
# Stable enums (kept module-level so tests and labeler code can import them).
# ---------------------------------------------------------------------------

# The 12 walkthrough steps in §11.1.1. Each step names the operator's action
# and the artifact VPT records (e.g. step 1 = "operator launches the Riot
# Client"; step 6 = "operator adds bots and starts the match").
WalkthroughStep = Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]


# ---------------------------------------------------------------------------
# Episode-level constants.
# ---------------------------------------------------------------------------

# The episode ID format is ``walkthrough_<YYYYMMDD>_<NN>``. We enforce that
# format with a regex so a labeler or test harness cannot silently generate
# an off-format episode (e.g. ``walkthrough_2026-10-17_01`` with dashes,
# ``walkthrough_20261017_1`` with a single-digit counter).
_EPISODE_ID_PATTERN = r"^walkthrough_[0-9]{8}_[0-9]{2,}$"


# ---------------------------------------------------------------------------
# The label envelope (§11.1.2 capture contract).
# ---------------------------------------------------------------------------


class LabelEnvelope(BaseModel):
    """The operator's per-frame annotation (§11.1.2).

    ``current_step`` is the operator's reading of which of the 12 walkthrough
    steps this frame belongs to. ``next_intended_action`` / ``expected_outcome``
    are the operator's free-text descriptions (1..300 chars; long enough to
    describe a step but short enough to keep the file readable).
    ``operator_note`` is the analyst-side note: never ingested into a vision
    LLM (§11.1.2), allowed to be empty (the operator may have nothing to add).
    ``unknown`` is set when the operator cannot determine the current step —
    this is a normal reading, not an error.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    current_step: WalkthroughStep
    next_intended_action: str = Field(min_length=1, max_length=300)
    expected_outcome: str = Field(min_length=1, max_length=300)
    operator_note: str = Field(default="", min_length=0, max_length=1000)
    unknown: bool = False


# ---------------------------------------------------------------------------
# The frame record.
# ---------------------------------------------------------------------------


class WalkthroughFrame(BaseModel):
    """One labeled frame inside a walkthrough episode (§11.1.2).

    Schema: ``league-episode/v1`` (carried by the parent episode).

    ``frame_id`` is a per-episode monotonic counter. ``frame_hash`` and
    ``acquired_at_monotonic_ns`` are the capture adapter's provenance.
    ``source_dimensions`` is the (W, H) of the captured bitmap.
    ``focus_app`` is the OS-level foreground window title (or a stable
    alias) — never an authoritative state signal, only an analyst trace.
    ``app_windows_rect`` is the (x, y, w, h) bounding rect of the
    foreground window at capture time.

    The label envelope is the operator's annotation; the schema deliberately
    has **no** ``policy_mode`` field — this is human-driven, not agent-driven.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    frame_id: int = Field(ge=0)
    frame_hash: str = Field(min_length=1)
    acquired_at_monotonic_ns: int = Field(ge=0)
    source_dimensions: Tuple[int, int]
    focus_app: str = Field(min_length=1)
    app_windows_rect: Tuple[int, int, int, int]
    label: LabelEnvelope

    @field_validator("source_dimensions")
    @classmethod
    def _dims_positive(cls, v: Tuple[int, int]) -> Tuple[int, int]:
        # ``W`` and ``H`` must be >= 1 — a 0-pixel capture is meaningless and
        # the downstream labeler would happily index into an empty array.
        w, h = v
        if w < 1 or h < 1:
            raise ValueError("source_dimensions (W, H) must both be >= 1")
        return v

    @field_validator("app_windows_rect")
    @classmethod
    def _rect_non_negative(cls, v: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        # ``x``, ``y``, ``w``, ``h`` must be >= 0. The OS can report a
        # negative ``x``/``y`` for a multi-monitor setup, but a negative
        # ``w``/``h`` is always a capture-side error; we forbid both to keep
        # the downstream crop math branch-free.
        x, y, w, h = v
        if x < 0 or y < 0 or w < 0 or h < 0:
            raise ValueError("app_windows_rect (x, y, w, h) must all be >= 0")
        return v


# ---------------------------------------------------------------------------
# The episode container.
# ---------------------------------------------------------------------------


class WalkthroughEpisode(BaseModel):
    """One full operator run = one labeled episode (§11.1.2).

    Schema: ``league-episode/v1``.

    The episode ID format is ``walkthrough_<YYYYMMDD>_<NN>`` (e.g.
    ``walkthrough_20261017_01``). ``operator`` is an anonymized handle (the
    spec never carries real account names or chat). ``host_fingerprint`` is
    the vpt-windows host identifier (so a re-run on a different box can be
    distinguished without exposing any Windows-internal names).

    ``started_at_utc`` is timezone-aware UTC. ``frames`` can be empty — a
    labeler is allowed to instantiate an episode before the first frame
    arrives.

    ``simulator_target_kind`` names the operator's selected simulator for
    this episode (§11.1.3): the agent will later train / evaluate against
    this target. The Literal excludes ``real-league`` by construction.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["league-episode/v1"]
    episode_id: str = Field(min_length=1, pattern=_EPISODE_ID_PATTERN)
    operator: str = Field(min_length=1)
    host_fingerprint: str = Field(min_length=1)
    started_at_utc: AwareDatetime
    frames: List[WalkthroughFrame] = Field(default_factory=list)
    simulator_target_kind: SimulatorTargetKind

    @field_validator("started_at_utc")
    @classmethod
    def _utc_only(cls, v: datetime) -> datetime:
        # ``AwareDatetime`` already blocks naive datetimes; this validator
        # adds the UTC requirement so a future audit can rely on a single
        # timezone across every recorded episode.
        if v.utcoffset() != timedelta(0):
            raise ValueError(
                "started_at_utc must be timezone-aware UTC (offset == 0)"
            )
        return v


__all__ = [
    "WalkthroughStep",
    "SimulatorTargetKind",
    "LabelEnvelope",
    "WalkthroughFrame",
    "WalkthroughEpisode",
]