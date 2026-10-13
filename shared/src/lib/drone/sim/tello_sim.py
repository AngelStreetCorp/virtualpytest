"""Wire-compatible Tello simulator: SDK text over UDP, state datagrams, H.264 video of a rendered view.

One TelloSim is one drone. It answers the SDK on bind_ip:cmd_port (replies go to the sender's source port,
like the real drone), sends the state datagram to client_ip:state_port every 100 ms, and after `streamon`
pipes rendered frames to ffmpeg which streams H.264 to client_ip:video_port. Several sims share a
SimRegistry so they draw each other.
"""

import math
import queue
import random
import socket
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

from .render import render_view
from .world import Pose, Room

_RADIUS = 12.0        # drone radius used for collisions (cm)
_WALL_MARGIN = 10.0
_MAX_Z = 300.0
_ROT_DPS = 90.0
_TAKEOFF_Z = 80.0


def sim_ip(drone_id: int) -> str:
    """Loopback address of simulated drone i (1-based): 127.0.0.11, 127.0.0.12, ..."""
    return f"127.0.0.{10 + drone_id}"


class SimRegistry:
    """Shared drone_id -> Pose map so simulators render each other."""

    def __init__(self):
        self._lock = threading.Lock()
        self._poses: Dict[int, Pose] = {}

    def set(self, drone_id: int, pose: Pose) -> None:
        with self._lock:
            self._poses[drone_id] = pose.copy()

    def get(self, drone_id: int) -> Optional[Pose]:
        with self._lock:
            p = self._poses.get(drone_id)
            return p.copy() if p else None

    def others(self, drone_id: int) -> List[Tuple[int, Pose]]:
        with self._lock:
            return [(i, p.copy()) for i, p in self._poses.items() if i != drone_id]


