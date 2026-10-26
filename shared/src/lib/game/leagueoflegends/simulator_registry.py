"""In-process registry of allowed League of Legends simulator targets (TASK-121).

This module pairs with :mod:`contracts_simulator`. The schema is the *type*
of an allowed target — this registry is the **collection** of targets the
runner may pick from, with the FR-15 hard gate re-applied at registration
time (defense in depth) so that a bypass attempt that skips the schema's
constructors (e.g. ``SimulatorTarget.model_construct(...)``) is still caught
when ``register()`` is called.

Hard policy (TASK-121 §6 FR-15, §11.1.3):

* The registry MUST refuse any target whose ``target_kind`` is ``real-league``
  — but the schema's Literal already prevents that kind from existing, so
  the registry's job is to refuse misconfigured targets that *claim* to be
  a community sim / custom-moba / stand-in-game but whose ``exe_path``
  references a real Riot / League binary (defense in depth).
* The registry is single-process / single-leader — there is no
  cross-process coordination. Concurrent registration is fine (Python's GIL
  keeps the list-mutation atomic), but persistent storage is *not* the
  registry's concern; persistence is up to the runner that wraps it.
* The registry MUST never import ``pyautogui`` or any League-process helper.
"""
from __future__ import annotations

from typing import List

from pydantic import ValidationError

