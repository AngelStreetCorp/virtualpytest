"""Typed contract for the League of Legends offline-simulator target (TASK-121).

This module pins the **typed shape of the offline target** the agent plays
against (§11.1.3). The agent never executes anything against the real Riot /
League client — that is the FR-15 hard gate — and the schema is built so that
``real-league`` cannot be a valid ``target_kind``: the :data:`SimulatorTargetKind`
literal deliberately lists only the three allowed kinds and ``real-league`` is
absent. The companion registry (:mod:`simulator_registry`) applies the same
gate at registration time.

Hard policy (TASK-121 §6 FR-15, §11.1.3):

* The real League client is never an execution target — only a human-played
  data source (FR-13). The agent's autonomous play happens **only** against
  one of the three allowed kinds.
* ``target_kind`` is a literal that excludes ``real-league`` — the FR-15
  hard gate. Defense in depth: an additional ``@model_validator`` ensures a
  ``community-sim`` target with a ``rejected`` license review cannot be
  registered, and an ``@field_validator`` rejects ``exe_path`` values that
  point at any known Riot / League binary (so a misconfigured target that
  sneaks past the literal gate is still caught at construction).
* The schema MUST never import ``pyautogui`` or any League-process helper.
* ``extra='forbid'`` so the schema cannot be silently extended by an LLM.
* ``strict=True`` so type coercion (string→int, bool→int, …) is impossible.
* ``schema_version`` is a single literal; future shapes must bump the version.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Stable enums (kept module-level so tests and runner code can import them).
# ---------------------------------------------------------------------------

# The three allowed simulator target kinds (§11.1.3). ``real-league`` is
# deliberately absent: the agent's autonomous play must never target the real
# Riot / League client (TASK-121 §6 FR-15). This Literal is the FR-15 hard
# gate — anything outside the three members is rejected at construction time.
SimulatorTargetKind = Literal[
    "community-sim",  # existing community LoL replay / sim harness
    "custom-moba",  # custom-built minimal MOBA simulator
    "stand-in-game",  # existing VPT game target reused as a stop-gap
]


# License review verdict for the upstream tool. ``self-built`` is the
# "we own the source, no upstream review required" sentinel; ``unknown``
# is the "we haven't checked yet" default.
LicenseReviewStatus = Literal[
    "approved",
    "pending",
    "rejected",
    "self-built",
    "unknown",
]


# ---------------------------------------------------------------------------
# Forbidden exe_path substrings (defense in depth).
#
# ``FR-15`` says the registry MUST refuse real-league targets. The Literal
# gate on ``target_kind`` is the primary defense. If a misconfigured target
# somehow slips past it (e.g. someone hand-crafts an executor that bypasses
# the schema), the ``exe_path`` substring check is the second line: any path
# pointing at a known Riot / League binary is refused at construction time.
#
# Kept module-level (and re-exported via :mod:`simulator_registry`) so the
# runner can import the same tuple without duplicating the strings.
# ---------------------------------------------------------------------------

FORBIDDEN_EXE_SUBSTRINGS: tuple[str, ...] = (
    "riotclientservices",  # the Riot Client launcher executable
    "leagueclientux",  # the LCU API client library / executable
    "league of legends",  # the game install folder name
    "riot games\\riot client",  # the canonical launcher folder on Windows
)


# ---------------------------------------------------------------------------
# The target model.
# ---------------------------------------------------------------------------


class SimulatorTarget(BaseModel):
    """Typed description of one offline-simulator target the agent may play against.

    Schema: ``league-simulator/v1``.

    Field rationale (TASK-121 §11.1.3, §6 FR-15):

    * ``target_kind`` is the FR-15 hard gate. Any value outside the three
      allowed kinds — including ``real-league`` — is rejected by the Literal
      type. There is no ``"real-league"`` member to "opt into".
    * ``target_id`` is an opaque, caller-chosen identifier for the specific
      simulator instance. The registry uses it as the key and is idempotent
      on it (re-registering the same id replaces; a different id adds).
    * ``display_name`` is the human-readable name shown in the UI / reports.
    * ``license_review_url`` + ``license_review_status`` are the FR-15
      license review for community targets. A ``community-sim`` target with
      ``license_review_status="rejected"`` is refused by the model validator.
      Self-built targets (``target_kind="custom-moba"`` we own) are expected
      to set ``license_review_status="self-built"`` and a non-empty
      ``build_commit_sha`` so the runner can show what was actually built.
    * ``build_commit_sha`` is required for ``custom-moba`` (we own it, we
      must know what we built). For ``community-sim`` and ``stand-in-game``
      targets we don't control, it is allowed to be ``None``.
    * ``exe_path`` is optional — not every simulator target has a binary
      path on this host (some are pure-process or remote). The substring
      check below is the FR-15 defense-in-depth layer: an empty / unrelated
      path is fine; a path that *names* a real Riot / League binary is not.
    * ``validation_metrics_url`` is the link to a recent evaluation report
      so an operator can audit whether the target is healthy before letting
      the agent loose on it.
    * ``notes`` is a free-text operator note (0..1000 chars) — not parsed,
      only shown in the UI / reports.

    The field validator (``exe_path``) and model validator (license review /
    build sha) catch the three refusal modes FR-15 calls out: wrong kind,
    rejected license, misconfigured exe path. Each refusal raises a
    ``ValueError`` at construction time so a misuse cannot reach the runner.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    # ---- provenance ----------------------------------------------------
    schema_version: Literal["league-simulator/v1"]
    target_kind: SimulatorTargetKind
    target_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)

    # ---- license review (FR-15) ---------------------------------------
    license_review_url: str | None = None
    license_review_status: LicenseReviewStatus = "unknown"

    # ---- provenance of the simulator itself ---------------------------
    build_commit_sha: str | None = None
    exe_path: str | None = None
    validation_metrics_url: str | None = None
    notes: str = Field(default="", min_length=0, max_length=1000)

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("exe_path")
    @classmethod
    def _no_real_league_exe_path(cls, v: str | None) -> str | None:
        """Reject any ``exe_path`` that points at a known Riot / League binary.

        This is the **FR-15 defense-in-depth check**. The Literal on
        ``target_kind`` already excludes ``"real-league"``, so a real client
        is supposed to be unreachable — but a misconfigured target that
        slips past the literal (e.g. an external runner that constructs the
        model via ``model_construct``) is still caught here as long as the
        path string names one of the forbidden substrings.

        The check is case-insensitive (Windows paths are case-insensitive in
        practice, and the lowercased substring match keeps the gate uniform).
        """
        if v is None:
            return None
        lowered = v.lower()
        for bad in FORBIDDEN_EXE_SUBSTRINGS:
            if bad in lowered:
                raise ValueError(
                    "SimulatorTarget.exe_path points at a real League "
                    "process; refused"
                )
        return v

    @model_validator(mode="after")
    def _kind_specific_constraints(self) -> "SimulatorTarget":
        """Enforce the per-kind constraints the literal gate does not express.

        * ``community-sim`` + ``license_review_status == "rejected"`` is
          refused (FR-15: a rejected upstream review cannot be registered).
        * ``custom-moba`` + ``build_commit_sha is None`` is refused: we own
          a custom-built simulator and must know what we built, so the SHA
          is mandatory (a ``None`` here means we forgot to pin it).
        * ``stand-in-game`` has no extra constraint beyond the ``exe_path``
          check above.
        """
        kind = self.target_kind
        if kind == "community-sim" and self.license_review_status == "rejected":
            raise ValueError(
                "community-sim target rejected by license review; refused"
            )
        if kind == "custom-moba" and self.build_commit_sha is None:
            raise ValueError("custom-moba requires build_commit_sha")
        return self


__all__ = [
    "SimulatorTargetKind",
    "LicenseReviewStatus",
    "SimulatorTarget",
    "FORBIDDEN_EXE_SUBSTRINGS",
]
