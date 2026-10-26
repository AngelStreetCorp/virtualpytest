"""Typed Python-side recorder for a League of Legends walkthrough episode.

This module is the in-memory companion to
:mod:`shared.src.lib.game.leagueoflegends.contracts_episode`. The recorder
collects :class:`WalkthroughFrame` records as the capture adapter feeds them
in, enforces the per-episode invariants the schema cannot enforce on its
own (``frame_id`` strictly monotonic across the episode), and hands back a
:class:`WalkthroughEpisode` snapshot.

Hard policy (TASK-121 §6 FR-13, §8, §13):

* The recorder is a typed Python object lifecycle. **No** file I/O. **No**
  network. **No** real-client driving. **No** ``pyautogui``.
* ``record()`` enforces the strictly-monotonic ``frame_id`` invariant by
  raising ``ValueError`` on equal / decreasing IDs — defense in depth so a
  buggy capture adapter cannot silently overwrite earlier labels.
* ``snapshot()`` returns a **deep copy**: the caller can mutate the returned
  episode (e.g. sort, trim, redact) without disturbing the recorder's
  internal state.
* The recorder is a context manager (``__enter__`` / ``__exit__``) for
  ergonomic use in run operators and tests; ``__exit__`` returns ``False``
  so genuine exceptions are not swallowed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from shared.src.lib.game.leagueoflegends.contracts_episode import (
    SimulatorTargetKind,
    WalkthroughEpisode,
    WalkthroughFrame,
)


class EpisodeRecorder:
    """In-memory recorder for a single walkthrough episode (§11.1.2).

    The recorder holds the episode-level metadata in a typed
    :class:`WalkthroughEpisode` and accumulates frames via :meth:`record`.
    The metadata (``episode_id``, ``operator``, ``host_fingerprint``,
    ``simulator_target_kind``, ``started_at_utc``) is set once at
    construction; the frames list grows over time.

    Per-episode invariants enforced by this class:

    * ``frame_id`` is strictly monotonic across ``record()`` calls.
    * ``snapshot()`` returns a deep copy — mutating the returned episode
      does not affect the recorder's internal state.

    Example::

        with EpisodeRecorder(
            episode_id="walkthrough_20261017_01",
            operator="op-anon-001",
            host_fingerprint="vpt-win-host-A",
            simulator_target_kind="community-sim",
        ) as rec:
            rec.record(frame_zero)
            rec.record(frame_one)
            ep = rec.snapshot()
    """

    def __init__(
        self,
        episode_id: str,
        operator: str,
        host_fingerprint: str,
        simulator_target_kind: SimulatorTargetKind | str,
    ) -> None:
        # Validate the user-supplied metadata up front via the schema. This
        # catches off-format episode IDs and excluded simulator_target_kind
        # values (``real-league``) at construction time rather than at the
        # first ``snapshot()`` call.
        #
        # The two metadata fields the caller does NOT supply are derived:
        #
        # * ``schema_version`` is always the current contract literal
        #   (``league-episode/v1``). A future shape change must bump the
        #   version here and in the schema.
        # * ``started_at_utc`` is captured once at construction time in
        #   UTC. The recorder treats it as the "wall clock" timestamp of
        #   the operator's walkthrough, which is what the spec asks for
        #   in §11.1.2 (the episode ID encodes the calendar day; this
        #   field encodes the time-of-day).
        self._episode: WalkthroughEpisode = WalkthroughEpisode(
            schema_version="league-episode/v1",
            episode_id=episode_id,
            operator=operator,
            host_fingerprint=host_fingerprint,
            started_at_utc=datetime.now(timezone.utc),
            frames=[],
            simulator_target_kind=simulator_target_kind,  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------------
    # Recording API.
    # ------------------------------------------------------------------

    def record(self, frame: WalkthroughFrame) -> None:
        """Append a frame to the episode.

        Raises ``ValueError`` if ``frame.frame_id`` is **not strictly
        greater** than the last recorded ``frame_id`` (or, on the first
        record, the frame's ``frame_id`` is not >= 0). The strict-monotonic
        guarantee is what lets the labeler trust that frame ordering inside
        an episode mirrors acquisition order.
        """
        frames: List[WalkthroughFrame] = self._episode.frames
        if frames:
            last_id = frames[-1].frame_id
            if frame.frame_id <= last_id:
                raise ValueError(
                    f"frame_id must be strictly greater than the last "
                    f"recorded frame_id ({last_id}); got {frame.frame_id}"
                )
        # Pydantic models are validated at construction (the WalkthroughFrame
        # passed in by the caller is already valid). We append a shallow
        # reference — frames are immutable in practice (pydantic models
        # default to frozen=False, but our callers do not mutate them after
        # record()), so a shallow reference is enough.
        frames.append(frame)

    def snapshot(self) -> WalkthroughEpisode:
        """Return a **deep copy** of the current episode.

        Mutating the returned episode (e.g. trimming frames, redacting the
        operator note) MUST NOT change the recorder's internal state. This
        is the boundary between the in-memory record and any downstream
        persistence / serialization layer.
        """
        return self._episode.model_copy(deep=True)

    # ------------------------------------------------------------------
    # Convenience / protocol dunder methods.
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Return the number of frames recorded so far."""
        return len(self._episode.frames)

    def __enter__(self) -> "EpisodeRecorder":
        """Enter the runtime context; returns ``self``."""
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        """Exit the runtime context.

        Returns ``False`` so genuine exceptions propagate — we deliberately
        do not swallow errors. The recorder has no resources to release (no
        file handles, no sockets, no threads) so cleanup is a no-op.
        """
        return False


__all__ = ["EpisodeRecorder"]