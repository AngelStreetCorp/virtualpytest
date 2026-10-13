"""Tello SDK client: plain-text UDP commands, state listener and keepalive (stdlib only).

Speaks the real Tello SDK 1.3/2.0 protocol: commands go to <ip>:<cmd_port> (8889), the drone replies to
the source port of the command, and state datagrams arrive on a host port (8890 on a real drone). Address
and ports are parameters so two drones can be reached through per-drone addresses (design section B).
"""

import socket
import threading
import time
from typing import Dict, Optional, Union


class TelloError(Exception):
    """Command timeout or socket failure."""


def tello_endpoints(index: int, base_ip: Optional[str] = None) -> dict:
    """Address and ports of drone `index` (1-based) in the netns layout: state 8889+i, video 11110+i."""
    return {
        "ip": base_ip or f"10.200.{index}.2",
        "cmd_port": 8889,
        "state_port": 8889 + index,
        "video_port": 11110 + index,
    }


def parse_state(text: str) -> Dict[str, Union[int, float]]:
    """Parse 'pitch:0;roll:0;yaw:5;...;' into a dict; integral values become int, others float."""
    out: Dict[str, Union[int, float]] = {}
    for part in text.strip().split(";"):
        if ":" not in part:
            continue
        key, _, val = part.partition(":")
        key = key.strip()
        try:
            num = float(val)
        except ValueError:
            continue
        out[key] = int(num) if num == int(num) and "." not in val else num
    return out


class TelloClient:
    def __init__(self, ip: str, cmd_port: int = 8889, state_port: int = 8890, local_ip: str = "0.0.0.0",
                 name: str = "drone", timeout_s: float = 10.0):
        self.ip = ip
        self.cmd_port = cmd_port
        self.state_port = state_port
        self.local_ip = local_ip
        self.name = name
        self.timeout_s = timeout_s
        self.last_command_at = 0.0
        self._cmd_sock: Optional[socket.socket] = None
        self._state_sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._state: Dict[str, Union[int, float]] = {}
        self._state_at = 0.0
        self._stop = threading.Event()
        self._threads = []

    # -- lifecycle -------------------------------------------------------------------------------
    def connect(self) -> None:
        self._stop.clear()
        self._cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._cmd_sock.bind((self.local_ip, 0))
        self._state_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._state_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._state_sock.bind((self.local_ip, self.state_port))
        self._state_sock.settimeout(0.5)
        t = threading.Thread(target=self._state_loop, daemon=True, name=f"tello-state-{self.name}")
        t.start()
        self._threads.append(t)
        # A plain Tello responds with "ok"; a Tello EDU/Tello Talent in binary mode responds
        # with a 0xcc... packet. Both indicate the SDK handoff succeeded, so any non-empty
        # reply that is not the literal "error" is accepted. (TASK-32, plain Tello + EDU
        # observed on vpt-pi4 with TELLO-C5B142 on 2026-10-09.)
        resp = self.send("command")
        if not resp or resp.lower() == "error":
            raise TelloError(f"{self.name}: 'command' was not acknowledged (got {resp!r})")

    def close(self) -> None:
        self._stop.set()
        for s in (self._cmd_sock, self._state_sock):
            try:
                if s:
                    s.close()
            except OSError:
                pass
        self._cmd_sock = self._state_sock = None
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(timeout=2)
        self._threads = []

    # -- commands --------------------------------------------------------------------------------
    def _drain(self) -> None:
        """Drop late replies from earlier commands (replies are untagged)."""
        self._cmd_sock.setblocking(False)
        try:
            while True:
                self._cmd_sock.recvfrom(2048)
        except (BlockingIOError, OSError):
            pass

    def send(self, cmd: str, timeout_s: Optional[float] = None) -> str:
        if self._cmd_sock is None:
            raise TelloError(f"{self.name}: not connected")
        timeout = self.timeout_s if timeout_s is None else timeout_s
        with self._lock:
            try:
                self._drain()
                self._cmd_sock.settimeout(timeout)
                self._cmd_sock.sendto(cmd.encode(), (self.ip, self.cmd_port))
                self.last_command_at = time.time()
                data, _ = self._cmd_sock.recvfrom(2048)
            except socket.timeout:
                raise TelloError(f"{self.name}: timeout after {timeout:.1f}s waiting for reply to '{cmd}'")
            except OSError as e:
                raise TelloError(f"{self.name}: socket error on '{cmd}': {e}")
            self.last_command_at = time.time()
            return data.decode(errors="replace").strip().strip("\x00")

    def send_ok(self, cmd: str, timeout_s: Optional[float] = None) -> bool:
        return self.send(cmd, timeout_s) == "ok"

    def send_no_reply(self, cmd: str) -> None:
        if self._cmd_sock is None:
            raise TelloError(f"{self.name}: not connected")
        with self._lock:
            self._cmd_sock.sendto(cmd.encode(), (self.ip, self.cmd_port))
            self.last_command_at = time.time()

    # -- state -----------------------------------------------------------------------------------
    def _state_loop(self) -> None:
        while not self._stop.is_set():
            sock = self._state_sock
            if sock is None:
                return
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            st = parse_state(data.decode(errors="replace"))
            if st:
                self._state = st
                self._state_at = time.time()

    def state(self) -> dict:
        return dict(self._state)

    def state_age_s(self) -> float:
        return time.time() - self._state_at if self._state_at else float("inf")

    # -- keepalive (Tello lands after 15 s without a command) --------------------------------------
    def start_keepalive(self, period_s: float = 5.0) -> None:
        self.stop_keepalive()
        self._ka_stop = threading.Event()
        stop = self._ka_stop

        def loop():
            while not stop.wait(0.5):
                if time.time() - self.last_command_at >= period_s:
                    try:
                        self.send("battery?", timeout_s=3.0)
                    except TelloError:
                        pass

        self._ka_thread = threading.Thread(target=loop, daemon=True, name=f"tello-ka-{self.name}")
        self._ka_thread.start()

    def stop_keepalive(self) -> None:
        ev = getattr(self, "_ka_stop", None)
        if ev:
            ev.set()
            self._ka_thread.join(timeout=2)
            self._ka_stop = None
