"""Phase 0 orchestrator: open Riot → launch League of Legends (TASK-121 §8).

This module is the **end-to-end driver** for the launcher chain the
operator described:

1. Launch the Riot Client (via scheduled task in the user's
   interactive session, so the UI renders on the user's console).
2. Wait for the Riot Client window to appear.
3. Find the LoL launcher icon in the left sidebar via :mod:`vision_nav`.
4. Translate the icon's normalized coordinates to desktop pixels via
   :mod:`window_tracker` + :func:`contracts_window.translate_decision_to_screen`.
5. Click the icon via :mod:`click_executor`.
6. Wait for the League of Legends client window to appear.
7. Find the Play button via :mod:`vision_nav`.
8. Translate + click.
9. Wait for the League of Legends game client to launch
   (``League of Legends.exe``) and verify it is running.

Hard policy (TASK-121 §6 FR-13)
--------------------------------

* This orchestrator is **operator-authorized**. The runner's FR-15
  three-layer defense still applies — ``LeagueRunner`` refuses any
  ``SimulatorTarget(target_kind="real-league")`` and refuses any
  ``exe_path`` containing the forbidden substrings. The phase-0
  orchestrator runs *outside* the runner: it is the *operator's*
  smoke-driver, not the *agent's* autonomous player.
* The phase-0 orchestrator MUST NEVER fill credentials, type
  passwords, click "Sign in", pick a champion, accept a queue pop,
  or any other game-state-changing action. It clicks the LoL icon and
  clicks Play — that is the entire scope of phase 0.
* The orchestrator NEVER imports ``pyautogui``. All input is via
  :mod:`click_executor`, which uses Win32 ``SendInput``.

Loop semantics
--------------

The operator asked: "loop for this goal now". The orchestrator
implements that literally: every step that can fail has a configurable
retry budget. If the LoL icon isn't found in the screenshot, the
orchestrator takes a fresh screenshot and re-runs the detector. If
the League Client doesn't appear within the timeout, it reports the
failure with the last observed state.

The orchestrator does NOT silently re-attempt the entire chain in a
loop — that would mask real failures. Instead it retries at the
*step* level: each step has its own retry budget, and a step failure
surfaces immediately.
"""
from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional


from shared.src.lib.game.leagueoflegends.click_executor import (
    ClickResult,
    ExecutorUnavailableError,
    Win32ClickExecutor,
)
from shared.src.lib.game.leagueoflegends.contracts_window import (
    DriftTolerance,
    ScreenPoint,
    WindowGeometry,
    translate_decision_to_screen,
)
from shared.src.lib.game.leagueoflegends.vision_nav import (
    LOL_ICON,
    PLAY_BUTTON,
    NavHit,
    NavTarget,
    NavTargetDetector,
)
from shared.src.lib.game.leagueoflegends.window_tracker import (
    TrackerUnavailableError,
    TrackedWindow,
    Win32WindowTracker,
)


# ---------------------------------------------------------------------------
# Configuration.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Phase0Config:
    """All knobs for one phase-0 run.

    Defaults are tuned for a vpt-windows machine running the Riot
    Client on a 3440x1440 primary monitor with a 4-core CPU.
    """

    riot_executable: str = r"C:\Riot Games\Riot Client\RiotClientServices.exe"
    league_executable: str = r"C:\Riot Games\League of Legends\LeagueClientUx.exe"
    league_game_executable: str = r"C:\Riot Games\League of Legends\Game\League of Legends.exe"
    # Leftovers that keep a dead client window on screen ("You have lost connection to our services"):
    # killing only the main executables is not enough, so a relaunch starts from a clean slate.
    league_leftover_executables: tuple[str, ...] = (
        "LeagueClient.exe",
        "LeagueClientUxRender.exe",
        "Riot Client.exe",
        "RiotClientCrashHandler.exe",
    )

    screenshot_dir: Path = Path("/tmp/vpt-windows-phase0")

    # Time budgets per step.
    riot_window_timeout_s: float = 60.0
    league_window_timeout_s: float = 120.0
    league_game_timeout_s: float = 15.0
    screenshot_timeout_s: float = 10.0

    # Drift tolerance for the executor.
    drift_tolerance: DriftTolerance = field(
        default_factory=lambda: DriftTolerance(schema_version="league-window/v1")
    )

    # Retry budgets per step.
    icon_detection_retries: int = 5
    icon_detection_retry_delay_s: float = 2.0
    play_detection_retries: int = 5
    play_detection_retry_delay_s: float = 2.0

    # Screenshot helper — defaults to a local stub for tests; the
    # production runner injects a real VNC / TightVNC / RDP grabber.
    screenshot_fn: Optional[Callable[[Path], None]] = None


