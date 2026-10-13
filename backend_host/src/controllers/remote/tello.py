"""
Tello (Ryze/DJI) Remote Controller

Drives one Tello over its plain-text UDP SDK, as a VirtualPyTest remote controller
(device model `tello`, TASK-32). The drone is a camera that flies: the video side is
the ordinary RTSP/stream AV controller (DEVICE{i}_VIDEO=udp://0.0.0.0:<video_port>), this
controller is the command side.

Every command that moves the drone goes through `SafetyGuard` (shared/src/lib/drone/safety.py)
before it is sent: height ceiling, geofence, battery floor, temperature, separation from the
other drone. A guard refusal returns `success: False` and sends nothing. The guard may also
clip a move; the clipped command is what is sent and what dead reckoning records.

Link behaviour:
  - the UDP link (command socket + state listener) is opened on the first command, not at
    construction. vpt-host builds this controller at startup and a script subprocess builds its
    own; only the process that actually flies binds the state port.
  - a flying Tello lands by itself after 15 s without a command, so a keepalive runs while
    airborne (TelloClient.start_keepalive).
  - a command that times out is retried once; if it still fails the drone is landed.
  - battery at or below the land floor while airborne lands the drone.

execute_command surface (route /host/remote/executeCommand and action executor):
  takeoff | land | emergency
  move      {direction: forward|back|left|right|up|down, cm: 20..500}
  rotate    {direction: cw|ccw, deg: 1..360}
  sdk       {cmd: '<raw SDK text>'}      still guarded
  configure {room_w, room_d, max_h, x, y, yaw, ...}   geofence + start spot for this run
  get_telemetry
  press_key {key: UP|DOWN|LEFT|RIGHT|OK|BACK}
`emergency` cuts the motors (the drone drops); it is never sent automatically.
"""

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..base_controller import RemoteControllerInterface
from shared.src.lib.drone.telemetry_log import TelemetryLogger

MOVE_DIRECTIONS = ('forward', 'back', 'left', 'right', 'up', 'down')
ROTATE_DIRECTIONS = ('cw', 'ccw')

# press_key -> (command, params). UP/DOWN/LEFT/RIGHT fly a step, OK/BACK take off and land.
KEY_MAP: Dict[str, Dict[str, Any]] = {
    'UP': {'command': 'move', 'params': {'direction': 'forward', 'cm': 50}},
    'DOWN': {'command': 'move', 'params': {'direction': 'back', 'cm': 50}},
    'LEFT': {'command': 'rotate', 'params': {'direction': 'ccw', 'deg': 30}},
    'RIGHT': {'command': 'rotate', 'params': {'direction': 'cw', 'deg': 30}},
    'OK': {'command': 'takeoff', 'params': {}},
    'BACK': {'command': 'land', 'params': {}},
}

# SDK verbs that put the drone in the air or move it; everything else is a read or a setting.
_FLIGHT_VERBS = ('takeoff', 'land', 'emergency', 'stop', 'rc') + MOVE_DIRECTIONS + ROTATE_DIRECTIONS


