"""Typed contract for the League of Legends client-window observation.

This is the bot's typed vocabulary for walkthrough §11.1.1 steps 2-4
("operator launches the Riot Client", "operator clicks the LoL tile",
"operator clicks the PLAY button"). The detector in :mod:`vision_client`
currently returns placeholder values; this module pins the schema so
downstream code (event-triggered strategy, fixture labeler, replay runner)
has a stable shape to validate against.

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

ActiveWindow = Literal[
    "riot_client",
    "lol_client",
    "lol_in_game",
    "lol_champ_select",
    "lol_loading",
    "lol_shop",
    "lol_end_screen",
    "other",
    "unknown",
]

LoggedIn = Literal["yes", "no", "unknown"]

ProductTile = Literal[
    "valorant",
    "league_of_legends",
    "teamfight_tactics",
    "wild_rift",
    "other",
]


# ---------------------------------------------------------------------------
# Frame-derived fields a real detector would need to populate.
# These are the names that appear in ``unknown_fields`` whenever the stub
# cannot read them from the frame. Listed in a stable order so reports
# diff deterministically.
# ---------------------------------------------------------------------------

_FRAME_DERIVED_FIELDS: tuple[str, ...] = (
    "active_window",
    "logged_in",
    "lol_ready",
    "practice_tool_open",
    "play_view_open",
    "product_tiles_visible",
    "window_title",
    "confidence",
)


# ---------------------------------------------------------------------------
# The observation model.
# ---------------------------------------------------------------------------


class ClientObservation(BaseModel):
    """Typed reading of one League/Riot client-window frame.

    Schema: ``league-client/v1``.

    The default-filled fields (``active_window='unknown'``,
    ``logged_in='unknown'``, ``lol_ready=None``, ``practice_tool_open=None``,
    ``play_view_open=None``, ``product_tiles_visible=[]``,
    ``window_title=None``, ``confidence=0.0``, ``unknown_fields=[]``) describe
    the *no information* reading: a detector that has not yet produced any
    per-frame classification MUST emit exactly these defaults and MUST list
    every detector-derived field name in ``unknown_fields``.

    Field rationale (TASK-121 §11.1.1 steps 2-4):

    * ``active_window`` names the foreground window the VPT agent observes.
      The Riot Client is ``riot_client``; the LoL launcher/client landing
      page is ``lol_client``; in-match states are ``lol_in_game``,
      ``lol_champ_select``, ``lol_loading``, ``lol_shop``, ``lol_end_screen``.
      ``other`` / ``unknown`` cover foreground drift (e.g. desktop) and
      pre-detection readings.
    * ``logged_in`` is tri-state (``yes``/``no``/``unknown``) because the
      Riot Client login screen has its own visual fingerprint distinct from
      a logged-out desktop.
    * ``lol_ready`` flips to ``True`` once the LoL launcher hands off to the
      League client (the walkthrough step 3 handoff). It is ``None`` while
      undecided — ``False`` would be ambiguous (could mean "checked, not
      ready" or "never checked").
    * ``practice_tool_open`` is the §11.1.1 step 5 indicator (only enabled
      match option). ``play_view_open`` is the §11.1.1 step 4 indicator
      (PLAY → queues view). Both are ``None`` until the detector sees the
      relevant frame.
    * ``product_tiles_visible`` enumerates the Riot Client product tiles
      visible on screen (Valorant, League of Legends, Teamfight Tactics,
      Wild Rift). ``other`` catches unrecognized tiles (e.g. a Riot region-
      specific title). Empty list means "no tiles visible yet" — the
      operator may not yet be logged in.
    * ``window_title`` is the raw OS window title (useful for trace logs;
      never an authoritative state signal).
    * ``unknown_fields`` lists field names the detector could not read from
      the frame (occlusion, off-screen, mid-transition). The downstream
      policy uses this to decide between ``WAIT`` and ``ABSTAIN``.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    # ---- provenance (provided by the capture adapter) -----------------
    schema_version: Literal["league-client/v1"]
    observation_id: str = Field(min_length=1)
    captured_at_monotonic_ns: int = Field(ge=0)
    frame_hash: str = Field(min_length=1)

    # ---- classifier outputs (per-frame detection) ---------------------
    active_window: ActiveWindow = "unknown"
    logged_in: LoggedIn = "unknown"
    lol_ready: bool | None = None
    practice_tool_open: bool | None = None
    play_view_open: bool | None = None
    product_tiles_visible: List[ProductTile] = Field(default_factory=list)
    window_title: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    unknown_fields: List[str] = Field(default_factory=list)


__all__ = [
    "ClientObservation",
    "ActiveWindow",
    "LoggedIn",
    "ProductTile",
]