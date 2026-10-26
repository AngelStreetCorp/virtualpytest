"""Typed contract for the League of Legends Practice Tool lobby observation.

This is the bot's typed vocabulary for walkthrough §11.1.1 step 6
("operator adds bots and starts the match; VPT records the lobby frame").
The detector in :mod:`vision_lobby` currently returns placeholder values;
this module pins the schema so downstream code (event-triggered strategy,
fixture labeler, replay runner) has a stable shape to validate against.

Hard policy (TASK-121 §6 FR-13, §8):

* The real League client is a human-played data source only.
* The detector MUST never import ``pyautogui`` or any League-process helper.
* ``extra='forbid'`` so the schema cannot be silently extended by an LLM.
* ``strict=True`` so type coercion (string→int, bool→int, …) is impossible.
* ``schema_version`` is a single literal; future shapes must bump the version.
"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Stable enums (kept module-level so tests and labeler code can import them).
# ---------------------------------------------------------------------------

MatchType = Literal[
    "practice_tool",
    "normal_draft",
    "normal_blind",
    "ranked_solo",
    "aram",
    "other",
    "unknown",
]

Side = Literal["Blue", "Red", None]

Role = Literal["top", "jungle", "mid", "bot", "support", None]


# ---------------------------------------------------------------------------
# Frame-derived fields a real detector would need to populate.
# These are the names that appear in ``unknown_fields`` whenever the stub
# cannot read them from the frame. Listed in a stable order so reports
# diff deterministically.
# ---------------------------------------------------------------------------

_FRAMES_DERIVED_FIELDS: tuple[str, ...] = (
    "match_type",
    "side",
    "role_locked",
    "bots_player_side",
    "bots_enemy_side",
    "human_players_player_side",
    "human_players_enemy_side",
    "start_button_enabled",
    "lobby_full",
    "confidence",
)


# ---------------------------------------------------------------------------
# The observation model.
# ---------------------------------------------------------------------------


class LobbyObservation(BaseModel):
    """Typed reading of one League Practice Tool lobby frame.

    Schema: ``league-lobby/v1``.

    The default-filled fields (``match_type='unknown'``, ``side=None``,
    ``role_locked=None``, ``bots_*_side=0``, ``human_players_*_side=0``,
    ``start_button_enabled=False``, ``lobby_full=False``, ``confidence=0.0``,
    ``unknown_fields=[]``) describe the *no information* reading: a detector
    that has not yet produced any per-frame classification MUST emit exactly
    these defaults and MUST list every detector-derived field name in
    ``unknown_fields``.

    Field rationale (TASK-121 §11.1.1 step 6):

    * ``side`` is ``None`` until the client has assigned the operator to a
      side. ``role_locked`` is ``None`` until the operator (per the operator's
      spec) locks a role; the agent never drives the role lock.
    * ``bots_*_side`` / ``human_players_*_side`` are integer counts of lobby
      slots, not of champions selected. Practice-tool lobbies fill with
      bots up to ``1 + bots_per_side``.
    * ``start_button_enabled`` is the client-side gate that confirms all
      required slots are filled; ``lobby_full`` is the operator-side reading
      that all ten slots are filled. Both must be present and consistent.
    * ``unknown_fields`` lists field names the detector could not read from
      the frame (occlusion, off-screen, mid-transition). The downstream
      policy uses this to decide between ``WAIT`` and ``ABSTAIN``.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    # ---- provenance (provided by the capture adapter) -----------------
    schema_version: Literal["league-lobby/v1"]
    observation_id: str = Field(min_length=1)
    captured_at_monotonic_ns: int = Field(ge=0)
    frame_hash: str = Field(min_length=1)

    # ---- classifier outputs (per-frame detection) ---------------------
    match_type: MatchType = "unknown"
    side: Side = None
    role_locked: Role = None
    bots_player_side: int = Field(default=0, ge=0, le=4)
    bots_enemy_side: int = Field(default=0, ge=0, le=4)
    human_players_player_side: int = Field(default=0, ge=0, le=5)
    human_players_enemy_side: int = Field(default=0, ge=0, le=5)
    start_button_enabled: bool = False
    lobby_full: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    unknown_fields: List[str] = Field(default_factory=list)


__all__ = [
    "LobbyObservation",
    "MatchType",
    "Side",
    "Role",
]