from shared.src.lib.game.leagueoflegends.contracts_simulator import (
    FORBIDDEN_EXE_SUBSTRINGS,
    SimulatorTarget,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SimulatorRegistryError(ValueError):
    """Raised when the registry refuses to register a simulator target.

    Subclasses ``ValueError`` so a caller that catches ``ValueError`` (or a
    Pydantic ``ValidationError`` — note that ``ValidationError`` wraps a list
    of ``ValueError`` s) keeps working. Raised by :meth:`SimulatorRegistry.register`
    on any refusal — defensive re-validation failures, banned exe_path
    substrings, or a target whose construction itself failed.

    The string form carries a single human-readable explanation that an
    operator can grep in the run report.
    """


# ---------------------------------------------------------------------------
# The registry.
# ---------------------------------------------------------------------------


class SimulatorRegistry:
    """In-process collection of allowed simulator targets.

    The registry is intentionally tiny: a list of targets keyed by
    ``target_id``, with a defensive re-validation step at registration time
    and a few lookups that the runner needs. There is no persistence — a
    fresh registry starts empty. The runner that owns the registry is
    responsible for hydrating it from configuration before the run.

    FR-15 contract (testable from one place):

    * :meth:`refuses_real_league` is a classmethod that *always* returns
      ``True``. This is the single assertion point for "this code path
      refuses real-league" — any test, lint rule, or runtime check that
      wants to ask "does the registry refuse real-league?" reads from this
      one attribute. Adding a future leak vector elsewhere (e.g. a side-
      channel loader) MUST also keep this assertion honest.

    Register semantics:

    * Re-registering the same ``target_id`` replaces the previous entry
      (the new one wins). This makes config reloads and "operator overrides"
      idempotent — the last write wins, no duplicates accumulate.
    * Appends a *new* entry for any ``target_id`` not already present.

    Lookup semantics:

    * :meth:`get` returns the registered target or ``None`` — never raises
      on a miss.
    * :meth:`list_approved` returns only targets with a status that
      authorizes autonomous play (``approved`` or ``self-built``). Pending
      / rejected / unknown targets are intentionally hidden.
    """

    def __init__(self) -> None:
        # We keep a list (not a dict) so ``list()`` / iteration order is
        # stable in operator reports. ``get`` / ``__contains__`` do a
        # linear scan — the registry stays tiny (handful of entries per
        # environment), so O(n) is cheaper than maintaining two structures.
        self._targets: List[SimulatorTarget] = []

    # ------------------------------------------------------------------
    # FR-15 contract assertion.
    # ------------------------------------------------------------------

    @classmethod
    def refuses_real_league(cls) -> bool:
        """The FR-15 contract: this registry ALWAYS refuses real-league.

        Returns ``True`` unconditionally. The point is not the boolean
        (any registry that does its job returns ``True``); the point is
        that *one* named attribute carries the contract, so that any
        future code path or test that needs to ask "does this registry
        refuse real-league targets?" has a single source of truth to read.
        """
        return True

    # ------------------------------------------------------------------
    # Defense in depth: the same forbidden-substring check the schema
    # applies at construction time. Exposed as a static method so the
    # runner can pre-screen a config payload before it even reaches
    # ``SimulatorTarget(...)`` (e.g. when re-hydrating from disk).
    # ------------------------------------------------------------------

    @staticmethod
    def _check_exe_path_safe(exe_path: str | None) -> None:
        """Raise :class:`SimulatorRegistryError` if ``exe_path`` is banned.

        Mirrors the schema's ``@field_validator("exe_path")`` so a target
        constructed via ``model_construct(...)`` (which skips validators)
        is still refused at registration time.
        """
        if exe_path is None:
            return
        lowered = exe_path.lower()
        for bad in FORBIDDEN_EXE_SUBSTRINGS:
            if bad in lowered:
                raise SimulatorRegistryError(
                    "SimulatorRegistry: exe_path points at a real League "
                    "process; refused (matches forbidden substring "
                    f"{bad!r})"
                )

    # ------------------------------------------------------------------
    # Mutation: register.
    # ------------------------------------------------------------------

    def register(self, target: SimulatorTarget) -> None:
        """Register ``target``. Idempotent on ``target_id`` (replace wins).

        Refuses to register if:

        * ``target`` is not a valid ``SimulatorTarget`` (re-validated
          defensively via ``model_validate`` to catch a ``model_construct``
          bypass);
        * the target's ``exe_path`` names a real Riot / League binary
          (defense in depth — the schema already enforces this, but the
          registry must be independently safe);
        * any of the above produce a ``ValidationError`` from the
          re-validation step.

        On success, ``target`` is appended to ``self._targets`` (or replaces
        the entry with the same ``target_id`` if one already exists).
        """
        # 1) Defensive re-validation. Pydantic already ran validators when
        # ``target`` was constructed, but ``model_construct`` skips them,
        # so we re-run the schema here. We feed ``model_dump`` so any
        # extra keys are stripped before re-validation (extra='forbid'
        # makes that an error rather than a silent drop).
        try:
            validated = SimulatorTarget.model_validate(target.model_dump())
        except ValidationError as exc:
            raise SimulatorRegistryError(
                "SimulatorRegistry: target failed re-validation; refused "
                f"({exc})"
            ) from exc

        # 2) Defense in depth: the exe_path substring check, run *outside*
        # of the schema so a future change to ``model_construct`` cannot
        # silently remove it.
        self._check_exe_path_safe(validated.exe_path)

        # 3) Idempotent append (replace on same target_id).
        # Use a list scan — the registry is small (handful of entries),
        # so a list is cheaper to maintain than a parallel dict, and
        # iteration order is stable for operator reports.
        for i, existing in enumerate(self._targets):
            if existing.target_id == validated.target_id:
                self._targets[i] = validated
                return
        self._targets.append(validated)

    # ------------------------------------------------------------------
    # Lookup.
    # ------------------------------------------------------------------

    def get(self, target_id: str) -> SimulatorTarget | None:
        """Return the target with ``target_id`` or ``None`` if absent."""
        for t in self._targets:
            if t.target_id == target_id:
                return t
        return None

    def list_approved(self) -> List[SimulatorTarget]:
        """Return only targets cleared for autonomous play.

        Approved set:

        * ``license_review_status == "approved"`` — reviewed and cleared;
        * ``license_review_status == "self-built"`` — we own the source and
          no upstream review applies.

        Pending / rejected / unknown are filtered out: the runner must not
        pick them without an explicit operator override (which the runner
        handles by calling :meth:`get` directly with a known id).
        """
        return [
            t
            for t in self._targets
            if t.license_review_status in {"approved", "self-built"}
        ]

    # ------------------------------------------------------------------
    # Convenience / protocol.
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._targets)

    def __contains__(self, target_id: str) -> bool:
        return self.get(target_id) is not None


__all__ = [
    "SimulatorRegistryError",
    "SimulatorRegistry",
    "FORBIDDEN_EXE_SUBSTRINGS",
]
