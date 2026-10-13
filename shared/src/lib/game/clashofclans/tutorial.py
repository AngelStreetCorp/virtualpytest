"""
§81.1.10 tutorial driver (TASK-81).

Progresses a fresh Clash of Clans village through Supercell's tutorial
until the §81.1.2 priority chain (collect / train / donate / clan-capital /
daily) becomes reachable. The driver is a stateful walker over the ten
known tutorial steps:

    1. welcome                — "Welcome Chief!" dismiss
    2. build_town_hall        — pick the Town Hall card from the dock
    3. place_town_hall        — swipe the card onto the village grass
    4. build_gold_mine        — pick the Gold Mine card
    5. place_gold_mine        — drop the mine on grass
    6. build_cannon           — same for the Cannon (the final build)
    7. attack_tutorial        — **MANUAL handoff** (R1 forbids auto-attack)
    8. after_attack           — "Welcome back" returns after the operator
                                 clears the tutorial attack + at least one
                                 troop gets trained
    9. train_troops           — drag a troop onto the army queue
   10. join_clan              — clan search screen; manual handoff if the
                                 operator isn't ready to join a clan

After step 10 the tutorial is complete; the §81.1.2 farm bot takes over.

This module is a pure state machine + plan executor. The vision helpers
in ``vision.py`` (``detect_tutorial_dialog``, ``crop_tutorial_bubble``)
give it the pixel reads; the runner provides the OCR (pytesseract or a
test stub) and the device-execution plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Tutorial step table
# ---------------------------------------------------------------------------

# Each step has:
#   id           -- stable name, used in events + reports
#   match        -- lowercased substrings; if any is found in the bubble
#                   text, this step is "current"
#   next         -- the next step id, or None for terminal steps
#   action       -- what the runner must do while this step is current
#                   (None means "wait for the dialog to advance itself")
#   manual       -- True when this step requires a human at the device
#                   (we never fire scripted taps on those steps; the
#                   runner parks and emits a `manual_handoff` event)

@dataclass(frozen=True)
class TutorialStep:
    id: str
    match: tuple  # type: ignore[type-arg]
    next: Optional[str]
    action: Optional[str] = None
    manual: bool = False
    description: str = ""


TUTORIAL_STEPS: Dict[str, TutorialStep] = {
    "welcome": TutorialStep(
        id="welcome",
        match=("welcome chief", "welcome back", "welcome to"),
        next="build_town_hall",
        action="tap_bubble",
        description="Welcome Chief bubble — tap Okay!"),
    "build_town_hall": TutorialStep(
        id="build_town_hall",
        match=("build your town hall", "build a town hall"),
        next="place_town_hall",
        action="tap_dock_card",
        description="Town Hall build card highlighted on the dock"),
    "place_town_hall": TutorialStep(
        id="place_town_hall",
        match=("place your town hall", "place the town hall"),
        next="build_gold_mine",
        action="swipe_dock_to_grass",
        description="Drag Town Hall from dock onto grass centre"),
    "build_gold_mine": TutorialStep(
        id="build_gold_mine",
        match=("build a gold mine", "build your gold mine"),
        next="place_gold_mine",
        action="tap_dock_card",
        description="Gold Mine build card highlighted"),
    "place_gold_mine": TutorialStep(
        id="place_gold_mine",
        match=("place the gold mine", "place a gold mine", "place your gold mine"),
        next="build_cannon",
        action="swipe_dock_to_grass",
        description="Drag Gold Mine from dock onto grass"),
    "build_cannon": TutorialStep(
        id="build_cannon",
        match=("build a cannon", "build your cannon"),
        next="attack_tutorial",
        action="tap_dock_card",
        description="Cannon build card highlighted"),
    "attack_tutorial": TutorialStep(
        id="attack_tutorial",
        # Match both the defend phase (goblins) and the attack phase
        # (find a village). The defend phase is a scripted narrative
        # where the cannon we just built auto-fires; we just need to
        # wait it out. The attack phase needs a real action.
        match=("attack a nearby", "find a village", "find a village to attack",
               "go attack", "attack!", "oh no", "goblins", "set up a cannon",
               "defend the village", "set up the cannon", "set up your cannon"),
        next="after_attack",
        action="auto_advance",
        manual=False,
        description="Tutorial attack — scripted narrative; bot auto-taps"),
    "after_attack": TutorialStep(
        id="after_attack",
        match=("welcome back", "nice work", "your village is ready",
               "your village looks great"),
        next="train_troops",
        action="tap_bubble",
        manual=False,
        description="Welcome back bubble after the operator's first attack"),
    "train_troops": TutorialStep(
        id="train_troops",
        match=("train some troops", "train troops", "build an army",
               "open army", "drag a troop"),
        next="join_clan",
        action="auto_advance",
        manual=False,
        description="Open Army, drag a troop onto the training queue"),
    "join_clan": TutorialStep(
        id="join_clan",
        match=("find a clan", "join a clan", "search for a clan",
               "join now", "you've been invited"),
        next="complete",
        action="auto_advance",
        manual=False,
        description="Bot auto-joins the first suggested clan"),
    "complete": TutorialStep(
        id="complete",
        match=(),
        next=None,
        action=None,
        manual=False,
        description="Tutorial complete — §81.1.2 chain is reachable"),
}

# Step ordering by id, for the report's breadcrumb trail.
TUTORIAL_ORDER: tuple = (
    "welcome", "build_town_hall", "place_town_hall",
    "build_gold_mine", "place_gold_mine", "build_cannon",
    "attack_tutorial", "after_attack", "train_troops",
    "join_clan", "complete",
)


# ---------------------------------------------------------------------------
# TutorialDriver
# ---------------------------------------------------------------------------

# The dock and grass tap positions, calibrated live on S21 FE (2340x1080
# device space). The android_mobile action executor interprets tap /
# swipe params as device-space coordinates (it routes through
# ``adb shell input tap X Y`` / ``adb shell input swipe X1 Y1 X2 Y2
# duration``), so the constants here are DEVICE coords, not the
# 1280x720 capture coords we used to think.
DOCK_CARD_SLOTS = {
    # card centre (device coords, 2340x1080) for the four tutorial build
    # cards. Approximate -- the dock positions are derived from the
    # capture coords (560, 580) * (2340/1280, 1080/720) = (1024, 870);
    # (660, 580) -> (1207, 870); (760, 580) -> (1389, 870). Until we
    # confirm the dock visually after the disconnect + welcome bubble
    # are cleared, treat these as best-effort.
    "townhall":  (1024, 870),
    "mine":      (1207, 870),
    "cannon":    (1389, 870),
}
GRASS_DROP_XY = (1170, 525)  # centre of the build grid (device coords)


@dataclass
class TutorialDriver:
    """Stateful walker across TUTORIAL_STEPS.

    Public surface:

        .observe(text, painted) -> step_change
            text    : OCR output for the bubble box (lowercased)
            painted : whether vision.detect_tutorial_dialog said True
            Returns a dict with one of:
              {"event": "step_advanced", "from": str, "to": str}
              {"event": "step_held",     "step": str}
              {"event": "tutorial_off",  "state": "untouched"|"complete"|"manual"}

        .step_current -> step id or None
        .step_action  -> action name for the runner to dispatch (None when
                         the dialog is text-only)
        .step_action_params -> dict of params for that action (e.g. card name)
        .step_description -> human-readable sentence for the report
        .is_complete() -> True after "complete" step is reached
        .require_manual_handoff() -> True when current step is MANUAL

        The driver is pure: it never imports device / executor / OCR.
        Tests inject an OCR function (or skip OCR entirely by setting
        ``painted=False``) and inspect state transitions.
    """
    initial_step: str = "welcome"
    # past_steps keeps the full breadcrumb so the report can list every
    # step the runner crossed (and which it stayed on).
    past_steps: List[str] = field(default_factory=list)
    step_current: Optional[str] = None
    last_text: str = ""

    def __post_init__(self) -> None:
        if self.initial_step not in TUTORIAL_STEPS:
            raise ValueError(f"unknown tutorial step: {self.initial_step!r}")
        self.step_current = self.initial_step

    # --- accessors --------------------------------------------------------

    def _step(self) -> Optional[TutorialStep]:
        if self.step_current is None:
            return None
        return TUTORIAL_STEPS.get(self.step_current)

    def step_action(self) -> Optional[str]:
        s = self._step()
        return s.action if s else None

    def step_action_params(self) -> Dict[str, Any]:
        s = self._step()
        if s is None:
            return {}
        if s.action == "tap_dock_card":
            return {"name": _card_name_for_step(s.id)}
        if s.action == "swipe_dock_to_grass":
            return {"from_xy": _dock_xy_for_step(s.id),
                    "to_xy": GRASS_DROP_XY}
        if s.action == "tap_bubble":
            # The android_mobile executor passes x/y straight through to
            # ``adb shell input tap``, so the value is in device coords
            # (2340x1080 on S21 FE). Measured on the live 2026-10-11
            # capture: the welcome bubble body spans device x in
            # [205..960], y in [520..700]; centre ~ (582, 610).
            return {"bubble_xy": (582, 610)}
        if s.action == "auto_advance":
            # Multi-tap sequence with per-tap wait_time (ms). The runner
            # dispatches these as a single action_executor batch; the
            # executor runs them sequentially with the wait_time as the
            # delay between consecutive taps. Coordinates are in DEVICE
            # space (2340x1080) -- the same convention as tap_bubble.
            if s.id == "attack_tutorial":
                # Defend phase: dismiss the "set up cannon / goblins"
                # bubble so the game plays out the scripted attack.
                # Attack phase: tap the Attack button (lower-right of
                # the village), then Find Match, drop a troop, Return
                # Home. All coordinates are best-effort -- the tutorial
                # attack is a scripted narrative with a fixed layout.
                return {"taps": [
                    {"x": 582,  "y": 610,  "wait_time": 3000},  # dismiss any bubble
                    {"x": 2010, "y": 950,  "wait_time": 4000},  # Attack button (lower-right of village)
                    {"x": 1170, "y": 750,  "wait_time": 5000},  # Find a Match
                    {"x": 1170, "y": 540,  "wait_time": 15000}, # deploy a troop (drag target = village centre)
                    {"x": 1170, "y": 200,  "wait_time": 4000},  # End Battle / Surrender (top)
                    {"x": 1170, "y": 950,  "wait_time": 4000},  # Return Home confirmation
                ]}
            if s.id == "train_troops":
                # Open the Army tab, drag a Barbarian onto the
                # training queue. Army tab is at the lower-LEFT of
                # the village; the troop icon in the bottom-centre
                # drag handle is at the army popup's footer. Coords
                # are best-effort -- the tutorial army popup has a
                # fixed layout.
                return {"taps": [
                    {"x": 582,  "y": 610,  "wait_time": 3000},  # dismiss any bubble
                    {"x": 250,  "y": 970,  "wait_time": 4000},  # Army tab (lower-left)
                    {"x": 1170, "y": 700,  "wait_time": 4000},  # Barbarian icon in army popup
                    {"x": 1170, "y": 350,  "wait_time": 4000},  # Training queue (drag target)
                    {"x": 2100, "y": 100,  "wait_time": 3000},  # Close army popup (X top-right)
                ]}
            if s.id == "join_clan":
                # Search for a clan and join the first suggestion.
                # "Find a Clan" opens a search box; tapping a
                # suggested clan opens its profile with a "Join" button.
                return {"taps": [
                    {"x": 582,  "y": 610,  "wait_time": 3000},  # dismiss any bubble
                    {"x": 1170, "y": 950,  "wait_time": 4000},  # search / first suggestion row
                    {"x": 1170, "y": 540,  "wait_time": 4000},  # open the clan profile
                    {"x": 1170, "y": 950,  "wait_time": 4000},  # Join button (lower-centre)
                    {"x": 1170, "y": 950,  "wait_time": 3000},  # confirm / OK dialog
                ]}
        return {}

    def step_description(self) -> str:
        s = self._step()
        return s.description if s else ""

    def is_complete(self) -> bool:
        return self.step_current == "complete"

    def require_manual_handoff(self) -> bool:
        s = self._step()
        return bool(s and s.manual)

    def manual_handoff_summary(self) -> Dict[str, Any]:
        s = self._step()
        if not s or not s.manual:
            return {}
        return {"id": s.id, "description": s.description}

    def is_in_progress(self) -> bool:
        """True when the tutorial has neither completed nor been abandoned."""
        return (self.step_current is not None
                and self.step_current != "complete")

    # --- transitions ------------------------------------------------------

    def observe(self, text: str, painted: bool) -> Dict[str, Any]:
        """Drive the state machine with one observation.

        ``text`` -- OCR output of the bubble box (lower-cased by the
                    runner before calling). Empty string when OCR fails.
        ``painted`` -- whether the bubble is visible on screen.

        On every step match, the driver advances to ``step.next``. When
        the OCR'd text doesn't match any known step the driver stays on
        the current step and emits ``step_held``. When the bubble isn't
        painted the driver holds too (the runner treats that as "tutorial
        not active" — not an error).
        """
        self.last_text = text or ""
        if not painted:
            return {"event": "step_held", "step": self.step_current,
                    "reason": "bubble_not_painted"}
        # Match the OCR text against every step's match list. The check
        # is whole-substring of any match in the text — fast and tolerant
        # of varying punctuation.
        text_lc = text.lower()
        matched_id: Optional[str] = None
        for sid, step in TUTORIAL_STEPS.items():
            if not step.match:
                continue
            for kw in step.match:
                if kw in text_lc:
                    matched_id = sid
                    break
            if matched_id is not None:
                break
        if matched_id is None:
            # bubble is painted but the text doesn't match anything.
            # Could be a localised variant or an off-script dialog
            # (Settings, Code of Conduct, etc.). Sticky on current step.
            return {"event": "step_held_unknown",
                    "step": self.step_current, "text": text_lc[:120]}
        if matched_id == self.step_current:
            return {"event": "step_held", "step": self.step_current}
        # Advance: we may skip steps if the bubble advanced several in
        # one frame (e.g. fast-tap during connection lag). Walk from
        # matched_id forward through the TUTORIAL_ORDER until we land on
        # self.step_current or its successor.
        prev = self.step_current
        if prev is not None:
            try:
                idx_prev = TUTORIAL_ORDER.index(prev)
                idx_new = TUTORIAL_ORDER.index(matched_id)
                if idx_new < idx_prev:
                    # backwards -- treat as held
                    return {"event": "step_held", "step": prev,
                            "skipped_match": matched_id}
                self.past_steps.append(prev)
                self.step_current = matched_id
                step = TUTORIAL_STEPS[matched_id]
                return {"event": "step_advanced", "from": prev, "to": matched_id,
                        "action": step.action, "manual": step.manual}
            except ValueError:
                pass
        # Fallback: directly set
        self.step_current = matched_id
        return {"event": "step_advanced", "from": prev, "to": matched_id,
                "action": TUTORIAL_STEPS[matched_id].action,
                "manual": TUTORIAL_STEPS[matched_id].manual}

    def advance_to_next(self) -> Dict[str, Any]:
        """Advance to ``step.next`` (or terminate).

        The runner calls this after a successful action on the current
        step. ``complete`` has ``next=None`` and the call returns the
        ``{"event": "tutorial_complete"}`` marker; the runner logs it
        and the chain takes over from there.
        """
        s = self._step()
        if s is None:
            return {"event": "tutorial_complete", "step": None}
        if s.next is None:
            # already on complete; no-op
            return {"event": "tutorial_complete", "step": self.step_current}
        nxt = s.next
        if nxt not in TUTORIAL_STEPS:
            return {"event": "tutorial_complete", "step": self.step_current,
                    "warning": f"step.next={nxt!r} is unknown"}
        self.past_steps.append(self.step_current)
        self.step_current = nxt
        if nxt == "complete":
            return {"event": "tutorial_complete", "step": "complete"}
        next_step = TUTORIAL_STEPS[nxt]
        return {"event": "step_advanced", "from": s.id, "to": nxt,
                "action": next_step.action, "manual": next_step.manual}

    def snapshot(self) -> Dict[str, Any]:
        """A JSON-friendly view used by the runner's KPI dump + report."""
        return {
            "current": self.step_current,
            "past": list(self.past_steps),
            "complete": self.is_complete(),
            "manual_handoff": self.require_manual_handoff(),
            "last_text": self.last_text,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Maps each ``build_<card>`` and the matching ``place_<card>`` step to
# its dock slot. The place step's swipe starts at the card we just
# picked up; the build step's tap lands on the same card.
_STEP_TO_CARD = {
    "build_town_hall": "townhall",
    "place_town_hall": "townhall",
    "build_gold_mine": "mine",
    "place_gold_mine": "mine",
    "build_cannon":    "cannon",
}


def _card_name_for_step(step_id: str) -> str:
    """Map a build / place step id to its dock-card key in DOCK_CARD_SLOTS."""
    return _STEP_TO_CARD.get(step_id, "")


def _dock_xy_for_step(step_id: str) -> tuple:
    """Centre XY for the dock card on the build dock (capture coords)."""
    return DOCK_CARD_SLOTS.get(_card_name_for_step(step_id), GRASS_DROP_XY)