class TelloRemoteController(RemoteControllerInterface):
    """Remote controller for a Tello, wrapping TelloClient and SafetyGuard."""

    @staticmethod
    def get_remote_config() -> Dict[str, Any]:
        """Frontend layout config (title and buttons) for the Tello panel."""
        return {
            'remote_info': {'name': 'Tello Remote', 'type': 'tello'},
            'buttons': [
                {'label': 'Take off', 'command': 'takeoff', 'params': {}},
                {'label': 'Land', 'command': 'land', 'params': {}},
                {'label': 'Forward', 'command': 'move', 'params': {'direction': 'forward', 'cm': 50}},
                {'label': 'Back', 'command': 'move', 'params': {'direction': 'back', 'cm': 50}},
                {'label': 'Left', 'command': 'move', 'params': {'direction': 'left', 'cm': 50}},
                {'label': 'Right', 'command': 'move', 'params': {'direction': 'right', 'cm': 50}},
                {'label': 'Up', 'command': 'move', 'params': {'direction': 'up', 'cm': 30}},
                {'label': 'Down', 'command': 'move', 'params': {'direction': 'down', 'cm': 30}},
                {'label': 'Turn left', 'command': 'rotate', 'params': {'direction': 'ccw', 'deg': 30}},
                {'label': 'Turn right', 'command': 'rotate', 'params': {'direction': 'cw', 'deg': 30}},
            ],
        }

    def __init__(self,
                 tello_ip: str,
                 cmd_port: int = 8889,
                 state_port: int = 8890,
                 video_port: int = 11111,
                 local_ip: str = '0.0.0.0',
                 name: str = 'tello',
                 room_w: float = 600,
                 room_d: float = 500,
                 max_h: float = 150,
                 start_x: float = 100,
                 start_y: float = 100,
                 start_yaw: float = 0,
                 keepalive_s: float = 5.0,
                 telemetry_log_interval_s: float = 0.2,
                 mission_pads: Optional[Dict[int, Tuple[float, float, float]]] = None,
                 **kwargs):
        super().__init__(f"Tello {name}", "tello")
        self.tello_ip = tello_ip
        self.cmd_port = int(cmd_port)
        self.state_port = int(state_port)
        self.video_port = int(video_port)
        self.local_ip = local_ip
        self.name = name
        self.keepalive_s = keepalive_s
        self.client = None
        self.guard = None
        self.limits = None
        self.airborne = False
        self.last_error: Optional[str] = None
        self.guard_blocks = 0
        self.commands_sent = 0
        # Per-flight telemetry logger. Started on takeoff, stopped on land.
        # Default 200 ms (5 Hz) — half the Tello's 10 Hz state rate, well within
        # the bandwidth the guard and the agent need for after-the-fact replay.
        # Set to 0.1 for full state rate or higher (e.g. 0.5) to log less.
        self._telemetry_log_interval_s = float(telemetry_log_interval_s)
        self._telemetry_logger = None
        self.last_log_path: Optional[str] = None
        # Optional Mission Pad layout (Tello Talent). Empty / None means the
        # pose is always dead-reckoned. The controller can also be reconfigured
        # at runtime via set_mission_pads().
        self._mission_pad_config: Optional[Any] = None
        if mission_pads:
            from shared.src.lib.drone.mission_pad import MissionPadConfig
            self._mission_pad_config = MissionPadConfig(pads=dict(mission_pads))
        self._peers: Callable[[], List[Any]] = lambda: []
        self._lock = threading.RLock()
        self._configure(room_w=room_w, room_d=room_d, max_h=max_h,
                        x=start_x, y=start_y, yaw=start_yaw)

    # ---------- configuration ---------------------------------------------

    def _configure(self, room_w=None, room_d=None, max_h=None, x=None, y=None, yaw=None,
                   tello_ip=None, cmd_port=None, state_port=None, video_port=None, **limits) -> None:
        """(Re)build the guard: geofence, ceiling, start pose. The drone must be landed.

        Also accepts a runtime endpoint swap (``tello_ip``, ``cmd_port``, ``state_port``,
        ``video_port``) used by the pairing flow: after the host joins a new Tello's AP
        the controller is told where the new Tello is. Any in-flight link is released
        so the next command re-binds on the new IP/ports.
        """
        from shared.src.lib.drone.safety import SafetyGuard, SafetyLimits
        from shared.src.lib.drone.sim.world import Pose
        old = self.limits
        values: Dict[str, Any] = {}
        if old is not None:
            values.update({k: getattr(old, k) for k in old.__dataclass_fields__})
        if room_w is not None:
            values['room_w'] = float(room_w)
        if room_d is not None:
            values['room_d'] = float(room_d)
        if max_h is not None:
            values['max_h'] = float(max_h)
        for key, value in limits.items():
            if key in SafetyLimits.__dataclass_fields__ and value is not None:
                values[key] = value
        self.limits = SafetyLimits(**values)
        start = Pose(float(x if x is not None else 100), float(y if y is not None else 100), 0.0,
                     float(yaw if yaw is not None else 0))
        self.guard = SafetyGuard(self.limits, start, lambda: list(self._peers()), telemetry=self._state)

        # Runtime endpoint swap. Any change releases the current UDP link so the next
        # command re-binds on the new IP/ports (the state port is one bind per host).
        endpoint_changed = False
        if tello_ip is not None and tello_ip != self.tello_ip:
            self.tello_ip = str(tello_ip)
            endpoint_changed = True
        if cmd_port is not None and int(cmd_port) != self.cmd_port:
            self.cmd_port = int(cmd_port)
            endpoint_changed = True
        if state_port is not None and int(state_port) != self.state_port:
            self.state_port = int(state_port)
            endpoint_changed = True
        if video_port is not None and int(video_port) != self.video_port:
            self.video_port = int(video_port)
            endpoint_changed = True
        if endpoint_changed and self.client is not None:
            self._release_link()

    def set_peers(self, peers: Callable[[], List[Any]]) -> None:
        """Callable returning the other drones' dead-reckoned poses (separation guard)."""
        self._peers = peers  # the guard reads it through a late-bound lambda

    def pose(self):
        return self.guard.pose if self.guard is not None else None

    # ---------- connection ------------------------------------------------

    def connect(self) -> bool:
        """Mark the controller usable. The UDP link itself opens on the first command."""
        self.is_connected = True
        return True

    def disconnect(self) -> bool:
        """Land if airborne, then close the UDP link."""
        with self._lock:
            if self.client is not None and self.airborne:
                self._land_quietly()
            if self.client is not None:
                try:
                    self.client.stop_keepalive()
                    self.client.close()
                except Exception as e:
                    print(f"Remote[TELLO]: close error: {e}")
                self.client = None
        self.is_connected = False
        return True

    def _ensure_client(self) -> bool:
        if self.client is not None:
            return True
        try:
            from shared.src.lib.drone.tello import TelloClient
            client = TelloClient(self.tello_ip, cmd_port=self.cmd_port, state_port=self.state_port,
                                 local_ip=self.local_ip, name=self.name)
            client.connect()
            # Video goes to the host port the vpt-stream ffmpeg listens on (DEVICE{i}_VIDEO).
            client.send_ok('streamon')
            # First state datagram (~100 ms): the battery and temperature gates need it.
            deadline = time.time() + 1.5
            while not client.state() and time.time() < deadline:
                time.sleep(0.05)
            self.client = client
            self.is_connected = True
            self.last_error = None
            print(f"Remote[TELLO]: {self.name} linked at {self.tello_ip}:{self.cmd_port} "
                  f"(state {self.state_port}, video {self.video_port})")
            return True
        except Exception as e:
            self.last_error = f"link to {self.tello_ip}:{self.cmd_port} failed: {e}"
            print(f"Remote[TELLO]: {self.last_error}")
            self.client = None
            return False

    # ---------- command dispatch ------------------------------------------

    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Dispatcher for /host/remote/executeCommand and the action executor."""
        params = params or {}
        if not command.startswith('get_'):
            print(f"Remote[TELLO]: Executing command '{command}' with params: {params}")
        try:
            with self._lock:
                if command == 'configure':
                    if self.airborne:
                        return {'success': False, 'error': 'cannot reconfigure while airborne'}
                    self._configure(**params)
                    return {'success': True}
                if command == 'get_telemetry':
                    return self._telemetry_result()
                if command == 'press_key':
                    return self._press_key(params.get('key'))
                sdk = self._to_sdk(command, params)
                if isinstance(sdk, dict):
                    return sdk
                return self._send_guarded(sdk, emergency=sdk.split()[0].lower() == 'emergency')
        except Exception as e:
            # Anything unexpected: never leave the drone flying on an exception.
            self.last_error = str(e)
            print(f"Remote[TELLO]: ERROR in '{command}': {e}")
            self._land_quietly()
            return {'success': False, 'error': str(e)}

    def press_key(self, key: str) -> bool:
        return bool(self.execute_command('press_key', {'key': key}).get('success'))

    def _press_key(self, key: Optional[str]) -> Dict[str, Any]:
        mapped = KEY_MAP.get((key or '').upper())
        if mapped is None:
            return {'success': False, 'error': f'unsupported key: {key}'}
        sdk = self._to_sdk(mapped['command'], mapped['params'])
        if isinstance(sdk, dict):
            return sdk
        return self._send_guarded(sdk)

    def _to_sdk(self, command: str, params: Dict[str, Any]):
        """SDK text for a high-level command, or an error result dict."""
        if command in ('takeoff', 'land', 'emergency'):
            return command
        if command == 'move':
            direction = str(params.get('direction', '')).lower()
            try:
                cm = int(params.get('cm'))
            except (TypeError, ValueError):
                return {'success': False, 'error': 'move needs integer cm'}
            if direction not in MOVE_DIRECTIONS:
                return {'success': False, 'error': f'unknown direction: {direction}'}
            if not 20 <= cm <= 500:
                return {'success': False, 'error': f'cm {cm} out of range 20..500'}
            return f'{direction} {cm}'
        if command == 'rotate':
            direction = str(params.get('direction', '')).lower()
            try:
                deg = int(params.get('deg'))
            except (TypeError, ValueError):
                return {'success': False, 'error': 'rotate needs integer deg'}
            if direction not in ROTATE_DIRECTIONS:
                return {'success': False, 'error': f'unknown direction: {direction}'}
            if not 1 <= deg <= 360:
                return {'success': False, 'error': f'deg {deg} out of range 1..360'}
            return f'{direction} {deg}'
        if command == 'sdk':
            cmd = str(params.get('cmd', '')).strip()
            if not cmd:
                return {'success': False, 'error': 'sdk needs cmd'}
            return cmd
        print(f"Remote[TELLO]: Unknown command: {command}")
        return {'success': False, 'error': f'unknown command: {command}'}

    # ---------- guarded send ----------------------------------------------

    def _send_guarded(self, cmd: str, emergency: bool = False) -> Dict[str, Any]:
        verb = cmd.split()[0].lower() if cmd.split() else ''
        if not self._ensure_client():
            return {'success': False, 'error': self.last_error or 'drone not reachable'}

        if emergency:
            # Operator kill: motors off, no guard, no retry.
            reply = self._raw(cmd, 5.0)
            self.airborne = False
            log_path = self._stop_telemetry_log()
            out: Dict[str, Any] = {'success': reply == 'ok', 'reply': reply}
            if log_path is not None:
                out['log_path'] = log_path
            self._release_link()
            return out

        # 'land' is always allowed; the guard must never be able to keep a drone in the air.
        if verb != 'land':
            allowed, to_send, reason = self.guard.check(cmd)
            if not allowed and to_send == 'land':
                # The guard wants the drone down now (battery at the land floor).
                self.guard_blocks += 1
                self._land_quietly()
                return {'success': False, 'blocked': True, 'landed': True, 'error': f'landed: {reason}',
                        'reason': reason}
            if not allowed or not to_send:
                self.guard_blocks += 1
                print(f"Remote[TELLO]: guard refused '{cmd}': {reason}")
                return {'success': False, 'blocked': True, 'error': f'blocked: {reason}', 'reason': reason}
            cmd_to_send = to_send
        else:
            cmd_to_send = cmd

        timeout = self._timeout_for(verb)
        reply = None
        for attempt in (1, 2):
            reply = self._raw(cmd_to_send, timeout)
            if reply is not None:
                break
            print(f"Remote[TELLO]: '{cmd_to_send}' timed out (attempt {attempt}/2)")
        self.commands_sent += 1
        if reply is None:
            self.last_error = f"'{cmd_to_send}' got no reply"
            if verb != 'land':
                self._land_quietly()
            return {'success': False, 'error': self.last_error, 'landed': verb != 'land'}

        ok = reply.lower() == 'ok' if verb in _FLIGHT_VERBS else not reply.lower().startswith('error')
        out: Dict[str, Any] = {'success': ok, 'reply': reply, 'sent': cmd_to_send}
        if cmd_to_send != cmd:
            out['clipped_from'] = cmd
        if not ok:
            self.last_error = f"'{cmd_to_send}' -> {reply}"
            out['error'] = reply
            return out

        self.guard.apply(cmd_to_send)
        if verb == 'takeoff':
            self.airborne = True
            self.client.start_keepalive(self.keepalive_s)
            self._start_telemetry_log()
        out['telemetry'] = self._state()
        out['output_data'] = {'reply': reply, 'sent': cmd_to_send, 'telemetry': out['telemetry']}
        out['pose'] = self._pose_dict()
        self._battery_floor(out)
        if verb == 'land':
            self.airborne = False
            log_path = self._stop_telemetry_log()
            if log_path is not None:
                out['log_path'] = str(log_path)
            self._release_link()
        return out

    def _release_link(self) -> None:
        """Close the UDP link of a landed drone. The state port is a single bind on the host, so the
        process that flies next (vpt-host's remote panel, or a script) can only open it once this one
        lets go; the next command re-links (and re-sends `command` + `streamon`)."""
        if self.client is None:
            return
        try:
            self.client.stop_keepalive()
            self.client.close()
        except Exception as e:
            print(f"Remote[TELLO]: close error: {e}")
        self.client = None

    # ---------- per-flight telemetry logging --------------------------------

    def _sample_telemetry(self) -> Optional[Dict[str, Any]]:
        """One sample: state datagram + (snapped or dead-reckoned) pose. Runs on the logger thread.

        If a Mission Pad is visible (Tello Talent only) and a pad is configured for
        this room, the pose is snapped to the known pad position + the reported
        offset and ``pose_source`` becomes ``"mission_pad"``. Otherwise the pose is
        the SafetyGuard's dead-reckoned value and ``pose_source`` is
        ``"dead_reckoned"``.
        """
        state = self._state() or {}
        pose = self.pose()
        pose_source = "dead_reckoned"
        pad_id = None
        if self._mission_pad_config is not None and pose is not None:
            from shared.src.lib.drone.mission_pad import is_mission_pad_visible, snap_pose
            if is_mission_pad_visible(state):
                snapped = snap_pose(state, pose, self._mission_pad_config)
                if snapped is not None:
                    pose = snapped
                    pose_source = "mission_pad"
                    try:
                        pad_id = int(state.get("mid"))
                    except (TypeError, ValueError):
                        pad_id = None
        return {
            "phase": "airborne" if self.airborne else "grounded",
            "bat": state.get("bat"),
            "temph": state.get("temph"),
            "h": state.get("h"),
            "tof": state.get("tof"),
            "baro": state.get("baro"),
            "time": state.get("time"),
            "pose_x": pose.x if pose is not None else None,
            "pose_y": pose.y if pose is not None else None,
            "pose_z": pose.z if pose is not None else None,
            "yaw": pose.yaw_deg if pose is not None else None,
            "pose_source": pose_source,
            "pad_id": pad_id,
            "vgx": state.get("vgx"),
            "vgy": state.get("vgy"),
            "vgz": state.get("vgz"),
            "agx": state.get("agx"),
            "agy": state.get("agy"),
            "agz": state.get("agz"),
            "guard_blocks": self.guard_blocks,
            "commands_sent": self.commands_sent,
        }

    def _start_telemetry_log(self) -> None:
        """Open a per-flight log file. Idempotent: a second takeoff is a no-op while one is in flight."""
        if self._telemetry_logger is not None and self._telemetry_logger.is_running:
            return
        self._telemetry_logger = TelemetryLogger(
            host=self.name, device_id=self.name,
            interval_s=self._telemetry_log_interval_s,
        )
        try:
            path = self._telemetry_logger.start(self._sample_telemetry)
            self.last_log_path = str(path)
        except Exception as e:
            print(f"Remote[TELLO]: could not start telemetry log: {e}")
            self._telemetry_logger = None

    def _stop_telemetry_log(self) -> Optional[str]:
        """Close the per-flight log file. Returns the path (or None if there was no log)."""
        if self._telemetry_logger is None:
            return None
        path = self._telemetry_logger.stop()
        self._telemetry_logger = None
        if path is not None:
            self.last_log_path = str(path)
        return self.last_log_path

    def get_flight_summary(self) -> Optional[Dict[str, Any]]:
        """Read the last per-flight CSV and return a small summary dict for the test report.

        Returns ``None`` if no log has been written. Cheap: scans the file
        once for the row count, the first/last row timestamps, the
        peak altitude, and the per-axis position deltas (a cheap proxy
        for total distance — the safety guard already does a more
        accurate one but it's not exposed here).
        """
        from pathlib import Path
        import csv as _csv
        path = self.last_log_path
        if not path:
            return None
        p = Path(path)
        if not p.exists():
            return None
        rows = 0
        first_t = last_t = ""
        peak_h = None
        first_pose = last_pose = None
        try:
            with p.open("r", newline="") as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    rows += 1
                    if not first_t:
                        first_t = row.get("t_iso", "")
                    last_t = row.get("t_iso", "")
                    h = row.get("h")
                    if h:
                        try:
                            hv = float(h)
                            peak_h = hv if peak_h is None else max(peak_h, hv)
                        except ValueError:
                            pass
                    try:
                        x = float(row.get("pose_x") or 0.0)
                        y = float(row.get("pose_y") or 0.0)
                        z = float(row.get("pose_z") or 0.0)
                    except ValueError:
                        continue
                    if first_pose is None:
                        first_pose = (x, y, z)
                    last_pose = (x, y, z)
        except OSError:
            return None

        distance_cm = 0.0
        if first_pose and last_pose:
            distance_cm = (
                (last_pose[0] - first_pose[0]) ** 2 +
                (last_pose[1] - first_pose[1]) ** 2 +
                (last_pose[2] - first_pose[2]) ** 2
            ) ** 0.5

        # Duration: parse the millisecond delta between first and last t_ms.
        duration_s = None
        # (parsing the millisecond column is faster than re-parsing the
        # ISO; we already have a fixed-width column at the start.)
        try:
            with p.open("r", newline="") as f:
                rd = _csv.DictReader(f)
                first_ms = last_ms = None
                for row in rd:
                    if first_ms is None:
                        first_ms = int(row.get("t_ms") or 0)
                    last_ms = int(row.get("t_ms") or 0)
            if first_ms is not None and last_ms is not None:
                duration_s = max(0, (last_ms - first_ms) / 1000.0)
        except (OSError, ValueError):
            pass

        return {
            "log_path": str(p),
            "rows": rows,
            "first_t": first_t,
            "last_t": last_t,
            "duration_s": duration_s,
            "peak_altitude_cm": peak_h,
            "total_distance_cm": distance_cm,
            "guard_blocks": self.guard_blocks,
            "commands_sent": self.commands_sent,
        }

    def set_mission_pads(self, pads: Optional[Dict[int, Tuple[float, float, float]]]) -> None:
        """Set the room's Mission Pad layout at runtime (Tello Talent only).

        Pass ``None`` or an empty dict to disable snapping; the pose is then
        always dead-reckoned. ``pads`` is ``{pad_id: (x, y, z)}`` in cm, in
        the same coordinate system as the SafetyGuard's room.
        """
        from shared.src.lib.drone.mission_pad import MissionPadConfig
        if pads:
            self._mission_pad_config = MissionPadConfig(pads=dict(pads))
        else:
            self._mission_pad_config = None

    def _raw(self, cmd: str, timeout_s: float) -> Optional[str]:
        """One SDK command; the reply text, or None on timeout/link error."""
        from shared.src.lib.drone.tello import TelloError
        try:
            return self.client.send(cmd, timeout_s=timeout_s)
        except TelloError as e:
            print(f"Remote[TELLO]: {e}")
            return None

    def _timeout_for(self, verb: str) -> float:
        if verb in ('takeoff', 'land'):
            return float(getattr(self.limits, 'takeoff_timeout_s', 20))
        return float(getattr(self.limits, 'cmd_timeout_s', 10))

    def _battery_floor(self, out: Dict[str, Any]) -> None:
        bat = (out.get('telemetry') or {}).get('bat')
        if self.airborne and bat is not None and bat <= self.limits.bat_land:
            print(f"Remote[TELLO]: battery {bat}% at the land floor, landing")
            self._land_quietly()
            out['success'] = False
            out['error'] = f'battery {bat}% at the land floor {self.limits.bat_land}%, landed'
            out['landed'] = True

    def _land_quietly(self) -> None:
        """Best effort land; used on any error. Never raises."""
        try:
            if self.client is None:
                return
            reply = self._raw('land', self._timeout_for('land'))
            if reply is None:
                reply = self._raw('land', self._timeout_for('land'))
            if reply == 'ok':
                self.guard.apply('land')
            self.airborne = False
            self.client.stop_keepalive()
            # Close out the per-flight log so the file is on disk even after a
            # guard-refused or timeout-induced forced landing.
            self._stop_telemetry_log()
        except Exception as e:
            print(f"Remote[TELLO]: land on error failed: {e}")

    # ---------- telemetry -------------------------------------------------

    def _state(self) -> Dict[str, Any]:
        try:
            return dict(self.client.state()) if self.client is not None else {}
        except Exception:
            return {}

    def _pose_dict(self) -> Optional[Dict[str, float]]:
        pose = self.pose()
        if pose is None:
            return None
        return {'x': pose.x, 'y': pose.y, 'z': pose.z, 'yaw': pose.yaw_deg}

    def _telemetry_result(self) -> Dict[str, Any]:
        if not self._ensure_client():
            return {'success': False, 'error': self.last_error or 'drone not reachable'}
        telemetry = self._state()
        data = {'telemetry': telemetry, 'pose': self._pose_dict(), 'airborne': self.airborne,
                'guard_blocks': self.guard_blocks, 'commands_sent': self.commands_sent}
        return {'success': bool(telemetry), 'telemetry': telemetry, 'pose': data['pose'],
                'airborne': self.airborne, 'output_data': data}

    def get_status(self) -> Dict[str, Any]:
        return {'success': True, 'linked': self.client is not None, 'airborne': self.airborne,
                'ip': self.tello_ip, 'state_port': self.state_port, 'video_port': self.video_port,
                'last_error': self.last_error, 'pose': self._pose_dict(),
                'last_log_path': self.last_log_path,
                'telemetry_log_running': (self._telemetry_logger is not None
                                          and self._telemetry_logger.is_running),
                'telemetry_log_interval_s': self._telemetry_log_interval_s}

    def get_available_actions(self) -> Dict[str, Any]:
        """Action objects for the editor, shaped like the other remotes ({'remote': [...]})."""
        def action(aid, label, command, params, description, requires_input=False):
            return {'id': aid, 'label': label, 'command': command, 'action_type': 'remote',
                    'params': params, 'description': description, 'requiresInput': requires_input}
        actions = [
            action('tello_takeoff', 'Take off', 'takeoff', {}, 'Take off and hover (about 80 cm)'),
            action('tello_land', 'Land', 'land', {}, 'Land'),
        ]
        for d in MOVE_DIRECTIONS:
            actions.append(action(f'tello_move_{d}', f'Move {d}', 'move', {'direction': d, 'cm': 50},
                                  f'Fly {d} (20-500 cm), guarded'))
        for d in ROTATE_DIRECTIONS:
            actions.append(action(f'tello_rotate_{d}', f'Rotate {d}', 'rotate', {'direction': d, 'deg': 30},
                                  f'Rotate {d} (1-360 degrees)'))
        actions.append(action('tello_telemetry', 'Telemetry', 'get_telemetry', {}, 'Battery, height, temperature'))
        return {'remote': actions}