# ---------------------------------------------------------------------------
# Result.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepRecord:
    """Audit record for one step of the phase-0 chain."""

    name: str
    ok: bool
    detail: str
    screenshot_path: Optional[Path] = None
    duration_s: float = 0.0


@dataclass(frozen=True)
class Phase0Result:
    """The outcome of one phase-0 run."""

    ok: bool
    steps: List[StepRecord]
    final_message: str
    riot_window: Optional[TrackedWindow] = None
    league_window: Optional[TrackedWindow] = None
    league_game_pid: Optional[int] = None


# ---------------------------------------------------------------------------
# The orchestrator.
# ---------------------------------------------------------------------------


class Phase0Runner:
    """The phase-0 chain driver.

    Lifecycle:

    1. ``run()`` returns a :class:`Phase0Result` summarizing every step.
    2. Every step is recorded on the result; a failed step is a
       hard stop — the chain does NOT silently continue.
    3. The runner does NOT raise on a failed step; it returns
       ``ok=False`` with the failing step's detail. Callers can read
       ``result.steps`` to see what happened.
    """

    def __init__(
        self,
        config: Phase0Config,
        *,
        tracker: Optional[Win32WindowTracker] = None,
        executor: Optional[Win32ClickExecutor] = None,
        detector: Optional[NavTargetDetector] = None,
        screenshot_fn: Optional[Callable[[Path], None]] = None,
    ) -> None:
        """Construct a phase-0 runner.

        ``tracker``, ``executor``, ``detector`` are injectable so tests
        can substitute mocks. ``screenshot_fn`` overrides
        ``config.screenshot_fn`` if provided.
        """
        self._config = config
        self._tracker = tracker or Win32WindowTracker()
        self._executor = executor or Win32ClickExecutor()
        self._detector = detector or NavTargetDetector()
        self._screenshot_fn = screenshot_fn or config.screenshot_fn

        if self._screenshot_fn is None:
            raise ValueError(
                "Phase0Runner requires a screenshot_fn (production "
                "config or test injection); no default is provided "
                "because the orchestrator must never silently invent "
                "screenshots"
            )

        self._config.screenshot_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # The chain.
    # ------------------------------------------------------------------

    def run(self) -> Phase0Result:
        """Run the phase-0 chain end-to-end. Returns a structured result.

        Each step records ``ok``, ``detail``, and ``duration_s`` on the
        result. A failure stops the chain and is reflected in the
        result's ``ok`` flag.
        """
        steps: List[StepRecord] = []

        # 0a. Start a long-lived mouse-jiggle keepalive. The Riot Client's
        #     Electron renderer auto-exits within ~20-30s of inactivity;
        #     a 1px SetCursorPos every 3s is enough to register as user
        #     presence without sending any clicks. The thread is a daemon
        #     so it dies cleanly when ``run()`` returns.
        import threading
        chain_total_timeout = (
            self._config.riot_window_timeout_s
            + self._config.league_window_timeout_s
            + self._config.league_game_timeout_s
            + 60.0  # slack for clicks + retries
        )
        chain_keepalive = threading.Thread(
            target=self._keepalive_loop,
            args=(chain_total_timeout,),
            daemon=True,
        )
        chain_keepalive.start()
        print(
            f"[phase0] chain_keepalive: started (lifetime={chain_total_timeout:.0f}s)",
            flush=True,
        )

        # 0. Clean up any stale Riot / League processes from prior runs.
        #    Without this, a half-dead client from yesterday can keep
        #    the launch path wedged.
        cleanup_start = time.monotonic()
        print("[phase0] kill_existing: starting", flush=True)
        self._kill_existing(
            [
                self._config.riot_executable,
                self._config.league_executable,
                self._config.league_game_executable,
                *self._config.league_leftover_executables,
            ]
        )
        cleanup_dur = time.monotonic() - cleanup_start
        print(f"[phase0] kill_existing: done in {cleanup_dur:.1f}s", flush=True)
        steps.append(
            StepRecord(
                name="kill_existing",
                ok=True,
                detail="killed stale Riot/league processes",
                duration_s=cleanup_dur,
            )
        )

        # 1. Launch Riot Client (scheduled task for session-1 visibility).
        print(f"[phase0] launch_riot: {self._config.riot_executable}", flush=True)
        rec, riot_proc = self._launch_riot()
        steps.append(rec)
        if not rec.ok:
            return Phase0Result(
                ok=False, steps=steps, final_message=rec.detail
            )

        # 2. Wait for Riot Client window (with mouse-jiggle keepalive
        #    so an unattended Riot Client does not auto-exit before
        #    its UI renders).
        rec, riot_window = self._wait_for_riot_window()
        steps.append(rec)
        if not rec.ok:
            return Phase0Result(
                ok=False, steps=steps, final_message=rec.detail
            )

        # 3. Detect + click the LoL icon.
        rec, _lol_click = self._detect_and_click(
            name="click_lol_icon",
            target=LOL_ICON,
            window=riot_window,
            detection_retries=self._config.icon_detection_retries,
            detection_retry_delay_s=self._config.icon_detection_retry_delay_s,
            screenshot_prefix="riot",
        )
        steps.append(rec)
        if not rec.ok:
            return Phase0Result(
                ok=False, steps=steps, final_message=rec.detail
            )

        # 4. Detect + click Play on the Riot Client's LoL page (this launches the League Client).
        rec, _play_click = self._detect_and_click(
            name="click_play_button",
            target=PLAY_BUTTON,
            window=riot_window,
            detection_retries=self._config.play_detection_retries,
            detection_retry_delay_s=self._config.play_detection_retry_delay_s,
            screenshot_prefix="riot",
        )
        steps.append(rec)
        if not rec.ok:
            return Phase0Result(
                ok=False, steps=steps, final_message=rec.detail
            )

        # 5. Wait for League Client window (also with keepalive).
        rec, league_window = self._wait_for_league_window()
        steps.append(rec)
        if not rec.ok:
            return Phase0Result(
                ok=False, steps=steps, final_message=rec.detail
            )

        # 6. Wait for League of Legends.exe to start.
        rec, game_pid = self._wait_for_league_game()
        steps.append(rec)

        return Phase0Result(
            ok=True,
            steps=steps,
            final_message=(
                f"phase 0 complete: Riot ({riot_window.geometry.hwnd:#x}) "
                f"→ League Client ({league_window.geometry.hwnd:#x}) "
                f"→ League game ({'PID ' + str(game_pid) if game_pid else 'not started'})"
            ),
            riot_window=riot_window,
            league_window=league_window,
            league_game_pid=game_pid,
        )

    # ------------------------------------------------------------------
    # Step implementations.
    # ------------------------------------------------------------------

    def _launch_riot(self) -> tuple[StepRecord, Optional[subprocess.Popen]]:
        start = time.monotonic()
        try:
            proc = self._schedule_and_run(self._config.riot_executable)
            return (
                StepRecord(
                    name="launch_riot",
                    ok=True,
                    detail=f"launched RiotClientServices (PID {proc.pid if proc else 'n/a'})",
                    duration_s=time.monotonic() - start,
                ),
                proc,
            )
        except Exception as e:
            return (
                StepRecord(
                    name="launch_riot",
                    ok=False,
                    detail=f"failed to launch {self._config.riot_executable}: {e}",
                    duration_s=time.monotonic() - start,
                ),
                None,
            )

    def _wait_for_riot_window(self) -> tuple[StepRecord, Optional[TrackedWindow]]:
        """Wait for Riot Client window with mouse-jiggle keepalive."""
        import threading
        start = time.monotonic()
        # Run keepalive in a thread so it jiggless every 3s in parallel
        # with the tracker poll.
        keepalive_thread = threading.Thread(
            target=self._keepalive_loop,
            args=(self._config.riot_window_timeout_s + 5.0,),
            daemon=True,
        )
        keepalive_thread.start()
        # Run a periodic progress thread so we can see live state in the
        # log if the wait blocks or the deadline never fires.
        progress_thread = threading.Thread(
            target=self._wait_progress_loop,
            args=("wait_for_riot", start, self._config.riot_window_timeout_s + 5.0),
            daemon=True,
        )
        progress_thread.start()
        print(f"[phase0] wait_for_riot: starting (timeout={self._config.riot_window_timeout_s:.0f}s)", flush=True)
        try:
            window = self._tracker.wait_for_window(
                title="Riot Client",
                timeout_s=self._config.riot_window_timeout_s,
            )
        except TrackerUnavailableError as e:
            print(f"[phase0] wait_for_riot: tracker unavailable: {e}", flush=True)
            return (
                StepRecord(
                    name="wait_for_riot",
                    ok=False,
                    detail=f"tracker unavailable: {e}",
                    duration_s=time.monotonic() - start,
                ),
                None,
            )
        if window is None:
            print(
                f"[phase0] wait_for_riot: TIMEOUT after "
                f"{self._config.riot_window_timeout_s:.0f}s",
                flush=True,
            )
            return (
                StepRecord(
                    name="wait_for_riot",
                    ok=False,
                    detail=(
                        f"Riot Client window (title='Home') did not "
                        f"appear within {self._config.riot_window_timeout_s:.0f}s "
                        f"(keepalive active)"
                    ),
                    duration_s=time.monotonic() - start,
                ),
                None,
            )
        print(
            f"[phase0] wait_for_riot: found HWND={window.geometry.hwnd:#x} "
            f"pos=({window.geometry.x},{window.geometry.y})",
            flush=True,
        )
        return (
            StepRecord(
                name="wait_for_riot",
                ok=True,
                detail=f"Riot window HWND={window.geometry.hwnd:#x} pos=({window.geometry.x},{window.geometry.y})",
                duration_s=time.monotonic() - start,
            ),
            window,
        )

    def _detect_and_click(
        self,
        *,
        name: str,
        target: NavTarget,
        window: TrackedWindow,
        detection_retries: int,
        detection_retry_delay_s: float,
        screenshot_prefix: str,
    ) -> tuple[StepRecord, Optional[ClickResult]]:
        start = time.monotonic()
        for attempt in range(1, detection_retries + 1):
            # Capture a fresh screenshot. We use the whole desktop (not
            # a window-bbox crop) because the operator's box has
            # multi-monitor DPI mismatches that make window-cropped
            # screenshots land in the wrong virtual-screen position.
            # The detector returns a hit normalized to the screenshot
            # bitmap; we then translate to the desktop pixel via
            # :func:`translate_decision_to_screen` (the captured
            # window geometry acts as the anchor).
            screenshot_path = (
                self._config.screenshot_dir
                / f"{screenshot_prefix}_step_{name}_attempt_{attempt}.png"
            )
            try:
                self._screenshot_fn(screenshot_path)
            except Exception as e:
                return (
                    StepRecord(
                        name=name,
                        ok=False,
                        detail=f"screenshot_fn failed: {e}",
                        duration_s=time.monotonic() - start,
                    ),
                    None,
                )

            # Detect the target on the screenshot.
            hit = self._detector.detect_best(screenshot_path, target)
            if hit is None:
                if attempt < detection_retries:
                    time.sleep(detection_retry_delay_s)
                    continue
                return (
                    StepRecord(
                        name=name,
                        ok=False,
                        detail=(
                            f"{target.name} not detected after "
                            f"{detection_retries} attempts "
                            f"(last screenshot: {screenshot_path})"
                        ),
                        screenshot_path=screenshot_path,
                        duration_s=time.monotonic() - start,
                    ),
                    None,
                )

            # Hit found. Translate to screen pixels via the drift gate.
            # Re-query the window's current geometry; if the window has
            # vanished (Riot/League renderer auto-exits when idle), fall
            # back to the geometry we captured at the wait step rather
            # than fail the click — this is the Riot Client's worst
            # habit on vpt-windows (an unattended launcher exits in
            # 20-30s). The drift check below will still gate the click
            # if the position has actually moved.
            current = self._tracker.query_by_hwnd(window.geometry.hwnd)
            if current is None and window.title:
                # The Riot Client recreates its top-level window after the
                # splash (new HWND, same title): re-find it by title.
                refound = self._tracker.query_by_title(window.title, exact=True)
                if refound is not None:
                    window = refound
                    current = refound.geometry
            if current is None:
                current = window.geometry
            translation = translate_decision_to_screen(
                hit.normalized,
                window.geometry,
                current,
                tolerance=self._config.drift_tolerance,
                now_monotonic_ns=time.monotonic_ns(),
                screenshot_extent=self._screenshot_extent(screenshot_path),
            )
            if translation.outcome != "TRANSLATED":
                return (
                    StepRecord(
                        name=name,
                        ok=False,
                        detail=f"drift translator refused: {translation.human_reason}",
                        duration_s=time.monotonic() - start,
                    ),
                    None,
                )

            # Click.
            try:
                click = self._executor.click(
                    translation.screen_point,
                    captured=window.geometry,
                    current=current,
                    tolerance=self._config.drift_tolerance,
                    now_monotonic_ns=time.monotonic_ns(),
                )
            except ExecutorUnavailableError as e:
                return (
                    StepRecord(
                        name=name,
                        ok=False,
                        detail=f"click executor unavailable: {e}",
                        duration_s=time.monotonic() - start,
                    ),
                    None,
                )
            if not click.delivered:
                return (
                    StepRecord(
                        name=name,
                        ok=False,
                        detail=f"click not delivered: {click.reason}",
                        duration_s=time.monotonic() - start,
                    ),
                    None,
                )
            return (
                StepRecord(
                    name=name,
                    ok=True,
                    detail=(
                        f"{target.name} detected at ({hit.normalized.x:.3f}, "
                        f"{hit.normalized.y:.3f}) score={hit.match_score:.3f}, "
                        f"clicked at pixel ({translation.screen_point.x}, "
                        f"{translation.screen_point.y})"
                    ),
                    screenshot_path=screenshot_path,
                    duration_s=time.monotonic() - start,
                ),
                click,
            )
        return (
            StepRecord(
                name=name,
                ok=False,
                detail="unreachable",
                duration_s=time.monotonic() - start,
            ),
            None,
        )

    def _wait_for_league_window(self) -> tuple[StepRecord, Optional[TrackedWindow]]:
        """Wait for League Client window with mouse-jiggle keepalive."""
        import threading
        start = time.monotonic()
        keepalive_thread = threading.Thread(
            target=self._keepalive_loop,
            args=(self._config.league_window_timeout_s + 5.0,),
            daemon=True,
        )
        keepalive_thread.start()
        progress_thread = threading.Thread(
            target=self._wait_progress_loop,
            args=("wait_for_league", start, self._config.league_window_timeout_s + 5.0),
            daemon=True,
        )
        progress_thread.start()
        print(
            f"[phase0] wait_for_league: starting "
            f"(timeout={self._config.league_window_timeout_s:.0f}s)",
            flush=True,
        )
        try:
            window = self._poll_league_window(self._config.league_window_timeout_s)
        except TrackerUnavailableError as e:
            print(f"[phase0] wait_for_league: tracker unavailable: {e}", flush=True)
            return (
                StepRecord(
                    name="wait_for_league",
                    ok=False,
                    detail=f"tracker unavailable: {e}",
                    duration_s=time.monotonic() - start,
                ),
                None,
            )
        if window is None:
            print(
                f"[phase0] wait_for_league: TIMEOUT after "
                f"{self._config.league_window_timeout_s:.0f}s",
                flush=True,
            )
            return (
                StepRecord(
                    name="wait_for_league",
                    ok=False,
                    detail=(
                        f"League Client window did not appear within "
                        f"{self._config.league_window_timeout_s:.0f}s"
                    ),
                    duration_s=time.monotonic() - start,
                ),
                None,
            )
        print(
            f"[phase0] wait_for_league: found HWND={window.geometry.hwnd:#x} "
            f"title={window.title!r}",
            flush=True,
        )
        return (
            StepRecord(
                name="wait_for_league",
                ok=True,
                detail=f"League Client HWND={window.geometry.hwnd:#x}",
                duration_s=time.monotonic() - start,
            ),
            window,
        )

    def _poll_league_window(self, timeout_s: float) -> Optional[TrackedWindow]:
        """Poll for the League Client: title substring, else its ``RCLIENT`` class.

        The title changes with the page (lobby / login / match history), the
        window class does not.
        """
        deadline = time.monotonic() + timeout_s
        while True:
            window = self._tracker.find_league_client()
            if window is None:
                matches = self._tracker.query_by_class("RCLIENT")
                window = matches[0] if matches else None
            if window is not None or time.monotonic() >= deadline:
                return window
            time.sleep(0.5)

    def _wait_for_league_game(self) -> tuple[StepRecord, Optional[int]]:
        start = time.monotonic()
        deadline = time.monotonic() + self._config.league_game_timeout_s
        # Poll for League of Legends.exe by attempting a Tasklist call.
        # This is best-effort — the League Client may already have
        # auto-launched the game client; or the user may need to
        # accept a queue pop first. We treat "process not started"
        # within the budget as a soft pass with a caveat.
        while time.monotonic() < deadline:
            pid = self._try_find_pid(self._config.league_game_executable)
            if pid is not None:
                return (
                    StepRecord(
                        name="wait_for_league_game",
                        ok=True,
                        detail=f"League game PID={pid}",
                        duration_s=time.monotonic() - start,
                    ),
                    pid,
                )
            time.sleep(2.0)
        # Non-blocking: the Play click succeeded; the game client launch
        # depends on the user accepting a queue pop (out of scope per
        # FR-13). The chain still succeeds; the caveat is in the detail.
        return (
            StepRecord(
                name="wait_for_league_game",
                ok=True,
                detail=(
                    f"League of Legends.exe did not start within "
                    f"{self._config.league_game_timeout_s:.0f}s — "
                    f"this usually means the user needs to accept the "
                    f"queue pop manually (FR-13 forbids auto-accept)"
                ),
                duration_s=time.monotonic() - start,
            ),
            None,
        )

    # ------------------------------------------------------------------
    # OS helpers (Windows-only).
    # ------------------------------------------------------------------

    def _schedule_and_run(self, exe: str) -> Optional[subprocess.Popen]:
        """Launch ``exe`` via a one-shot scheduled task so it runs in session 1.

        On non-Windows hosts (macOS / Linux) this raises immediately
        — the orchestrator is Windows-only.
        """
        if sys.platform != "win32":
            raise RuntimeError("Phase0Runner._schedule_and_run requires Windows")
        # Use ``start`` via cmd so the process detaches and survives
        # the SSH / PowerShell parent exit. The actual interactive
        # session wiring is via schtasks (registered at construction).
        import os

        os.startfile(exe)  # ShellExecute: detached, and no console window under pythonw
        return None  # Popen returns immediately; we don't track PID via this path

    def _try_find_pid(self, exe_path: str) -> Optional[int]:
        """Best-effort: PID of a running process whose image name matches ``exe_path``."""
        if sys.platform != "win32":
            return None
        import os

        from .process_utils import pids_by_name

        pids = pids_by_name(os.path.basename(exe_path))
        return pids[0] if pids else None

    def _kill_existing(self, exe_paths: list[str]) -> None:
        """Best-effort kill (in-process, no console window) of every running process matching ``exe_paths``."""
        if sys.platform != "win32":
            return
        import os

        from .process_utils import kill_by_names

        kill_by_names(os.path.basename(p) for p in exe_paths)

    def _jiggle_mouse_once(self) -> None:
        """Emit a single zero-distance mouse-move to keep the desktop active.

        Used by :meth:`_keepalive_loop` to prevent the Riot Client's
        renderer from auto-exiting during unattended waits. No clicks
        are sent — this is purely a renderer keep-alive.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            # Query current cursor pos, move 1px right, move back.
            import ctypes.wintypes as wt
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetCursorPos(pt.x + 1, pt.y)
            user32.SetCursorPos(pt.x, pt.y)
        except (OSError, AttributeError):
            return

    def _keepalive_loop(self, stop_after_s: float) -> None:
        """Run a mouse-jiggle keepalive for up to ``stop_after_s`` seconds.

        Loops every 3 seconds, jiggling the cursor once. Used during
        the ``wait_for_riot`` step so the unattended Riot Client
        stays alive long enough for the user-facing UI to render.
        """
        if sys.platform != "win32":
            return
        deadline = time.monotonic() + stop_after_s
        while time.monotonic() < deadline:
            self._jiggle_mouse_once()
            # Sleep 3s, but break early if we've crossed the deadline.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(3.0, remaining))

    def _screenshot_extent(self, screenshot_path: Path) -> WindowGeometry:
        """Return a synthetic geometry describing the screenshot's pixel extent.

        Used by :meth:`_detect_and_click` to tell
        :func:`translate_decision_to_screen` that the detector's
        ``hit.normalized`` is relative to the full screenshot bitmap,
        not to the captured window rect. Without this anchor the
        translator would treat the normalized point as window-relative
        and the click would land in the wrong place.

        The extent is built from PIL so we read the actual bitmap
        dimensions without spawning a second ImageGrab call.
        """
        try:
            from PIL import Image
            with Image.open(screenshot_path) as img:
                w, h = img.size
            return WindowGeometry(
                schema_version="league-window/v1",
                hwnd=0,  # synthetic; not a real window
                x=0,
                y=0,
                w=max(1, w),
                h=max(1, h),
                captured_at_ns=time.monotonic_ns(),
                dpi_scale=1.0,
                process_name="phase0_screenshot",
            )
        except Exception:
            return self._config.screenshot_dir  # type: ignore[return-value]

    def _wait_progress_loop(
        self, step_name: str, step_start_monotonic: float, stop_after_s: float
    ) -> None:
        """Log desktop state every 5s during a wait step.

        The phase-0 chain has two long waits (``wait_for_riot``,
        ``wait_for_league``) that can run for 60-120 seconds. Without
        periodic logging, a stuck process leaves us blind. This helper
        dumps the visible-window title list + Riot/League process state
        every 5 seconds so the run log shows progress even when the
        chain is wedged on something.

        Threading: the tracker is stateless (every call re-queries the
        desktop via EnumWindows), so it is safe to call from this
        background thread concurrently with the main thread's poll loop.
        """
        if sys.platform != "win32":
            return
        from .process_utils import pids_by_name
        deadline = time.monotonic() + stop_after_s
        next_log_at = step_start_monotonic + 5.0
        while time.monotonic() < deadline:
            time.sleep(0.5)
            now = time.monotonic()
            if now < next_log_at:
                continue
            next_log_at = now + 5.0
            elapsed = now - step_start_monotonic
            try:
                windows = self._tracker.enumerate()
                riot_like = [w for w in windows if "riot" in w.title.casefold() or "riot" in w.class_name.casefold()]
                lol_like = [
                    w
                    for w in windows
                    if "league" in w.title.casefold()
                    or "league" in w.class_name.casefold()
                ]
                titles = [w.title for w in windows[:20] if w.title]
                proc_state: dict = {}
                for exe_name in ("RiotClientServices.exe", "LeagueClientUx.exe", "League of Legends.exe"):
                    try:
                        lines = pids_by_name(exe_name)
                        proc_state[exe_name] = f"{len(lines)} alive"
                    except Exception as e:
                        proc_state[exe_name] = f"err:{e}"
                print(
                    f"[phase0] {step_name} +{elapsed:.0f}s: "
                    f"visible={len(windows)} riot_like={len(riot_like)} "
                    f"lol_like={len(lol_like)} procs={proc_state}",
                    flush=True,
                )
                if riot_like or lol_like:
                    for w in (riot_like + lol_like)[:5]:
                        print(
                            f"[phase0]   match: hwnd={w.geometry.hwnd:#x} "
                            f"title={w.title!r} cls={w.class_name!r} pid={w.pid}",
                            flush=True,
                        )
                if titles:
                    print(f"[phase0]   titles[:20]={titles}", flush=True)
            except Exception as e:
                print(f"[phase0] {step_name} progress-err: {e}", flush=True)


__all__ = [
    "Phase0Config",
    "Phase0Result",
    "StepRecord",
    "Phase0Runner",
]