class TelloSim:
    def __init__(self, room: Room, drone_id: int, bind_ip: str, cmd_port: int = 8889, client_ip: str = "127.0.0.1",
                 state_port: int = 8890, video_port: int = 11111, fps: int = 15, drift: float = 0.03,
                 seed: Optional[int] = None, registry: Optional[SimRegistry] = None,
                 start_pose: Optional[Pose] = None, idle_timeout_s: float = 15.0, time_scale: float = 1.0):
        from .world import START_SPOTS
        self.room = room
        self.drone_id = drone_id
        self.bind_ip = bind_ip
        self.cmd_port = cmd_port
        self.client_ip = client_ip
        self.state_port = state_port
        self.video_port = video_port
        self.fps = fps
        self.drift = drift
        self.idle_timeout_s = idle_timeout_s
        self.time_scale = time_scale  # >1 runs motion faster than real time (tests)
        self.registry = registry if registry is not None else SimRegistry()
        self.pose = (start_pose or START_SPOTS.get(drone_id) or Pose(100, 100, 0, 0)).copy()
        self.battery = 100.0
        self.speed = 50.0
        self.flying = False
        self.streaming = False
        self.flight_time = 0.0
        self._rng = random.Random(seed)
        self._lock = threading.RLock()
        self._rc = (0, 0, 0, 0)
        self._busy = False
        self._abort = threading.Event()
        self._stop = threading.Event()
        self._cmds: "queue.Queue[Tuple[str, tuple]]" = queue.Queue()
        self._last_cmd = time.time()
        self._t0 = time.time()
        self._sock: Optional[socket.socket] = None
        self._state_sock: Optional[socket.socket] = None
        self._ffmpeg: Optional[subprocess.Popen] = None
        self._threads: List[threading.Thread] = []
        self._video_stop = threading.Event()
        self._video_thread: Optional[threading.Thread] = None

    # -- lifecycle -------------------------------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.bind_ip, self.cmd_port))
        self._sock.settimeout(0.3)
        self._state_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.registry.set(self.drone_id, self.pose)
        for fn, nm in ((self._recv_loop, "recv"), (self._exec_loop, "exec"), (self._tick_loop, "tick")):
            t = threading.Thread(target=fn, daemon=True, name=f"sim{self.drone_id}-{nm}")
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self._abort.set()
        self._stop_video()
        for t in self._threads:
            t.join(timeout=3)
        self._threads = []
        for s in (self._sock, self._state_sock):
            if s:
                s.close()
        self._sock = self._state_sock = None

    # -- helpers ---------------------------------------------------------------------------------
    def _sleep(self, s: float) -> None:
        time.sleep(s / self.time_scale)

    def _blocked(self, x: float, y: float, z: float) -> bool:
        if not (_WALL_MARGIN <= x <= self.room.width - _WALL_MARGIN and _WALL_MARGIN <= y <= self.room.depth - _WALL_MARGIN):
            return True
        if z >= self.room.height - 15:
            return True
        for o in self.room.objects:
            if z > o.z0 + o.h + 8 or z < o.z0 - 8:
                continue
            x0, x1, y0, y1 = o.bounds
            if x0 - _RADIUS < x < x1 + _RADIUS and y0 - _RADIUS < y < y1 + _RADIUS:
                return True
        return False

    def _publish(self) -> None:
        self.registry.set(self.drone_id, self.pose)

    def _reply(self, addr, text: str) -> None:
        try:
            self._sock.sendto(text.encode(), addr)
        except (OSError, AttributeError):
            pass

    # -- network loops ---------------------------------------------------------------------------
    def _recv_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                return
            text = data.decode(errors="replace").strip()
            if not text:
                continue
            self._last_cmd = time.time()
            low = text.lower()
            if low == "emergency":
                self._abort.set()
                with self._lock:
                    self.flying = False
                    self.pose.z = 0.0
                    self._rc = (0, 0, 0, 0)
                self._publish()
                self._reply(addr, "ok")
            elif low == "stop":
                self._abort.set()
                self._rc = (0, 0, 0, 0)
                self._reply(addr, "ok")
            elif low.startswith("rc "):  # no reply
                try:
                    a, b, c, d = (max(-100, min(100, int(v))) for v in low.split()[1:5])
                    self._rc = (a, b, c, d)
                except ValueError:
                    pass
            else:
                self._cmds.put((text, addr))

    def _exec_loop(self) -> None:
        while not self._stop.is_set():
            try:
                text, addr = self._cmds.get(timeout=0.2)
            except queue.Empty:
                continue
            self._abort.clear()
            self._busy = True
            try:
                reply = self._handle(text)
            except Exception as e:  # never kill the executor
                reply = f"error {e}"
            self._busy = False
            self._last_cmd = time.time()
            self._reply(addr, reply)

    def _tick_loop(self) -> None:
        last = last_state = time.time()
        while not self._stop.is_set():
            time.sleep(0.05)
            now = time.time()
            dt = now - last
            last = now
            with self._lock:
                if self.flying:
                    self.flight_time += dt
                    self.battery = max(0.0, self.battery - dt / 8.0)
                    if now - self._last_cmd > self.idle_timeout_s and self._cmds.empty() and not self._busy:
                        self.flying = False  # real Tello lands after 15 s of silence
                        self.pose.z = 0.0
                        self._rc = (0, 0, 0, 0)
                    elif any(self._rc):
                        self._apply_rc(dt)
                else:
                    self.battery = max(0.0, self.battery - dt / 120.0)
            self._publish()
            if now - last_state >= 0.1:
                last_state = now
                self._send_state()

    def _apply_rc(self, dt: float) -> None:
        a, b, c, d = self._rc
        yaw = math.radians(self.pose.yaw_deg)
        vx = b * math.sin(yaw) + a * math.cos(yaw)
        vy = b * math.cos(yaw) - a * math.sin(yaw)
        nx, ny, nz = self.pose.x + vx * dt, self.pose.y + vy * dt, self.pose.z + c * dt
        if not self._blocked(nx, ny, nz):
            self.pose.x, self.pose.y, self.pose.z = nx, ny, max(10.0, min(_MAX_Z, nz))
        self.pose.yaw_deg = (self.pose.yaw_deg + 1.5 * d * dt) % 360

    # -- state -----------------------------------------------------------------------------------
    def state_text(self) -> str:
        yaw = int(round(self.pose.yaw_deg)) % 360
        if yaw > 180:
            yaw -= 360
        h = int(round(self.pose.z))
        temph = int(45 + min(35.0, (time.time() - self._t0) * 0.05))
        return ("pitch:0;roll:0;yaw:%d;vgx:0;vgy:0;vgz:0;templ:%d;temph:%d;tof:%d;h:%d;bat:%d;"
                "baro:%.2f;time:%d;agx:0.00;agy:0.00;agz:-1000.00;\r\n"
                % (yaw, temph - 3, temph, h, h, int(self.battery), 20.0 + self.pose.z / 100.0, int(self.flight_time)))

    def _send_state(self) -> None:
        try:
            self._state_sock.sendto(self.state_text().encode(), (self.client_ip, self.state_port))
        except (OSError, AttributeError):
            pass

    # -- SDK commands ----------------------------------------------------------------------------
    def _handle(self, text: str) -> str:
        parts = text.split()
        cmd = parts[0].lower()
        args = parts[1:]
        if cmd == "command":
            return "ok"
        if cmd == "battery?":
            return str(int(self.battery))
        if cmd == "height?":
            return f"{int(self.pose.z)}dm"
        if cmd == "speed?":
            return f"{self.speed:.1f}"
        if cmd == "time?":
            return f"{int(self.flight_time)}s"
        if cmd == "temp?":
            t = int(45 + min(35.0, (time.time() - self._t0) * 0.05))
            return f"{t - 2}~{t}C"
        if cmd == "wifi?":
            return "90"
        if cmd == "sdk?":
            return "20"
        if cmd == "streamon":
            self._start_video()
            return "ok"
        if cmd == "streamoff":
            self._stop_video()
            return "ok"
        if cmd == "speed":
            try:
                v = int(args[0])
            except (IndexError, ValueError):
                return "error"
            if not 10 <= v <= 100:
                return "error"
            self.speed = float(v)
            return "ok"
        if cmd == "takeoff":
            if self.flying:
                return "error"
            if self.battery < 10:
                return "error Not enough battery"
            return self._takeoff()
        if cmd == "land":
            if not self.flying:
                return "error"
            return self._land()
        if cmd in ("up", "down", "left", "right", "forward", "back", "cw", "ccw"):
            try:
                n = int(args[0])
            except (IndexError, ValueError):
                return "error"
            if cmd in ("cw", "ccw"):
                if not 1 <= n <= 360:
                    return "error"
            elif not 20 <= n <= 500:
                return "error"
            if not self.flying:
                return "error Motor stop"
            if cmd in ("cw", "ccw"):
                return self._rotate(n if cmd == "cw" else -n)
            return self._move(cmd, n)
        return "error"

    def _noise(self, scale: float = 1.0) -> float:
        return self._rng.gauss(0.0, self.drift * scale)

    def _takeoff(self) -> str:
        steps = 20
        for i in range(steps):
            if self._abort.is_set():
                return "ok"
            with self._lock:
                self.pose.z = _TAKEOFF_Z * (i + 1) / steps
                self.flying = True
            self._sleep(2.5 / steps)
        self._publish()
        return "ok"

    def _land(self) -> str:
        z0 = self.pose.z
        steps = max(5, int(z0 / 8))
        for i in range(steps):
            if self._abort.is_set():
                break
            with self._lock:
                self.pose.z = z0 * (1 - (i + 1) / steps)
            self._sleep(1.5 / steps)
        with self._lock:
            self.pose.z = 0.0
            self.flying = False
        self._publish()
        return "ok"

    def _rotate(self, deg: float) -> str:
        total = deg * (1 + self._noise(0.5))
        steps = max(1, int(abs(total) / (_ROT_DPS * 0.05)))
        for _ in range(steps):
            if self._abort.is_set():
                break
            with self._lock:
                self.pose.yaw_deg = (self.pose.yaw_deg + total / steps) % 360
            self._sleep(0.05)
        self._publish()
        return "ok"

    def _move(self, cmd: str, dist: float) -> str:
        yaw = math.radians(self.pose.yaw_deg)
        fwd = (math.sin(yaw), math.cos(yaw))
        right = (math.cos(yaw), -math.sin(yaw))
        vec = {"forward": (fwd[0], fwd[1], 0), "back": (-fwd[0], -fwd[1], 0),
               "right": (right[0], right[1], 0), "left": (-right[0], -right[1], 0),
               "up": (0, 0, 1), "down": (0, 0, -1)}[cmd]
        total = dist * (1 + self._noise())
        lat = dist * self._noise(0.3) if cmd in ("forward", "back", "left", "right") else 0.0
        if cmd in ("forward", "back"):
            vec = (vec[0] + right[0] * lat / max(total, 1), vec[1] + right[1] * lat / max(total, 1), 0)
        elif cmd in ("left", "right"):
            vec = (vec[0] + fwd[0] * lat / max(total, 1), vec[1] + fwd[1] * lat / max(total, 1), 0)
        step = self.speed * 0.05
        moved = 0.0
        while moved < total and not self._abort.is_set():
            s = min(step, total - moved)
            nx, ny, nz = (self.pose.x + vec[0] * s, self.pose.y + vec[1] * s, self.pose.z + vec[2] * s)
            if nz < 10 or nz > _MAX_Z or self._blocked(nx, ny, nz):
                break  # stop at the obstacle, still 'ok' (the real drone just drifts/stalls)
            with self._lock:
                self.pose.x, self.pose.y, self.pose.z = nx, ny, nz
            moved += s
            self._sleep(0.05)
        self._publish()
        return "ok"

    # -- video -----------------------------------------------------------------------------------
    def _start_video(self) -> None:
        if self.streaming:
            return
        cmd = ["ffmpeg", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "960x720",
               "-r", str(self.fps), "-i", "-", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
               "-g", str(self.fps), "-pix_fmt", "yuv420p", "-x264-params", "repeat-headers=1",
               "-f", "h264", f"udp://{self.client_ip}:{self.video_port}?pkt_size=1316"]
        self._ffmpeg = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.streaming = True
        self._video_stop.clear()
        self._video_thread = threading.Thread(target=self._video_loop, daemon=True, name=f"sim{self.drone_id}-video")
        self._video_thread.start()

    def _video_loop(self) -> None:
        period = 1.0 / self.fps
        nxt = time.time()
        proc = self._ffmpeg
        while not self._video_stop.is_set() and not self._stop.is_set():
            frame = render_view(self.room, self.pose.copy(), self.registry.others(self.drone_id))
            try:
                proc.stdin.write(frame.tobytes())
                proc.stdin.flush()
            except (OSError, ValueError):
                break
            nxt += period
            delay = nxt - time.time()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = time.time()  # render slower than fps: do not accumulate debt

    def _stop_video(self) -> None:
        self.streaming = False
        self._video_stop.set()
        if self._video_thread and self._video_thread is not threading.current_thread():
            self._video_thread.join(timeout=3)
        self._video_thread = None
        p, self._ffmpeg = self._ffmpeg, None
        if p:
            try:
                p.stdin.close()
            except OSError:
                pass
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
