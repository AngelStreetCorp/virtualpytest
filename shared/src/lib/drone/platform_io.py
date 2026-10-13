"""
Platform side of the drone games (TASK-32): the same DroneIO / Reporter protocols as the local
runner, implemented through the host's executors only.

  PlatformDroneIO   commands -> ExecutionOrchestrator.execute_actions (remote controller `tello`),
                    frames   -> the device's AV controller captures (vpt-stream ingests the
                                drone's UDP video), telemetry -> the controller's telemetry command.
  PlatformReporter  one report step per game step through context.record_step_immediately.

Nothing here talks UDP or opens a video socket: the controller owns the drone link and
vpt-stream owns the video port, so the script never competes with the host for either.
"""

import asyncio
import os
import tempfile
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from shared.src.lib.utils import cv2_io

FRESH_TIMEOUT_S = 4.0
TELEMETRY_MAX_AGE_S = 1.0


def _capture_path(device) -> Optional[str]:
    from shared.src.lib.utils.device_utils import capture_screenshot
    return capture_screenshot(device)


def _frame_time(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


class PlatformDroneIO:
    """DroneIO for one `tello` device, through the action executor and the AV captures."""

    def __init__(self, device, context, name: str, index: int):
        self.device, self.context = device, context
        self.name, self.index = name, index
        self._tel: Dict[str, Any] = {}
        self._tel_at = 0.0
        self._lock = threading.Lock()

    # --- commands ----------------------------------------------------------------
    def _run(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        from backend_host.src.orchestrator.execution_orchestrator import ExecutionOrchestrator
        action = {"command": command, "action_type": "remote", "params": dict(params), "wait_time": 0}
        # context=None: a drone game sends hundreds of commands; the game reports its own steps
        # (PlatformReporter), the executor must not add one report step per command.
        return asyncio.run(ExecutionOrchestrator.execute_actions(
            self.device, [action], team_id=self.context.team_id, context=None))

    def _result(self, result: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
        out = result.get("output_data") or {}
        if out.get("telemetry"):
            with self._lock:
                self._tel, self._tel_at = dict(out["telemetry"]), time.time()
        err = result.get("error") or ""
        for r in result.get("results") or []:
            err = err or r.get("error") or ""
        return bool(result.get("success")), out, err

    def command(self, cmd: str, timeout_s: Optional[float] = None) -> Tuple[bool, str]:
        """Raw SDK text through the controller (still guarded there). (ok, reply)."""
        try:
            ok, out, err = self._result(self._run("sdk", {"cmd": cmd}))
        except Exception as e:  # executor failure: report it, never raise into the game loop
            return False, f"error {e}"
        if ok:
            return True, str(out.get("reply", "ok"))
        # The controller already retried a timeout and landed; an `error` prefix tells the game
        # not to send the command a third time.
        text = err or str(out.get("reply") or "command failed")
        return False, text if text.lower().startswith("error") else f"error {text}"

    def configure(self, **params: Any) -> bool:
        """Geofence, ceiling and start spot for this run (controller `configure`)."""
        ok, _out, _err = self._result(self._run("configure", params))
        return ok

    # --- frames and telemetry ------------------------------------------------------
    def frame(self, fresh: bool = False) -> Optional[np.ndarray]:
        """Latest capture as BGR. fresh=True waits for one written after this call started."""
        started = time.time()
        deadline = started + FRESH_TIMEOUT_S
        last: Optional[np.ndarray] = None
        while True:
            path = _capture_path(self.device)
            if path and os.path.exists(path):
                img = cv2_io.imread(path)
                if img is not None:
                    last = img
                    if not fresh or _frame_time(path) >= started:
                        return img
            if time.time() >= deadline:
                return last
            time.sleep(0.15)

    def telemetry(self) -> dict:
        with self._lock:
            if self._tel and time.time() - self._tel_at < TELEMETRY_MAX_AGE_S:
                return dict(self._tel)
        try:
            self._result(self._run("get_telemetry", {}))
        except Exception:
            pass
        with self._lock:
            return dict(self._tel)

    def close(self) -> None:
        """Land. The controller is owned by the device, not by this object."""
        try:
            self.command("land", timeout_s=20)
        except Exception:
            pass


def link_peers(ios: List[PlatformDroneIO]) -> None:
    """Give every drone's controller the other drones' dead-reckoned poses (separation guard).

    Both devices are built in this script process, so their controllers can read each other's
    guard pose directly; this is the one place the script touches a controller instead of an executor.
    """
    controllers = {io.index: io.device._get_controller("remote") for io in ios}
    for io in ios:
        me = controllers[io.index]
        others = [c for i, c in controllers.items() if i != io.index and c is not None]
        if me is not None and hasattr(me, "set_peers"):
            me.set_peers(lambda others=others: [c.pose() for c in others if c.pose() is not None])


class PlatformReporter:
    """Reporter through context.record_step_immediately, one step per game step.

    A step with a frame (the annotated winner frame, a claim frame) stores that picture as the
    step screenshot; a step without one gets a capture of the drone's own device.
    """

    def __init__(self, context, devices_by_name: Dict[str, Any]):
        self.context = context
        self.devices = devices_by_name
        self._dirs: Dict[int, str] = {}
        self._lock = threading.Lock()
        self._n = 0
        self.summary: Dict[str, Any] = {}

    def _dir(self, device) -> str:
        key = id(device)
        if key not in self._dirs:
            path = _capture_path(device)
            if path:
                from shared.src.lib.utils.build_url_utils import convert_hot_to_cold_path, is_hot_storage_path
                if is_hot_storage_path(path):
                    path = convert_hot_to_cold_path(path)
                directory = os.path.dirname(path)
            else:
                directory = tempfile.mkdtemp(prefix="drone_report_")
            os.makedirs(directory, exist_ok=True)
            self._dirs[key] = directory
        return self._dirs[key]

    def _evidence(self, drone: str, frame: Optional[np.ndarray], kind: str, n: int) -> str:
        device = self.devices.get(drone)
        if device is None and self.devices:
            device = next(iter(self.devices.values()))
        if device is None:
            return ""
        with self._lock:
            if frame is not None:
                path = os.path.join(self._dir(device), f"drone_{n:04d}_{kind}_{drone}.jpg")
                cv2_io.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
                self.context.add_screenshot(path)
                return self.context.screenshot_paths[-1] if self.context.screenshot_paths else path
            from shared.src.lib.utils.device_utils import capture_screenshot_for_script
            captured = capture_screenshot_for_script(device, self.context, f"drone_{n:04d}_{kind}_{drone}")
            return self.context.screenshot_paths[-1] if captured and self.context.screenshot_paths else ""

    def step(self, drone: str, message: str, success: bool, frame: Optional[np.ndarray] = None,
             details: Optional[dict] = None, kind: str = "turn") -> None:
        with self._lock:
            self._n += 1
            n = self._n
        started = time.time()
        # Pure bookkeeping lines ("info") do not need a picture; turns, claims and winners do.
        shot = self._evidence(drone, frame, kind, n) if (frame is not None or kind != "info") else ""
        now = time.time()
        label = f"[{drone}] {message}"
        step = {
            "success": bool(success),
            "message": label,
            "from_node": drone, "to_node": drone,
            "execution_time_ms": int((now - started) * 1000),
            "start_time": datetime.fromtimestamp(started).strftime("%H:%M:%S"),
            "end_time": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
            "screenshot_path": shot or None,
            "step_end_screenshot_path": shot or None,
            "action_screenshots": [shot] if shot else [],
            "actions": [],
            "verifications": [{"verification_type": "drone", "command": kind, "label": label,
                               "success": bool(success), "details": details or {}}],
            "verification_results": [],
            "step_category": "drone",
        }
        with self._lock:
            self.context.record_step_immediately(step)

    def finish(self, summary: dict) -> Optional[str]:
        self.summary = dict(summary)
        return None

    def flight_log_step(self, drone: str, log_path: str, summary: Optional[dict] = None) -> None:
        """Record the per-flight Tello telemetry CSV into the test report.

        Called by scripts (hide-and-seek, race, follow-me) after a flight
        finishes. The CSV is on the host filesystem; the test report gets
        a step with kind=``"flight_log"`` whose ``details`` point to the file
        and carry a few key numbers (rows, duration, peak altitude, total
        distance, battery delta). Downstream tooling (Test Reports page)
        renders the step in the timeline and lets the operator download
        the CSV.
        """
        summary = summary or {}
        details = {
            "log_path": log_path,
            "rows": summary.get("rows"),
            "duration_s": summary.get("duration_s"),
            "peak_altitude_cm": summary.get("peak_altitude_cm"),
            "total_distance_cm": summary.get("total_distance_cm"),
            "battery_start_pct": summary.get("battery_start_pct"),
            "battery_end_pct": summary.get("battery_end_pct"),
            "guard_blocks": summary.get("guard_blocks"),
            "commands_sent": summary.get("commands_sent"),
            "pose_source": summary.get("pose_source"),
        }
        self.step(
            drone, f"Flight log saved ({summary.get('rows', '?')} rows, "
                   f"{summary.get('duration_s', '?')}s)",
            True, frame=None, details=details, kind="flight_log",
        )


# --- script helpers (shared by test_scripts/drone/*.py) ---------------------------------------

def load_room_map(path: str):
    """--room_map: a JSON file (see test_scripts/drone/local/room_example.json). Required: the guard has to
    know the furniture before a drone flies. The word `sim` means the simulated room (simulator hosts only)."""
    from .roommap import RoomMap
    path = (path or "").strip()
    if not path:
        raise ValueError("--room_map is required: pass the path of the room map JSON "
                         "(copy test_scripts/drone/local/room_example.json and edit it), or `sim` for the simulator")
    if path == "sim":
        from .sim.world import default_room
        return RoomMap.from_sim_room(default_room())
    try:
        return RoomMap.load(path)
    except (OSError, ValueError, KeyError) as e:
        raise ValueError(f"cannot read room map {path!r}: {e}")


def parse_spot(text: str, index: int):
    """'x,y,yaw' in cm and degrees -> Pose on the floor; empty text -> the default start spot."""
    from .sim.world import START_SPOTS, Pose
    text = (text or "").strip()
    if not text:
        return START_SPOTS[index]
    parts = [p for p in text.replace(";", ",").split(",") if p.strip()]
    try:
        x, y = float(parts[0]), float(parts[1])
        yaw = float(parts[2]) if len(parts) > 2 else 0.0
    except (IndexError, ValueError):
        raise ValueError(f"start spot must be 'x,y,yaw' in cm and degrees, not {text!r}")
    return Pose(x, y, 0.0, yaw)


def load_peer_device(peer_id: str):
    """The second drone's device. The framework only builds the selected device, so the peer is
    built from the same .env by the controller manager (an independent Host, not the singleton)."""
    from backend_host.src.controllers.controller_manager import create_host_from_environment
    host = create_host_from_environment([peer_id])
    device = next((d for d in host.get_devices() if d.device_id == peer_id), None)
    return host, device


def setup_drones(context, device, args, count: int = 2):
    """Build the PlatformDroneIOs, configure each controller's fence and start spot, link the
    peers, and return (ios, start_poses, limits, reporter). Raises ValueError with a message
    fit for context.error_message."""
    from .safety import SafetyLimits

    devices = [device]
    context.drone_hosts = []  # keep the peer Host alive for the whole run
    if count > 1:
        peer_id = args.peer_device
        if peer_id == device.device_id:
            raise ValueError(f"--peer_device must be a different device than {device.device_id}")
        host, peer = load_peer_device(peer_id)
        context.drone_hosts.append(host)
        if peer is None:
            raise ValueError(f"peer device {peer_id!r} is not configured in the host .env")
        devices.append(peer)
    for d in devices:
        if getattr(d, "device_model", "") != "tello":
            raise ValueError(f"{d.device_id} is a {getattr(d, 'device_model', '?')!r} device, not a tello")
        if d._get_controller("remote") is None:
            raise ValueError(f"{d.device_id} has no tello remote controller (set DEVICE<n>_TELLO_IP)")

    spots = {i + 1: parse_spot(getattr(args, f"start{i + 1}", ""), i + 1) for i in range(count)}
    ios = [PlatformDroneIO(d, context, f"drone{i + 1}", i + 1) for i, d in enumerate(devices)]
    room_map = load_room_map(getattr(args, "room_map", ""))
    limits = SafetyLimits(room_w=args.room_w, room_d=args.room_d, max_h=args.max_height, room_map=room_map)
    for io in ios:
        s = spots[io.index]
        if not io.configure(room_w=args.room_w, room_d=args.room_d, max_h=args.max_height,
                            x=s.x, y=s.y, yaw=s.yaw_deg, room_map=room_map.to_dict()):
            raise ValueError(f"{io.name}: could not configure the controller geofence")
    link_peers(ios)
    reporter = PlatformReporter(context, {io.name: io.device for io in ios})
    return ios, spots, limits, reporter


def release_drones(ios: List[PlatformDroneIO]) -> None:
    """Teardown: land anything still airborne and close the UDP links. Never raises."""
    for io in ios:
        try:
            controller = io.device._get_controller("remote")
            if controller is not None:
                controller.disconnect()
        except Exception as e:
            print(f"[drone] release {io.name}: {e}")


def make_perception(kind: str, game: str):
    """(agent-side detector, referee detector, referee min confidence) for --perception.

    auto: hide and seek reads the hider's ArUco marker; the race uses the COCO detector when
    DRONE_COCO_MODEL points at a model file, otherwise the vision model. The referee's detector is
    always stricter than the agent's own.
    """
    from .perception import ArucoDetector, CocoDetector, VlmDetector
    if kind == "auto":
        if game == "hide":
            kind = "aruco"
        else:
            kind = "coco" if os.path.isfile(os.environ.get("DRONE_COCO_MODEL", "")) else "vlm"
    if kind == "aruco":
        if game != "hide":
            raise ValueError("--perception aruco only finds drones; the race needs coco or vlm")
        return ArucoDetector(), ArucoDetector(min_side_px=14.0), 0.0
    if kind == "coco":
        if game == "hide":
            raise ValueError("--perception coco has no drone class; hide and seek needs aruco or vlm")
        return CocoDetector(min_conf=0.35), CocoDetector(min_conf=0.5), 0.5
    if kind == "vlm":
        return VlmDetector(min_conf=0.5), VlmDetector(min_conf=0.7), 0.7
    raise ValueError(f"unknown perception {kind!r}")


def make_seek_agent(kind: str, perception, limits):
    """One searching agent: scan (rotate and sweep, no model) or llm (vision model, falls back to scan)."""
    from .agents import LlmAgent, ScanAgent
    scan = ScanAgent(perception, limits)
    return LlmAgent(limits, fallback=scan) if kind == "llm" else scan
