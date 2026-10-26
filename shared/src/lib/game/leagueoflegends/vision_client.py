"""Client-window-vision stub for the League of Legends launch flow (§11.1.1).

The real Riot / League client is a **human-played data source only**. This
module is a typed placeholder detector: it validates its input frame,
returns a :class:`ClientObservation` populated with ``unknown`` defaults,
and reports every frame-derived field as undetermined in ``unknown_fields``.

A real detector (later) will replace :meth:`ClientVision.observe`. Until
then this stub gives downstream code a stable surface to integrate against
without depending on private League state.

Hard policy (TASK-121 §6 FR-13):

* No ``pyautogui`` import anywhere in this module's source.
* No ``subprocess`` call against any League / Riot process name.
* No file-system writes; the stub is pure and deterministic.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import numpy as np

from shared.src.lib.game.leagueoflegends.contracts_client import (
    ClientObservation,
)


# Placeholder frame hash emitted when the stub has no real frame to hash.
# We never claim it's a cryptographic hash; it's a stable marker so reports
# can group stub emissions deterministically.
_STUB_FRAME_HASH = "<stub-client-no-real-detector>"


class ClientVision:
    """Typed stub detector for the League/Riot client-window frame.

    The ``__init__`` accepts an optional ``detector`` placeholder. The stub
    never calls the detector — it returns the typed ``unknown`` observation
    directly. A future revision can swap the implementation for one that
    routes a real frame through a CV / OCR / vision-LLM pipeline without
    changing the public surface.
    """

    def __init__(self, detector: Optional[Any] = None) -> None:
        # Placeholder: stored so tests can introspect wiring.
        self._detector = detector

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe(
        self,
        frame: Optional[np.ndarray],
        window_title: Optional[str] = None,
    ) -> ClientObservation:
        """Validate ``frame`` and return a typed ``unknown`` observation.

        Parameters
        ----------
        frame:
            Either ``None`` (no frame supplied — caller is mid-transition
            or the capture pipe returned nothing) or a 3-D ``uint8``
            ``numpy.ndarray`` (an H×W×C frame in BGR/RGB). Any other shape
            or dtype raises :class:`TypeError` / :class:`ValueError`.
        window_title:
            Optional raw OS window title. The stub does not interpret it —
            it is captured verbatim into ``window_title`` so reports can
            correlate observations with foreground-app state in traces.

        Returns
        -------
        ClientObservation
            A schema-versioned observation with every frame-derived field
            set to its ``unknown`` / ``None`` / ``False`` / ``[]`` default
            and every such field name listed in ``unknown_fields``.
        """
        self._validate_frame(frame)

        # frame_hash placeholder: same marker regardless of frame content
        # until a real detector is wired in. Keeping it constant makes
        # stub-driven fixtures deterministic.
        return ClientObservation(
            schema_version="league-client/v1",
            observation_id=str(uuid.uuid4()),
            captured_at_monotonic_ns=time.monotonic_ns(),
            frame_hash=_STUB_FRAME_HASH,
            window_title=window_title,
            unknown_fields=list(_UNKNOWN_FIELD_NAMES),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_frame(frame: Optional[np.ndarray]) -> None:
        """Reject anything that is not ``None`` or a 3-D uint8 ndarray."""
        if frame is None:
            return
        if not isinstance(frame, np.ndarray):
            raise TypeError(
                f"frame must be a numpy.ndarray or None, got {type(frame).__name__}"
            )
        if frame.dtype != np.uint8:
            raise ValueError(f"frame dtype must be uint8, got {frame.dtype}")
        if frame.ndim != 3:
            raise ValueError(f"frame must be 3-D (H x W x C), got ndim={frame.ndim}")


# Frame-derived fields the stub cannot read. Mirrors the enum in
# ``contracts_client`` but duplicated here to avoid an import cycle when
# downstream labelers introspect the stub.
_UNKNOWN_FIELD_NAMES: tuple[str, ...] = (
    "active_window",
    "logged_in",
    "lol_ready",
    "practice_tool_open",
    "play_view_open",
    "product_tiles_visible",
    "window_title",
    "confidence",
)


__all__ = ["ClientVision"]