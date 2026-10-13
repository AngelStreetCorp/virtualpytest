"""
The Clash of Clans farm-bot loop (TASK-81 §81.1).

The runner is the only place that touches the device: it captures frames,
fires action batches, talks to the navigation executor and the action
executor, holds the vpt-lease on the S21 FE slot, and writes the KPI
metadata block on every exit path. ``vision``, ``tactics`` and ``menus``
stay pure (GAME_BOTS §1: the perception / decision / menu layers cannot
import device code).

Cycle shape:

    capture frame  ->  warn-substring scan (§R5)  ->  read_village  ->
    decide_next (priority chain)  ->  cross_to target  ->
    one action batch  ->  record_step  ->  KPI update

Every cycle respects the four big rules from GAME_BOTS §2:

* one action batch per decision, ``wait_time=0`` (rule 1);
* a transition frame is not a screen -- the runner waits one frame
  before re-reading (rule 2);
* taps only land on what vision has confirmed (rule 3);
* KPI deltas are computed on small regions, never whole-frame OCR (rule 4);
* the menu module picks targets by name, not position (rule 5);
* the runner refuses any "buy / purchase / gem / pass / offer /
  subscribe" tap (rule 6);
* the runner **never** takes the Attack path (§81.1 out-of-scope).

The guard is fail-closed: any match of an R5 substring during the cycle
sets ``stop_reason = 'guard'`` and ``account_warning_seen = True``, drops
the lease, and refuses to relaunch (TASK-81 §81.1 R5).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from . import menus, tactics, tutorial, vision
from .tactics import (
    CLEAR_DISCONNECT_MODAL,
    IDLE,
)
from .tutorial import TutorialDriver, TutorialStep
from .video import VideoRecorder
from .tactics import (
    Action,
    BANNED_ACTION_SUBSTRINGS,
    CLAN_CAPITAL_COLLECT,
    COLLECT_READY_COLLECTORS,
    DAILY_COLLECT,
    DONATE_PENDING,
    IDLE,
    TRAIN_DONATIONS_NEEDED,
    TREE_ACTIONS,
)
from .vision import (
    VillageObservation,
    crop_account_warning,
    detect_account_warning,
    warning_substrings,
)
from shared.src.lib.utils import cv2_io

log = logging.getLogger("vpt.game.clashofclans.runner")

UI_PREFIX = "clashofclans-"
DEFAULT_DEVICE_MODEL = "s21_phone"
DEFAULT_USERINTERFACE = "clashofclans-android-mobile"

# Frame poll cadence. The S21 FE HDMI path lags the screen by 1-2 s
# (TASK-81 §81.1); a frame every REACT_S guards against acting twice on
# the lag-window (GAME_BOTS §2 rule 1).
REACT_S = 0.5
IDLE_PAUSE_S = 1.0
WARN_OCR_TESSERACT_PSM = 6

# R5 catalogue duplicated as a tuple so the runner doesn't depend on
# vision reading the catalogue at import time (it owns the fail-closed
# behaviour here).
R5_SUBSTRINGS = (
    "your account",
    "suspended",
    "suspicious activity",
)


# ---------------------------------------------------------------------------
# Optional OCR adapter. The runner accepts an OCR function from the script
# so synthetic tests can monkeypatch it without pulling pytesseract in.
# ---------------------------------------------------------------------------
OCRFn = Callable[[Any], str]


def _default_ocr(region) -> str:
    """Default OCR uses pytesseract when available; returns ``""`` (empty)
    otherwise. Synthetic tests inject a stub."""
    try:
        import pytesseract  # type: ignore
    except Exception:
        return ""
    try:
        return str(pytesseract.image_to_string(region, config=f"--psm {WARN_OCR_TESSERACT_PSM}"))
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Runner config
# ---------------------------------------------------------------------------

@dataclass
class RunnerConfig:
    """Per-run knobs.

    Defaults match TASK-81 §81.1.5 / §81.1.6 (max runtime 30 minutes for
    the first live run, 4 hours for the soak).

    ``shop_free_claim`` is gated off by default per TASK-81 §81.1 R3 -- the
    runner refuses to auto-claim a "free" rotating shop item on principle.
    """

    max_runtime_s: int = 1800
    max_cycles: int = 240
    idle_s_per_action: float = IDLE_PAUSE_S
    donate_policy: str = "auto"          # auto | manual
    collect_policy: str = "auto"         # auto | manual
    attack_opt_in: bool = False          # always False in v1; raises hard
    shop_free_claim: bool = False        # R3: gated off; default False
    dry_run: bool = False
    install_only: bool = False


# ---------------------------------------------------------------------------
# GameRunner
# ---------------------------------------------------------------------------

class GameRunner:
    """The §81.1 loop. ``run()`` returns the KPI ``data`` dict.

    The constructor only stores dependencies. ``run()`` does the work.
    Errors raise ``RuntimeError`` so the script can mark the run failed.
    """

    def __init__(self, device: Any, context: Any, userinterface: str, tree_id: str,
                 config: Optional[RunnerConfig] = None,
                 ocr: Optional[OCRFn] = None,
                 video: Optional[VideoRecorder] = None,
                 tutorial_driver: Optional[TutorialDriver] = None):
        if not userinterface.startswith(UI_PREFIX):
            raise ValueError(f"userinterface must start with '{UI_PREFIX}', got {userinterface!r}")
        if config is None:
            config = RunnerConfig()
        self.device = device
        self.context = context
        self.userinterface = userinterface
        self.tree_id = tree_id
        self.config = config
        self.ocr = ocr or _default_ocr
        # Per-cycle host-screen recording (§81.1.9). When None, the runner
        # makes its own (auto-disabled when no adb serial is available, so
        # never an import-time crash). Tests inject a fake recorder here.
        if video is None:
            run_id = "coc_run_" + str(int(time.time()))
            video = VideoRecorder(device, run_id=run_id)
        self.video = video
        # §81.1.10 tutorial driver. When None, the runner auto-creates one;
        # tests inject a scripted driver for synthetic state machines.
        self.tutorial_driver = tutorial_driver or TutorialDriver()

        # Hard guard against enabling the Attack path. TASK-81 §81.1 says
        # the runner MUST refuse Attack; the only place that flag would
        # ever be set is ``runner_config.attack_opt_in``, and we ignore it
        # on principle (the script is the only layer that can read it for
        # ad-hoc testing on a non-farming account).
        if config.attack_opt_in:
            log.warning("attack_opt_in=True ignored: TASK-81 §81.1 refuses the Attack button")

        self.data: Dict[str, Any] = {
            "userinterface": userinterface,
            "device_model": getattr(device, "device_model", DEFAULT_DEVICE_MODEL),
            "gold_gained": 0,
            "elixir_gained": 0,
            "dark_elixir_gained": 0,
            "troops_trained": 0,
            "troops_donated": 0,
            "capital_chests_collected": 0,
            "dailies_collected": 0,
            "cycles_completed": 0,
            "attack_attempted": False,
            "account_warning_seen": False,
            "stop_reason": "",
            "play_duration_s": 0,
            "idle_seconds": 0,
            "path": userinterface[len(UI_PREFIX):],
            "max_runtime_s": config.max_runtime_s,
            "max_cycles": config.max_cycles,
            "attack_opt_in": False,    # forced False
            "shop_free_claim": config.shop_free_claim,
            "actions_fired": 0,
            "guard_scan_count": 0,
            "no_observation_cycles": 0,
            "transition_cycles": 0,
            "plan_priority": tactics.priority_chain_description(),
            "buy_surface_refused": 0,
            # §81.1.10 tutorial driver state
            "tutorial_dialogs_seen": 0,
            "tutorial_complete": False,
            "tutorial_current_step": self.tutorial_driver.step_current or "",
            "tutorial_past_steps": [],
        }

        # Action log: every cycle + every screen change + every guard trip.
        # Mirrors game_pokémon's runner.log[] -- the report (report.py)
        # reads it for the run timeline. Each entry has:
        #   t           -- wall-clock seconds since play_started (added in _log)
        #   kind        -- short tag for the report (see _KIND_*)
        #   cycle_index -- the cycle that produced this entry
        #   ... plus per-kind fields
        self.log: List[Dict[str, Any]] = []
        self._play_started_at: Optional[float] = None

        self._started_at: Optional[float] = None
        self._last_action_at: Optional[float] = None
        self._gold_prev: Optional[int] = None
        self._elixir_prev: Optional[int] = None
        self._drk_prev: Optional[int] = None

    # --- device access --------------------------------------------------------

    def navigate(self, node: str) -> Dict[str, Any]:
        """One navigation edge from the user-interface tree."""
        return asyncio.run(self.device.navigation_executor.execute_navigation(
            tree_id=self.tree_id,
            userinterface_name=self.userinterface,
            target_node_label=node,
            team_id=self.context.team_id,
            context=self.context,
        ))

    def run_actions(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ad-hoc action batch (the menu plan: tap / press_key / swipe)."""
        # Defence in depth: the menu module already filters, but the runner
        # is the safety net against a future regression in ``menus.cross_to``.
        clean = [a for a in actions if not self._is_buy_surface(a)]
        if len(clean) != len(actions):
            self.data["buy_surface_refused"] += len(actions) - len(clean)
        if not clean:
            return {"success": False, "error": "empty or fully-refused batch"}
        return asyncio.run(self.device.action_executor.execute_actions(
            actions=clean,
            team_id=self.context.team_id,
            context=self.context,
            userinterface_name=self.userinterface,
        ))

    def frame(self) -> Optional[Any]:
        """A BGR numpy frame, or ``None`` when the capture pipeline is offline.

        ``capture_screenshot`` returns the latest-capture path (a string),
        not the array; we read it back with cv2 so vision.get_* callers
        always see a real ndarray.
        """
        from shared.src.lib.utils.device_utils import capture_screenshot
        path = capture_screenshot(self.device)
        if not path:
            return None
        try:
            import cv2  # type: ignore
        except Exception:
            return None
        img = cv2_io.imread(path)
        return img if img is not None else None

    def evidence(self, name: str) -> str:
        """A screenshot saved next to the script for the report."""
        from shared.src.lib.utils.device_utils import capture_screenshot_for_script
        ok = capture_screenshot_for_script(self.device, self.context, name)
        return self.context.screenshot_paths[-1] if ok and self.context.screenshot_paths else ""

    # --- guard -----------------------------------------------------------------

    def _scan_guard(self, img) -> bool:
        """The §R5 guard trip.

        Steps (all fail-closed):
            1. Pixel pre-filter on the warning region (always).
            2. OCR the warning region (default pytesseract; tests inject).
            3. Substring scan on the OCR output (vision.warning_substrings).

        Returns ``True`` when the guard trips.
        """
        self.data["guard_scan_count"] += 1
        if not detect_account_warning(img):
            return False
        crop = crop_account_warning(img)
        text = self.ocr(crop) if crop is not None and getattr(crop, "size", 0) else ""
        return warning_substrings(text) or _substring_scan(text)

    def _is_buy_surface(self, action: Dict[str, Any]) -> bool:
        """Per §81.1 R3 and GAME_BOTS §2 rule 6. Refuses any action whose
        command / params mention a real-money surface."""
        return menus.is_banned(action)

    # --- KPI helpers -----------------------------------------------------------

    def _try_update_resource_deltas(self, obs: VillageObservation) -> None:
        """If the OCR layer wired digits into obs (gold / elixir / dark),
        compute KPIs by cross-frame delta. Otherwise leave the counters at
        0 -- structural pixel reads alone can't tally gold_gained.
        """
        for field_name, attr in (("gold_gained", "gold"), ("elixir_gained", "elixir"),
                                 ("dark_elixir_gained", "dark_elixir")):
            cur = getattr(obs, attr)
            if cur is None:
                continue
            prev_attr = f"_{attr.split('_')[0]}_prev"
            # the prev slots are gold_prev / elixir_prev / drk_prev
            slot = {"gold_gained": "_gold_prev",
                    "elixir_gained": "_elixir_prev",
                    "dark_elixir_gained": "_drk_prev"}[field_name]
            prev = getattr(self, slot, None)
            if prev is not None and cur >= prev:
                self.data[field_name] += int(cur - prev)
            setattr(self, slot, cur)

    def _record_action_kpi(self, action: Action, success: bool) -> None:
        """Bump the KPI counter for the action we just executed."""
        if not success:
            return
        if action.name == COLLECT_READY_COLLECTORS:
            self.data["cycles_completed"] += 1
        elif action.name == TRAIN_DONATIONS_NEEDED:
            self.data["troops_trained"] += 1
        elif action.name == DONATE_PENDING:
            self.data["troops_donated"] += 1
        elif action.name == CLAN_CAPITAL_COLLECT:
            self.data["capital_chests_collected"] += 1
        elif action.name == DAILY_COLLECT:
            self.data["dailies_collected"] += 1

    # --- §81.1.10 tutorial routing ------------------------------------------

    def _handle_tutorial(self, img: Any, cycle_index: int, started: float) -> str:
        """One cycle on the tutorial dialog screen.

        Reads the bubble text (OCR via ``self.ocr``), feeds it to the
        ``TutorialDriver``, executes the step's action via the menu
        executor when one is set, and logs the event.

        Always returns ``"continue"``: tutorial advances are paced by
        the dialog itself, not by the bot's cycle budget.
        """
        td = self.tutorial_driver
        # OCR the bubble box only when the bubble is painted -- otherwise
        # we just hit "step_held bubble_not_painted".
        crop = vision.crop_tutorial_bubble(img)
        text = ""
        if crop is not None and getattr(crop, "size", 0):
            text = self.ocr(crop) or ""
        result = td.observe(text or "", painted=text != "" or vision.detect_tutorial_dialog(img))
        self.data["tutorial_dialogs_seen"] += 1
        self.data["tutorial_current_step"] = td.step_current or ""
        self.data["tutorial_past_steps"] = list(td.past_steps)
        self.data["tutorial_complete"] = td.is_complete()

        # Log + dispatch
        action_result: Dict[str, Any] = {"observed": result, "text": (text or "")[:200]}
        if td.require_manual_handoff():
            self._log("tutorial_manual_handoff", cycle_index,
                      step=td.step_current,
                      description=td.step_description(),
                      text=(text or "")[:120])
            # do not fire actions on a manual step
            self.record_step(
                "§81.1.10 manual handoff — operator must take over",
                True, "tutorial",
                {"tutorial": td.snapshot(), "observed": result,
                 "text": (text or "")[:200]},
                self.evidence(f"coc_tutorial_{cycle_index:04d}_manual"),
                started, label="tutorial_manual",
            )
            return "continue"

        action = td.step_action()
        params = td.step_action_params()
        if action is None:
            self._log("tutorial_dialog_seen", cycle_index,
                      step=td.step_current,
                      event_kind=result.get("event"),
                      observed=result,
                      text=(text or "")[:120])
            self.record_step(
                f"§81.1.10 tutorial: {td.step_description()}",
                True, "tutorial",
                {"tutorial": td.snapshot(), "observed": result,
                 "text": (text or "")[:200]},
                self.evidence(f"coc_tutorial_{cycle_index:04d}_text"),
                started, label="tutorial_text",
            )
            return "continue"

        # Tap / swipe the action the step asks for. The runner never
        # dispatches UI-tree nodes from inside the tutorial -- we go
        # straight to the action executor so the input bypasses vptree
        # (the dock + bubble taps aren't tree nodes).
        tap_actions = self._tutorial_action_batch(action, params)
        success = False
        if tap_actions:
            run = self.run_actions(tap_actions)
            success = bool(run.get("success"))
            action_result["actions_fired"] = tap_actions
            action_result["run_result"] = run

        # §81.1.10 step transition: when the action succeeded and the
        # step has a successor, advance. We do NOT wait for the bubble
        # to re-render -- the next observation cycle will re-validate.
        advance_event: Optional[Dict[str, Any]] = None
        if success:
            advance_event = td.advance_to_next()
            action_result["advance"] = advance_event
            self.data["tutorial_current_step"] = td.step_current or ""
            self.data["tutorial_past_steps"] = list(td.past_steps)
            self.data["tutorial_complete"] = td.is_complete()

        kind = result.get("event", "step_advanced")
        self._log("tutorial_action_fired" if success else "tutorial_action_failed",
                  cycle_index, step=td.step_current,
                  action=action, params=params, success=success,
                  observed_event=kind, advance=advance_event)
        self.record_step(
            f"§81.1.10 {action}: {td.step_description()}",
            success, "tutorial",
            {"tutorial": td.snapshot(), "observed": result,
             "action": action, "params": params,
             "actions_fired": tap_actions, "text": (text or "")[:200],
             "advance": advance_event},
            self.evidence(f"coc_tutorial_{cycle_index:04d}_{action}"),
            started, label="tutorial_action",
        )
        if kind == "step_advanced":
            self._log("tutorial_step_advanced", cycle_index,
                      from_step=result.get("from"),
                      to_step=result.get("to"),
                      to_manual=bool(result.get("manual")))
        if advance_event and advance_event.get("event") == "tutorial_complete":
            self._log("tutorial_complete", cycle_index,
                      past=list(td.past_steps))
        return "continue"

    def _tutorial_action_batch(self, action: str, params: Dict[str, Any]
                               ) -> List[Dict[str, Any]]:
        """Translate a tutorial step into one action_executor batch."""
        if action == "tap_bubble":
            xy = params.get("bubble_xy") or (640, 480)
            return [{"command": "tap_coordinates", "action_type": "android_mobile",
                     "params": {"x": int(xy[0]), "y": int(xy[1]), "wait_time": 0}}]
        if action == "tap_dock_card":
            name = params.get("name")
            from .tutorial import DOCK_CARD_SLOTS
            xy = DOCK_CARD_SLOTS.get(name)
            if xy is None:
                return []
            return [{"command": "tap_coordinates", "action_type": "android_mobile",
                     "params": {"x": int(xy[0]), "y": int(xy[1]), "wait_time": 0}}]
        if action == "swipe_dock_to_grass":
            from_xy = params.get("from_xy") or (640, 480)
            to_xy = params.get("to_xy") or tutorial.GRASS_DROP_XY
            # The android_mobile swipe handler reads params from
            # ``params.get('from_x'|'from_y'|'to_x'|'to_y')`` -- NOT
            # ``x1/y1/x2/y2`` like the menu plans use. Wrong keys
            # silently fail with ``{'success': False}`` and never call
            # the underlying adb swipe.
            return [{"command": "swipe", "action_type": "android_mobile",
                     "params": {"from_x": int(from_xy[0]),
                                "from_y": int(from_xy[1]),
                                "to_x": int(to_xy[0]),
                                "to_y": int(to_xy[1]),
                                "duration": 600}}]
        if action == "auto_advance":
            # Multi-tap sequence with per-tap wait_time. The action
            # executor runs these sequentially with the wait_time as
            # the delay between consecutive taps. Used for the
            # attack_tutorial + join_clan steps where the game flow
            # is "tap a button, wait for the screen, tap the next
            # button" -- a single tap isn't enough.
            taps = params.get("taps") or []
            return [
                {"command": "tap_coordinates", "action_type": "android_mobile",
                 "params": {"x": int(t["x"]), "y": int(t["y"]),
                            "wait_time": int(t.get("wait_time", 1000))}}
                for t in taps
            ]
        return []

    # --- event log ------------------------------------------------------------

    def _log(self, kind: str, cycle_index: int, **fields: Any) -> None:
        """Append one entry to ``self.log`` (the report's timeline).

        Always called *with* a screenshot path or *with* an explicit
        empty ``screenshot=""``; the report renders the cycle's screenshot
        from this entry. ``t`` is the wall-clock seconds since
        ``_play_started_at`` (set in :meth:`run`).
        """
        if self._play_started_at is None:
            offset = 0.0
        else:
            offset = round(time.time() - self._play_started_at, 3)
        entry: Dict[str, Any] = {"t": offset, "kind": kind, "cycle_index": cycle_index}
        entry.update(fields)
        self.log.append(entry)

    # --- record_step ----------------------------------------------------------

    def record_step(self, message: str, success: bool, node: str,
                    details: Dict[str, Any], screenshot: str = "",
                    started: Optional[float] = None, label: str = "") -> None:
        """One row in the script_results timeline."""
        now = time.time()
        started = started or now
        self.context.record_step_immediately({
            "success": success,
            "message": message,
            "from_node": node,
            "to_node": node,
            "execution_time_ms": int((now - started) * 1000),
            "start_time": datetime.fromtimestamp(started).strftime("%H:%M:%S"),
            "end_time": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
            "screenshot_path": screenshot or None,
            "step_end_screenshot_path": screenshot or None,
            "action_screenshots": [screenshot] if screenshot else [],
            "actions": [],
            "verifications": [{
                "verification_type": "clashofclans", "command": label or "cycle",
                "label": message, "success": success, "details": details,
            }],
            "verification_results": [],
            "step_category": "clashofclans",
        })

    # --- per-cycle body --------------------------------------------------------

    def _step_cycle(self, cycle_index: int, started: float) -> str:
        """One runner cycle: frame in, action batch out, KPI updated.

        Returns the stop reason or ``"continue"`` if the loop should run
        another cycle.
        """
        self._log("cycle_start", cycle_index)

        img = self.frame()
        if img is None:
            # Device offline (capture pipeline returned nothing). Stop.
            self.data["stop_reason"] = "device_offline"
            self._log("device_offline", cycle_index, reason="frame_returned_none",
                      cold_path=self.evidence("coc_device_offline"))
            return "device_offline"

        # §R5 fail-closed scan on every cycle, before any other decision.
        if self._scan_guard(img):
            self.data["account_warning_seen"] = True
            self.data["stop_reason"] = "guard"
            cold = self.evidence("coc_guard")
            self.record_step(
                "§R5 guard tripped: account warning on screen",
                False, "guard",
                {"guard_scan_count": self.data["guard_scan_count"]},
                cold, started, label="guard",
            )
            self._log("guard", cycle_index,
                      guard_scan_count=self.data["guard_scan_count"],
                      cold_path=cold)
            return "guard"

        obs = vision.read_village(img)
        if obs is None:
            self.data["no_observation_cycles"] += 1
            self.data["transition_cycles"] += 1
            cold = self.evidence(f"coc_cycle_{cycle_index:04d}_transition")
            self._log("transition", cycle_index,
                      no_observation_count=self.data["no_observation_cycles"],
                      transition_count=self.data["transition_cycles"],
                      cold_path=cold)
            # Rule 2: a transition frame is not a screen -- wait one frame.
            time.sleep(self.config.idle_s_per_action)
            self.data["idle_seconds"] += int(self.config.idle_s_per_action)
            return "continue"

        # Log what we saw (the report shows the per-cycle state).
        self._log("screen", cycle_index,
                  screen=getattr(obs, "screen", "?"),
                  collector_ready=list(getattr(obs, "collector_ready", []) or []),
                  donation_dot_present=bool(getattr(obs, "donation_dot_present", None)),
                  clan_capital_ready=bool(getattr(obs, "clan_capital_ready", None)),
                  daily_present=bool(getattr(obs, "daily_present", None)),
                  gold=getattr(obs, "gold", None),
                  elixir=getattr(obs, "elixir", None),
                  dark_elixir=getattr(obs, "dark_elixir", None),
                  account_warning_present=bool(getattr(obs, "account_warning_present", None)))

        self._try_update_resource_deltas(obs)

        # §81.1.10: tutorial screen supersedes the §81.1.2 chain. While
        # the tutorial is in progress we route every cycle through the
        # TutorialDriver instead of decide_next().
        if getattr(obs, "screen", None) == "tutorial":
            return self._handle_tutorial(img, cycle_index, started)

        action = tactics.decide_next(obs)
        self._log("decision", cycle_index,
                  action_name=action.name,
                  target=action.target,
                  reason=action.reason,
                  is_idle=action.is_idle)

        if action.is_idle:
            # Idle is fine and expected (per §81.1.2). Wait one frame and
            # re-read; idle_seconds tracks how long we were passive.
            time.sleep(self.config.idle_s_per_action)
            self.data["idle_seconds"] += int(self.config.idle_s_per_action)
            cold = self.evidence(f"coc_cycle_{cycle_index:04d}_idle")
            self.record_step(
                f"Idle: {action.reason or 'nothing ready'}",
                True, action.target,
                {"obs": obs.to_dict(), "action": action.to_dict()},
                cold, started, label="idle",
            )
            self._log("idle", cycle_index,
                      reason=action.reason, idle_seconds=self.data["idle_seconds"],
                      cold_path=cold)
            return "continue"

        # Plan the navigation: one batch per decision (rule 1). If we're
        # already on the action's target screen, ``cross_to`` returns an
        # empty list -- treat that as a no-op success and dispatch the tree
        # action directly (don't waste a frame on the executor).
        plan_actions = menus.cross_to(obs, action.target)
        if plan_actions:
            nav_result = self.run_actions(plan_actions)
            self._log("cross_to", cycle_index,
                      target=action.target, planned=len(plan_actions),
                      plan_actions=plan_actions, success=bool(nav_result.get("success")))
            if not nav_result.get("success"):
                # Navigation to the target screen failed: keep going, re-read.
                self.record_step(
                    f"Cross_to {action.target} failed",
                    False, action.target,
                    {"obs": obs.to_dict(), "action": action.to_dict(),
                     "plan_actions": plan_actions, "result": nav_result},
                    self.evidence(f"coc_cycle_{cycle_index:04d}_navfail"),
                    started, label="navigate",
                )
                return "continue"

        # Now run the tree action (collect_resources / train_troops / ...).
        tree_node = TREE_ACTIONS.get(action.name)
        if tree_node is None:
            # Idle-ish: nothing to dispatch (e.g. CLEAR_DISCONNECT_MODAL has no
            # tree node because menus.cross_to handled it).
            if action.name == CLEAR_DISCONNECT_MODAL:
                # The cross_to above cleared it; we record the success and
                # keep looping. Don't bump cycles_completed.
                self._log("disconnect_cleared", cycle_index)
                return "continue"
            cold = self.evidence(f"coc_cycle_{cycle_index:04d}_noop")
            self.record_step(
                f"No tree node for action {action.name}",
                True, action.target,
                {"obs": obs.to_dict(), "action": action.to_dict()},
                cold, started, label="noop",
            )
            self._log("noop", cycle_index, action_name=action.name, cold_path=cold)
            return "continue"

        nav_action = self.navigate(tree_node)
        success = bool(nav_action.get("success"))
        self._record_action_kpi(action, success)
        self.data["actions_fired"] += 1

        cold = self.evidence(f"coc_cycle_{cycle_index:04d}_{action.name}")
        self.record_step(
            f"{action.name} -> {tree_node}",
            success, action.target,
            {"obs": obs.to_dict(), "action": action.to_dict(),
             "tree_node": tree_node, "result": nav_action,
             "plan_actions": plan_actions},
            cold, started, label=action.name,
        )
        self._log("action_fired", cycle_index,
                  action_name=action.name, tree_node=tree_node,
                  success=success, cycles_completed=self.data["cycles_completed"],
                  kpi_count=self.data["troops_trained"] + self.data["troops_donated"]
                             + self.data["capital_chests_collected"] + self.data["dailies_collected"],
                  cold_path=cold)
        return "continue"

    # --- main loop -------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """The §81.1 loop.

        Lease acquire/release is owned the script (per R6). The runner
        works on the assumption that the slot is held.
        """
        self._started_at = time.time()
        play_started = time.time()
        self._play_started_at = play_started
        # §81.1.9 recording: start one screenrecord chunk up front. On a
        # host with no adb serial the recorder is auto-disabled; the
        # runner still runs normally, only the run video is missing.
        if self.video.start():
            self._log("video_start", cycle_index=-1,
                      run_id=self.video._run_id,   # type: ignore[attr-defined]
                      chunks_target=int(self.config.max_runtime_s / 150) + 1)
        else:
            self._log("video_disabled", cycle_index=-1,
                      reason=self.video.disabled_reason)
        self._log("run_start", cycle_index=-1,
                  userinterface=self.userinterface,
                  device_model=self.data["device_model"],
                  max_runtime_s=self.config.max_runtime_s,
                  max_cycles=self.config.max_cycles)
        last_step_started = time.time()
        cycle = 0
        while True:
            now = time.time()
            play_s = now - play_started
            if play_s >= self.config.max_runtime_s:
                self.data["stop_reason"] = "time_cap"
                break
            if cycle >= self.config.max_cycles:
                self.data["stop_reason"] = "max_cycles"
                break
            action_started = time.time()
            verdict = self._step_cycle(cycle, action_started)
            cycle += 1
            # §81.1.9 video rotate after each cycle. Cheap when disabled
            # (returns None immediately); never raises.
            self.video.maybe_rotate()
            if verdict == "continue":
                # Game_BOTS rule 1: don't fire twice in the lag window.
                self._wait_react_s(action_started)
                continue
            # verdict is a stop reason
            if verdict in ("guard", "device_offline"):
                break
            break

        # §81.1.9 video finalize.
        video_path = self.video.stop()
        self.data["run_video_path"] = video_path or ""
        self.data["run_video_disabled_reason"] = self.video.disabled_reason
        self.data["run_video_chunk_count"] = len(self.video.chunks)

        self.data["play_duration_s"] = round(time.time() - play_started, 2)
        self.data["attack_attempted"] = False
        self._finalise()
        # Always log the closing event for the report.
        self._log("run_stop", cycle_index=-1, stop_reason=self.data["stop_reason"],
                  play_duration_s=self.data["play_duration_s"],
                  cycles_observed=cycle,
                  cycles_completed=self.data["cycles_completed"],
                  run_video_path=self.data["run_video_path"],
                  run_video_chunks=self.data["run_video_chunk_count"],
                  run_video_disabled_reason=self.data["run_video_disabled_reason"],
                  kpis={k: self.data[k] for k in
                        ("gold_gained", "elixir_gained", "dark_elixir_gained",
                         "troops_trained", "troops_donated",
                         "capital_chests_collected", "dailies_collected",
                         "actions_fired", "guard_scan_count",
                         "no_observation_cycles", "transition_cycles",
                         "buy_surface_refused", "idle_seconds",
                         "account_warning_seen", "attack_attempted")})
        # Expose the event log on the returned dict so the report can pick
        # it up without holding a Python reference to the runner.
        self.data["event_log"] = list(self.log)
        self.data["cycles_observed"] = cycle
        return self.data

    def _wait_react_s(self, since: float) -> None:
        """Slept at most REACT_S after the previous action, in case the
        capture pipeline lags and we don't want to fire twice on the same
        frame (GAME_BOTS §2 rule 1)."""
        elapsed = time.time() - since
        if elapsed < REACT_S:
            time.sleep(REACT_S - elapsed)

    # --- finishing ------------------------------------------------------------

    def _finalise(self) -> None:
        if self.data["stop_reason"] == "":
            self.data["stop_reason"] = "completed"
        self.data["success"] = self.data["stop_reason"] in ("time_cap", "max_cycles")
        if not self.data["success"]:
            log.info("coc run stop_reason=%s", self.data["stop_reason"])

    # --- public helpers (used by tests + scripts) -----------------------------

    def step_cycle_for_tests(self, cycle_index: int) -> str:
        """Test entry point: one full cycle against the live device.

        Synthetic-input tests inject an in-memory ``device`` and inject
        ``frame()`` etc. through the same surface, so they can call this
        without going through ``run()``.
        """
        return self._step_cycle(cycle_index, time.time())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _substring_scan(text: str) -> bool:
    """Substring match used by the §R5 guard scan; R5 fails closed on any
    catalogue match."""
    if not text:
        return False
    lowered = text.lower()
    return any(s in lowered for s in R5_SUBSTRINGS)


# ---------------------------------------------------------------------------
# KPI summary (mirrors game2048.summary)
# ---------------------------------------------------------------------------

def summary(data: Dict[str, Any], success: bool, error: str = "") -> str:
    lines = [
        "CLASH_OF_CLANS_SUMMARY",
        f"Userinterface: {data.get('userinterface', '')} (device model {data.get('device_model', '')})",
        f"Cycles: {data.get('cycles_completed', 0)} / actions: {data.get('actions_fired', 0)}",
        f"Gold gained: {data.get('gold_gained', 0)}, elixir {data.get('elixir_gained', 0)}, "
        f"dark {data.get('dark_elixir_gained', 0)}",
        f"Trained: {data.get('troops_trained', 0)}, donated: {data.get('troops_donated', 0)}",
        f"Capital chests: {data.get('capital_chests_collected', 0)}, "
        f"dailies: {data.get('dailies_collected', 0)}",
        f"Guard scans: {data.get('guard_scan_count', 0)} (warning seen: {data.get('account_warning_seen', False)})",
        f"Buy-surface taps refused: {data.get('buy_surface_refused', 0)}",
        f"Idle seconds: {data.get('idle_seconds', 0)}, play duration: {data.get('play_duration_s', 0)}s",
        f"Attack attempted: {data.get('attack_attempted', False)}",
        f"Stop reason: {data.get('stop_reason', '')}",
        f"Result: {'PASS' if success else 'FAIL'}",
    ]
    if error:
        lines.append(f"Error: {error}")
    return "\n".join(lines)


def kpi_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    """Subset of ``data`` the script writes to ``script_results.metadata``.

    Locked to the column list from TASK-81 §81.1 KPIs (lines 206-224):
    gold / elixir / dark_elixir / troops_trained / troops_donated /
    capital_chests_collected / dailies_collected / cycles_completed /
    attack_attempted / idle_seconds / account_warning_seen / stop_reason /
    userinterface / device_model / play_duration_s.

    Plus the scoring fields the report needs:

    * ``event_log_count`` -- number of events ``GameRunner.log`` ended with,
      so a ``summary`` can show "X cycles observed, Y events logged";
    * ``cycles_observed`` -- cycles the loop ran (NOT the §81.1.2 full chain);
    * ``event_log`` -- the full event stream (writes go to
      ``script_results.metadata.event_log``; sized as JSON, may be long,
      typically < 100 KB for a 30 min / 200-cycle run).
    """
    keys = (
        "gold_gained", "elixir_gained", "dark_elixir_gained",
        "troops_trained", "troops_donated",
        "capital_chests_collected", "dailies_collected",
        "cycles_completed", "cycles_observed",
        "attack_attempted", "account_warning_seen",
        "stop_reason",
        "userinterface", "device_model",
        "play_duration_s", "idle_seconds",
        "actions_fired", "guard_scan_count",
        "no_observation_cycles", "transition_cycles",
        "buy_surface_refused",
        # §81.1.9 run video
        "run_video_path", "run_video_r2_url",
        "run_video_chunk_count", "run_video_disabled_reason",
        # §81.1.10 tutorial
        "tutorial_dialogs_seen", "tutorial_complete",
        "tutorial_current_step", "tutorial_past_steps",
    )
    out = {k: data[k] for k in keys if k in data}
    if "event_log" in data:
        out["event_log_count"] = len(data["event_log"])
        out["event_log"] = data["event_log"]
    return out


def resolve_userinterface(requested: Optional[str], device_model: str, team_id: str) -> Optional[str]:
    """The ``clashofclans-*`` userinterface for this device.

    Mirror of ``game2048.resolve_userinterface``; lives here so the script
    does not have to import the runner only to discover the UI name.
    """
    if requested and requested.startswith(UI_PREFIX):
        return requested
    from shared.src.lib.config.device_capabilities import model_matches_any
    from shared.src.lib.database.userinterface_db import get_all_userinterfaces
    for ui in sorted(get_all_userinterfaces(team_id) or [], key=lambda u: u.get("name", "")):
        if ui.get("name", "").startswith(UI_PREFIX) and model_matches_any(device_model, ui.get("models") or []):
            return ui["name"]
    return None
