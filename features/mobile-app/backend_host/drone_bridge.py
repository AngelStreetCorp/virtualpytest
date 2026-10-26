"""
features/mobile-app/backend_host/drone_bridge.py — the host side of TASK-167 and TASK-173.

The drone's SDK is three plain-text UDP channels to one address (see
shared/src/lib/drone/tello.py): command (8889, request/response), state (8890,
pushed) and video (11111, pushed RTP). A drone in the lab is reached over a USB
Wi-Fi dongle; a drone 100 m away in a garden is reached through a phone.

This module is the host end of that: it presents the drone as a LOCAL UDP peer
on 127.0.0.1 and forwards the conversation to the drone, whichever way the drone
is currently reachable.

    drone (Wi-Fi)  <--UDP-->  phone  <--Socket.IO-->  drone_bridge  <--UDP-->
                                                                  127.0.0.1
    drone (Wi-Fi)  <--UDP-->  drone_bridge (the host's own radio)  --^

That shape is the whole point: the host keeps speaking plain UDP to the drone,
so `TelloClient`, `SafetyGuard`, the telemetry logger, the command log, the
drone games and `vpt-stream`'s ffmpeg are all untouched. A bridged drone is
configured like any other drone, only the address is 127.0.0.1 and the bridge
holds the radio.

TASK-173 adds the HYBRID: the drone sits on ONE Wi-Fi network at a time, and
which one it is on is the owner's choice (the lab network through the host's
dongle, or the phone's hotspot). The drone cannot be on both. So the bridge
does not switch networks - it watches both paths and uses the one that answers:

    direct  the host's own radio (the USB dongle) reaches the drone on the
            drone's own subnet. This is the lab path, unchanged.
    phone   the drone is on the phone's hotspot and the phone relays it over
            the Socket.IO link the phone agent already holds open.

`DEVICE{i}_TELLO_LINK=auto` prefers the direct path and falls back to the
phone; `direct` and `phone` pin one path. The switch happens on its own:

  * a command that fails on the direct path is retried on the phone path, and
    the drone is then marked as "on the phone's hotspot";
  * a slow probe on the direct path notices the drone coming back to the lab
    network and the bridge returns to it.

Per drone the sidecar owns four local ports, all read from the environment so a
lab drone and a remote drone are configured the same way:

    DEVICE3_TELLO_BRIDGE=phone          this drone can be served through a phone
    DEVICE3_TELLO_BRIDGE_PHONE=device2   the phone_agent slot that carries it
    DEVICE3_TELLO_BRIDGE_DRONE=droneA    the label the owner gave it on the phone
    DEVICE3_TELLO_CMD_PORT=28001        the sidecar ANSWERS SDK commands here
    DEVICE3_TELLO_STATE_PORT=28901      the sidecar INJECTS the drone's state here
    DEVICE3_TELLO_LOCAL_CMD_PORT=8881   the client binds this locally (per drone)
    DEVICE3_VIDEO=udp://127.0.0.1:29001 the sidecar INJECTS the drone's RTP here

and, for the hybrid, the direct path's own numbers:

    DEVICE3_TELLO_LINK=auto              auto | direct | phone
    DEVICE3_TELLO_DIRECT_IP=192.168.10.1 the drone's address on the lab network
    DEVICE3_TELLO_DIRECT_LOCAL_IP=192.168.10.2  the dongle's address (source)
    DEVICE3_TELLO_DIRECT_LOCAL_CMD_PORT=8883     the sidecar's own SDK socket
    DEVICE3_TELLO_DIRECT_CMD_PORT=8889   the drone's SDK port (stock)
    DEVICE3_TELLO_DIRECT_STATE_PORT=8890 where the drone pushes its state
    DEVICE3_TELLO_DIRECT_VIDEO_PORT=11111 where the drone pushes its RTP

Why the phone carries a LABEL rather than an address: the drones on a phone's
hotspot get their addresses from the hotspot's DHCP, so they change from
session to session and cannot be written into the host's configuration. What
does not change is the label the owner gave each drone in the phone app
('droneA'), and that label is what the host's `.env` names.

Two rules from the real drone shape the implementation and are easy to get
wrong:

  * A drone only answers the address:port that sent its first `command` after
    power-on (measured on vpt-pi4, 2026-10-13). So the sidecar replies to the
    SOURCE address the client used, never to a fixed port, and the phone keeps
    ONE command socket for every drone it carries (see the task doc).
  * The drone pushes state and video to FIXED ports (8890 / 11111) of whatever
    client it is talking to, so several drones on one phone all push to the
    same two ports and are told apart by source address.
"""
import os
import socket
import threading
import time
from typing import Any, Dict, List, Optional

from ..lib import protocol

_LOG = '[@mobile-app:drone_bridge]'

# How often the bridge checks whether the drone came back to the lab network.
# Only while the drone is suspect: the probe wakes the drone, and the drone is
# only worth waking when it is somewhere the phone cannot see.
DIRECT_PROBE_INTERVAL_S = 15.0
# How long a probe waits for the drone's answer. The drone is usually asleep,
# and a sleeping drone answers nothing.
DIRECT_PROBE_TIMEOUT_S = 1.5
# How long a command waits for the drone on the direct path before the bridge
# gives up and carries it on the phone path instead. The direct path is the
# lab's own radio: the drone answers in milliseconds, so a second and a half is
# already generous - and it is what keeps the joystick from stuttering when
# the drone has moved to the phone's hotspot.
DIRECT_SEND_TIMEOUT_S = 1.5
# How long a direct answer keeps the direct path marked alive in the status.
DIRECT_ALIVE_TTL_S = 45.0


class DroneBridgeError(Exception):
    """The phone could not carry out a drone command."""


class _DroneLink:
    """One bridged drone: its ports, the phone that carries it and its label there.

    `ip` is the address the drone answers on the phone's hotspot. The host uses
    it only for the status display: the command path goes through the phone,
    never straight to the drone.
    """

    def __init__(self, device_id: str, cmd_port: int, state_port: int,
                 video_port: int, local_cmd_port: int,
                 phone_slot: str, drone_label: str,
                 link_mode: str = 'phone',
                 direct_ip: Optional[str] = None,
                 direct_local_ip: str = '0.0.0.0',
                 direct_local_cmd_port: int = 8883,
                 direct_cmd_port: int = 8889,
                 direct_state_port: int = 8890,
                 direct_video_port: int = 11111):
        self.device_id = device_id
        self.cmd_port = int(cmd_port)
        self.state_port = int(state_port)
        self.video_port = int(video_port)
        self.local_cmd_port = int(local_cmd_port)
        self.phone_slot = phone_slot
        self.drone_label = drone_label
        # 'auto' | 'direct' | 'phone'
        self.link_mode = (link_mode or 'phone').lower()
        # The direct path (the host's own radio). Empty direct_ip = no direct
        # path at all, which is the plain bridged drone of TASK-167.
        self.direct_ip = direct_ip
        self.direct_local_ip = direct_local_ip
        self.direct_local_cmd_port = int(direct_local_cmd_port)
        self.direct_cmd_port = int(direct_cmd_port)
        self.direct_state_port = int(direct_state_port)
        self.direct_video_port = int(direct_video_port)
        self.ip: Optional[str] = None
        self.last_state_at: float = 0.0
        self.last_video_at: float = 0.0
        self.state: Dict[str, Any] = {}
        self.commands_sent = 0
        self.video_packets = 0
        self.last_error: Optional[str] = None
        # Which path is in charge right now: 'direct' or 'phone'.
        self.active_path: str = 'phone'
        # When the direct path last answered. 0 = it never did.
        self.direct_ok_at: float = 0.0
        # True once the direct path has failed: the drone is (probably) on the
        # phone's hotspot now, so the phone path takes over until a probe says
        # otherwise. It starts False, because the optimistic guess - try the lab
        # path first - is the right one when the drone is in the lab.
        self.direct_suspect: bool = False
        self.direct_last_error: Optional[str] = None
        # What the phone last told us: the hotspot is on, the drone is on it.
        self.phone_ready: bool = False
        self.hotspot: Optional[bool] = None
        # The sidecar that owns this link, so the link can inject the drone's
        # state and its RTP without knowing how the sidecar is wired.
        self.bridge = None

    @property
    def has_direct(self) -> bool:
        return bool(self.direct_ip)

    def _inject_state(self, data: bytes) -> None:
        """Put the drone's state where the host's drone client listens."""
        if self.bridge:
            self.bridge._inject(self.device_id, self.state_port, data)

    def _inject_video(self, data: bytes) -> None:
        """Put the drone's RTP where vpt-stream's ffmpeg listens."""
        if self.bridge:
            self.bridge._inject(self.device_id, self.video_port, data)

    def direct_alive(self) -> bool:
        if not self.has_direct or not self.direct_ok_at:
            return False
        return (time.time() - self.direct_ok_at) < DIRECT_ALIVE_TTL_S

    def summary(self) -> Dict[str, Any]:
        return {
            'device_id': self.device_id,
            'phone_slot': self.phone_slot,
            'drone_label': self.drone_label,
            'ip': self.ip,
            'cmd_port': self.cmd_port,
            'state_port': self.state_port,
            'video_port': self.video_port,
            'local_cmd_port': self.local_cmd_port,
            'state_age_s': (time.time() - self.last_state_at) if self.last_state_at else None,
            'video_age_s': (time.time() - self.last_video_at) if self.last_video_at else None,
            'commands_sent': self.commands_sent,
            'video_packets': self.video_packets,
            'last_error': self.last_error,
            # The hybrid (TASK-173)
            'link_mode': self.link_mode,
            'active_path': self.active_path,
            'direct_ip': self.direct_ip,
            'direct_local_ip': self.direct_local_ip,
            'direct_alive': self.direct_alive(),
            'direct_suspect': self.direct_suspect,
            'direct_age_s': (time.time() - self.direct_ok_at) if self.direct_ok_at else None,
            'direct_last_error': self.direct_last_error,
            'phone_ready': self.phone_ready,
            'hotspot': self.hotspot,
        }


class _DirectLink:
    """The direct path: the host's own radio talking to the drone.

    In the lab the drone is its own access point and the host reaches it over a
    USB Wi-Fi dongle: the drone lives on the drone's subnet, and the dongle's
    address is the source the drone sees.

    The sidecar plays the SDK client on this path, so the direct path and the
    phone path look the same to the controller: the sidecar always answers on
    127.0.0.1, and the drone's state and RTP are re-injected where the rest of
    the stack already expects them.

    The command socket is bound once and kept: a drone only answers the
    address:port that sent its first `command`, so the socket that talks to the
    drone has to be the same socket for ever.
    """

    def __init__(self, link: _DroneLink, timeout_s: float = DIRECT_SEND_TIMEOUT_S):
        self.link = link
        self.timeout_s = float(timeout_s)
        # The probe is a separate clock from the command timeout: a probe may
        # wait longer, because nothing is waiting on it.
        self.probe_timeout_s = float(
            os.getenv('VPT_DRONE_DIRECT_PROBE_TIMEOUT_S') or DIRECT_PROBE_TIMEOUT_S)
        self.cmd_sock: Optional[socket.socket] = None
        self.state_sock: Optional[socket.socket] = None
        self.video_sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._threads: List[threading.Thread] = []
        self._stop = threading.Event()

    def start(self) -> None:
        link = self.link
        self._stop.clear()
        try:
            self.cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.cmd_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.cmd_sock.bind((link.direct_local_ip, link.direct_local_cmd_port))
            self.cmd_sock.settimeout(0.5)

            # The drone pushes its state and its video to FIXED ports of its
            # client, so the sidecar listens there and re-injects them.
            self.state_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.state_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.state_sock.bind((link.direct_local_ip, link.direct_state_port))
            self.state_sock.settimeout(0.5)

            self.video_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.video_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.video_sock.bind((link.direct_local_ip, link.direct_video_port))
            self.video_sock.settimeout(0.5)
        except OSError as e:
            self.link.direct_last_error = f'could not open the direct path: {e}'
            print(f"{_LOG} {link.device_id}: {self.link.direct_last_error}")
            return

        for fn, name in ((self._state_loop, 'direct-state'), (self._video_loop, 'direct-video')):
            t = threading.Thread(target=fn, daemon=True, name=f'drone-bridge-{name}-{link.device_id}')
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for s in (self.cmd_sock, self.state_sock, self.video_sock):
            try:
                if s:
                    s.close()
            except OSError:
                pass
        self.cmd_sock = self.state_sock = self.video_sock = None
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(timeout=2)
        self._threads = []

    # ---- the SDK conversation ---------------------------------------------

    def send(self, cmd: str, timeout_s: float = 0.0) -> str:
        """Send one SDK command to the drone and return its answer.

        The socket is bound, so the drone's answer comes back to the same
        address:port it was told to answer.
        """
        sock = self.cmd_sock
        if sock is None:
            raise DroneBridgeError('the direct path is not open')
        timeout_s = timeout_s or self.timeout_s
        with self._lock:
            try:
                sock.sendto(cmd.encode(), (self.link.direct_ip, self.link.direct_cmd_port))
                sock.settimeout(timeout_s)
                data, _ = sock.recvfrom(2048)
                return data.decode(errors='replace').strip()
            except socket.timeout:
                raise DroneBridgeError(f'the drone did not answer on the direct path: {cmd}')
            except OSError as e:
                raise DroneBridgeError(f'the direct path failed: {e}')
            finally:
                try:
                    sock.settimeout(0.5)
                except OSError:
                    pass

    def send_nowait(self, cmd: str) -> None:
        """Send a command the drone never answers (`rc`), without waiting."""
        if self.cmd_sock is None:
            return
        try:
            self.cmd_sock.sendto(cmd.encode(), (self.link.direct_ip, self.link.direct_cmd_port))
        except OSError as e:
            self.link.direct_last_error = f'could not send {cmd!r} on the direct path: {e}'

    def probe(self) -> bool:
        """Is the drone on the lab network right now?

        The probe is the SDK handshake (`command`) plus `battery?`: `command` is
        what makes the drone bind its answer to this socket, and `battery?` is
        the cheapest question that has an answer. A drone that is asleep
        answers nothing, and a drone on the phone's hotspot is not even
        reachable from here.
        """
        if self.cmd_sock is None or not self.link.direct_ip:
            return False
        try:
            self.send('command', timeout_s=self.probe_timeout_s)
        except DroneBridgeError:
            return False
        try:
            reply = self.send('battery?', timeout_s=self.probe_timeout_s)
        except DroneBridgeError:
            return False
        return bool(reply) and reply.lower() != 'error'

    # ---- the pushed channels ----------------------------------------------

    def _state_loop(self) -> None:
        """The drone pushes its state here; the sidecar re-injects it locally."""
        while not self._stop.is_set():
            try:
                data, _ = self.state_sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            text = data.decode(errors='replace').strip()
            self.link.last_state_at = time.time()
            parsed = _parse_state(text)
            if parsed:
                self.link.state = parsed
            self.link._inject_state(text.encode())

    def _video_loop(self) -> None:
        """The drone pushes its RTP here; the sidecar re-injects it locally."""
        while not self._stop.is_set():
            try:
                data, _ = self.video_sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            self.link.video_packets += 1
            self.link.last_video_at = time.time()
            self.link._inject_video(data)


class DroneBridge:
    """The sidecar: local UDP ports per drone, the Socket.IO conversation with the phone.

    One instance per host process, created by backend_host/__init__.py::register(app)
    next to the PhoneBridge it shares the Socket.IO connection with.
    """

    def __init__(self, socketio=None, phone_bridge=None):
        self.socketio = socketio
        self.phone_bridge = phone_bridge
        self.links: Dict[str, _DroneLink] = {}
        self._lock = threading.RLock()
        self._cmd_socks: Dict[str, socket.socket] = {}
        self._inject_socks: Dict[str, socket.socket] = {}
        self._direct_links: Dict[str, _DirectLink] = {}
        # The timings are read per instance, so a host can be tuned (and a test
        # can be quick) without touching the module.
        self.direct_probe_interval_s = float(
            os.getenv('VPT_DRONE_DIRECT_PROBE_INTERVAL_S') or DIRECT_PROBE_INTERVAL_S)
        self.direct_probe_timeout_s = float(
            os.getenv('VPT_DRONE_DIRECT_PROBE_TIMEOUT_S') or DIRECT_PROBE_TIMEOUT_S)
        self.direct_send_timeout_s = float(
            os.getenv('VPT_DRONE_DIRECT_SEND_TIMEOUT_S') or DIRECT_SEND_TIMEOUT_S)
        self._threads: List[threading.Thread] = []
        self._stop = threading.Event()
        self._load_from_env()

    # ---- configuration ----------------------------------------------------

    def _load_from_env(self) -> None:
        """Find the drones the environment says are bridged.

        A drone is bridged when DEVICE{i}_TELLO_BRIDGE is set. Its ports come
        from the same keys a lab drone uses, so one drone's configuration reads
        the same whether it is in the lab or in a field.
        """
        index = 1
        while index <= 64:
            device_id = f'device{index}'
            if not os.getenv(f'DEVICE{index}_TELLO_BRIDGE'):
                index += 1
                continue
            cmd_port = int(os.getenv(f'DEVICE{index}_TELLO_CMD_PORT') or 8889)
            state_port = int(os.getenv(f'DEVICE{index}_TELLO_STATE_PORT') or 8890)
            local_cmd_port = int(os.getenv(f'DEVICE{index}_TELLO_LOCAL_CMD_PORT') or cmd_port)
            video_port = _video_port_from_env(index)
            phone_slot = os.getenv(f'DEVICE{index}_TELLO_BRIDGE_PHONE') or ''
            drone_label = os.getenv(f'DEVICE{index}_TELLO_BRIDGE_DRONE') or device_id
            link_mode = (os.getenv(f'DEVICE{index}_TELLO_LINK') or 'phone').lower()
            if link_mode not in ('auto', 'direct', 'phone'):
                print(f"{_LOG} {device_id}: unknown TELLO_LINK '{link_mode}', using phone")
                link_mode = 'phone'
            direct_ip = os.getenv(f'DEVICE{index}_TELLO_DIRECT_IP') or None
            direct_local_ip = os.getenv(f'DEVICE{index}_TELLO_DIRECT_LOCAL_IP') or '0.0.0.0'
            direct_local_cmd_port = int(os.getenv(f'DEVICE{index}_TELLO_DIRECT_LOCAL_CMD_PORT') or 8883)
            direct_cmd_port = int(os.getenv(f'DEVICE{index}_TELLO_DIRECT_CMD_PORT') or 8889)
            direct_state_port = int(os.getenv(f'DEVICE{index}_TELLO_DIRECT_STATE_PORT') or 8890)
            direct_video_port = int(os.getenv(f'DEVICE{index}_TELLO_DIRECT_VIDEO_PORT') or 11111)
            link = _DroneLink(device_id, cmd_port, state_port,
                                                video_port, local_cmd_port,
                                                phone_slot, drone_label,
                                                link_mode=link_mode,
                                                direct_ip=direct_ip,
                                                direct_local_ip=direct_local_ip,
                                                direct_local_cmd_port=direct_local_cmd_port,
                                                direct_cmd_port=direct_cmd_port,
                                                direct_state_port=direct_state_port,
                                                direct_video_port=direct_video_port)
            link.bridge = self
            self.links[device_id] = link
            index += 1
        if self.links:
            print(f"{_LOG} {len(self.links)} bridged drone(s): "
                  f"{ {k: v.cmd_port for k, v in self.links.items()} }")

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Open the UDP ports and start the command loops."""
        self._stop.clear()
        for device_id, link in self.links.items():
            try:
                cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                cmd_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                cmd_sock.bind(('127.0.0.1', link.cmd_port))
                cmd_sock.settimeout(0.5)
                self._cmd_socks[device_id] = cmd_sock

                inject_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                inject_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                inject_sock.bind(('127.0.0.1', 0))
                self._inject_socks[device_id] = inject_sock

                t = threading.Thread(target=self._cmd_loop, args=(device_id, cmd_sock),
                                     daemon=True, name=f'drone-bridge-{device_id}')
                t.start()
                self._threads.append(t)

                # The hybrid (TASK-173): the direct path and the watcher that
                # notices the drone coming back to the lab network.
                if link.has_direct:
                    direct = _DirectLink(link, timeout_s=self.direct_send_timeout_s)
                    direct.start()
                    self._direct_links[device_id] = direct
                    link.active_path = 'direct'
                    w = threading.Thread(target=self._direct_watch, args=(device_id,),
                                         daemon=True, name=f'drone-bridge-watch-{device_id}')
                    w.start()
                    self._threads.append(w)

                print(f"{_LOG} {device_id}: cmd on 127.0.0.1:{link.cmd_port}, "
                      f"state -> :{link.state_port}, video -> :{link.video_port}, "
                      f"phone {link.phone_slot} drone {link.drone_label}, "
                      f"link {link.link_mode}"
                      + (f", direct {link.direct_ip}" if link.has_direct else ''))
            except OSError as e:
                print(f"{_LOG} {device_id}: could not open the bridge ports: {e}")

    def stop(self) -> None:
        self._stop.set()
        for direct in self._direct_links.values():
            direct.stop()
        self._direct_links.clear()
        for s in list(self._cmd_socks.values()) + list(self._inject_socks.values()):
            try:
                s.close()
            except OSError:
                pass
        self._cmd_socks.clear()
        self._inject_socks.clear()
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(timeout=2)
        self._threads = []

    # ---- the command path --------------------------------------------------

    def _cmd_loop(self, device_id: str, sock: socket.socket) -> None:
        """Answer SDK commands the way a drone would.

        The reply must go back to the SOURCE address the client sent from: a
        real Tello only answers the address:port that sent its first `command`
        after power-on, and the TelloClient binds one fixed local port for
        exactly that reason.

        A command the drone never answers (`rc`) is passed through without
        waiting: the joystick streams at 10 Hz, and a round trip per stick value
        would cap the stick at one command per phone round trip.
        """
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                text = data.decode(errors='replace').strip()
                if _expects_no_reply(text):
                    # Fire and forget: carry it, answer the client at once, and let
                    # the drone's side do its work without waiting either.
                    self._send_nowait(device_id, text)
                    sock.sendto(b'ok', addr)
                    continue
                reply = self.send_command(device_id, text)
            except DroneBridgeError as e:
                reply = 'error'
                link = self.links.get(device_id)
                if link:
                    link.last_error = str(e)
                print(f"{_LOG} {device_id}: '{text}' failed: {e}")
            try:
                sock.sendto(reply.encode(), addr)
            except OSError:
                pass

    def _send_nowait(self, device_id: str, cmd: str) -> None:
        """Carry a command the drone will not answer, without waiting for it."""
        link = self.links.get(device_id)
        if not link:
            return
        path = self._choose_path(link)
        if path == 'direct':
            direct = self._direct_links.get(device_id)
            if direct:
                direct.send_nowait(cmd)
                link.commands_sent += 1
                return
        # A fire-and-forget command gives no answer, so it cannot prove the
        # path; the suspicion is cleared by the next answered command.
        self._send_to_phone_nowait(link, cmd)

    def send_command(self, device_id: str, cmd: str) -> str:
        """Carry one SDK command to the drone and return the drone's reply.

        The direct path is tried first when it is in charge. If the drone has
        moved to the phone's hotspot the direct path fails, and the command is
        carried on the phone path instead - the drone is simply somewhere else
        now, and the drone's answer is the same answer.
        """
        link = self.links.get(device_id)
        if not link:
            raise DroneBridgeError(f'no bridged drone {device_id}')
        path = self._choose_path(link)
        if path == 'direct':
            direct = self._direct_links.get(device_id)
            if direct:
                try:
                    reply = direct.send(cmd)
                    link.commands_sent += 1
                    link.direct_ok_at = time.time()
                    link.direct_suspect = False
                    link.active_path = 'direct'
                    return reply
                except DroneBridgeError as e:
                    link.direct_last_error = str(e)
                    link.direct_ok_at = 0.0
                    link.direct_suspect = True
                    if link.link_mode == 'direct':
                        raise
                    print(f"{_LOG} {device_id}: direct path failed ({e}); trying the phone")
                    link.active_path = 'phone'
        reply = self._call_phone(link, cmd)
        link.commands_sent += 1
        return reply

    def _choose_path(self, link: _DroneLink) -> str:
        """Which path carries this command.

        'auto' prefers the direct path - the lab, no latency - and uses the
        phone when the drone is not on the lab network any more.

        The first guess is always the direct path: the drone is on one Wi-Fi
        network at a time, and the lab is where it usually is. A direct path that
        fails marks the drone as suspect, and only a probe (or a direct success)
        clears that suspicion.
        """
        if link.link_mode == 'phone':
            return 'phone'
        if link.link_mode == 'direct':
            return 'direct'
        return 'phone' if link.direct_suspect else 'direct'

    def _direct_watch(self, device_id: str) -> None:
        """Watch the direct path so the bridge can come back to it.

        The probe runs only while the phone path is in charge: it wakes the
        drone, and the drone is only worth waking when it is somewhere the
        phone cannot see.
        """
        while not self._stop.is_set():
            time.sleep(self.direct_probe_interval_s)
            if self._stop.is_set():
                return
            link = self.links.get(device_id)
            direct = self._direct_links.get(device_id)
            if not link or not direct:
                return
            if link.link_mode != 'auto' or not link.direct_suspect:
                continue
            if not link.has_direct:
                continue
            try:
                alive = direct.probe()
            except Exception:
                alive = False
            if alive:
                link.direct_ok_at = time.time()
                link.direct_suspect = False
                link.active_path = 'direct'
                link.direct_last_error = None
                print(f"{_LOG} {device_id}: the drone answered on the direct path again "
                      f"({link.direct_ip}); back to the lab path")

    # ---- the phone path ----------------------------------------------------

    def _call_phone(self, link: _DroneLink, cmd: str) -> str:
        """Ask the phone to run one command on the drone and wait for the answer.

        The phone holds the drone's socket, so the reply comes back the way the
        drone sent it: the phone answers with the drone's own text.
        """
        if not self.socketio:
            raise DroneBridgeError('socketio is not available on this host')
        if self.phone_bridge is None:
            raise DroneBridgeError('no phone bridge on this host')
        sid = self.phone_bridge.sid_for_device(link.phone_slot)
        if not sid:
            raise DroneBridgeError(f'no phone is connected on slot {link.phone_slot}')
        payload = {'drone': link.device_id, 'target': link.drone_label, 'cmd': cmd}
        try:
            ack = self.phone_bridge.call_phone(protocol.EV_DRONE_CMD, payload, sid,
                                               protocol.DRONE_CMD_TIMEOUT_S)
        except Exception as e:
            raise DroneBridgeError(f'the phone did not answer: {e}')
        if not isinstance(ack, dict):
            raise DroneBridgeError(f'malformed answer from the phone: {ack!r}')
        if not ack.get('ok'):
            raise DroneBridgeError(str(ack.get('error') or 'the phone refused the command'))
        return str(ack.get('reply') or '')

    def _send_to_phone_nowait(self, link: _DroneLink, cmd: str) -> None:
        """Carry a command the drone will not answer, without waiting for it."""
        if not self.socketio or self.phone_bridge is None:
            return
        sid = self.phone_bridge.sid_for_device(link.phone_slot)
        if not sid:
            return
        payload = {'drone': link.device_id, 'target': link.drone_label, 'cmd': cmd}
        try:
            self.socketio.emit(protocol.EV_DRONE_CMD, payload,
                               namespace=protocol.NAMESPACE, to=sid)
            link.commands_sent += 1
        except Exception as e:
            print(f"{_LOG} {link.device_id}: could not send '{cmd}': {e}")

    # ---- the state and video paths -----------------------------------------

    def _resolve(self, name: Optional[str]) -> Optional[_DroneLink]:
        """The link a phone message refers to.

        The phone knows the drone by the label the owner gave it ('droneA'); the
        host knows it by the device slot ('device3'). Both names are accepted, so
        the phone does not have to know the host's slot numbering.
        """
        if not name:
            return None
        link = self.links.get(name)
        if link:
            return link
        for candidate in self.links.values():
            if candidate.drone_label == name:
                return candidate
        return None

    def handle_state(self, payload: Dict[str, Any]) -> None:
        """The phone pushed one of the drone's state datagrams."""
        link = self._resolve((payload or {}).get('drone'))
        if not link:
            return
        text = (payload or {}).get('text') or ''
        parsed = _parse_state(text)
        if parsed:
            link.state = parsed
        link.last_state_at = time.time()
        # The client listens on its own state port; inject the datagram there
        # so TelloClient's state thread sees it exactly as it would from the air.
        link._inject_state(text.encode())

    def handle_video(self, payload: Any, data: bytes) -> None:
        """The phone pushed one RTP video packet from the drone."""
        name = (payload or {}).get('drone') if isinstance(payload, dict) else None
        link = self._resolve(name)
        if not link:
            return
        link.video_packets += 1
        link.last_video_at = time.time()
        # ffmpeg reads udp://127.0.0.1:<video port>; injecting the packet there
        # keeps the whole existing video pipeline (BUG-0824's per-address bind
        # included) untouched.
        link._inject_video(data)

    def _inject(self, device_id: str, port: int, data: bytes) -> None:
        """Put a datagram on one of the host's local ports.

        Both paths end here: the phone's state and RTP, and the drone's own
        state and RTP on the lab network, are injected on the same ports, so
        the rest of the stack cannot tell which one is in charge.
        """
        sock = self._inject_socks.get(device_id)
        if not sock or not data:
            return
        try:
            sock.sendto(data, ('127.0.0.1', port))
        except OSError as e:
            link = self.links.get(device_id)
            if link:
                link.last_error = f'inject on port {port} failed: {e}'

    # ---- status ------------------------------------------------------------

    def handle_status(self, payload: Dict[str, Any]) -> None:
        """The phone reported which drones it is carrying.

        The phone is the fallback path, so what it says matters: the hotspot
        being on, and the drone being on it, are what make the phone path
        usable at all.
        """
        payload = payload or {}
        hotspot = payload.get('hotspot')
        for entry in payload.get('drones') or []:
            link = self._resolve(entry.get('label') or entry.get('id'))
            if link:
                link.ip = entry.get('ip')
                link.phone_ready = True
                link.hotspot = hotspot
                # The phone says the drone is not on its hotspot: the fallback
                # is not available, and the direct path has to carry the drone.
                if entry.get('present') is False:
                    link.phone_ready = False
        if hotspot is False:
            for link in self.links.values():
                if link.phone_slot and link.phone_slot == (payload.get('slot') or link.phone_slot):
                    link.hotspot = False

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            return {k: v.summary() for k, v in self.links.items()}


def _parse_state(text: str) -> Optional[Dict[str, Any]]:
    """The drone's state datagram, read the way the drone client reads it."""
    try:
        from shared.src.lib.drone.tello import parse_state
    except Exception:
        return None
    try:
        return parse_state(text)
    except Exception:
        return None


def _expects_no_reply(cmd: str) -> bool:
    """True for a command the drone never answers (`rc`).

    The drone holds the stick values until the next one, so there is nothing to
    wait for - and the joystick streams at 10 Hz.
    """
    verb = cmd.strip().split(' ')[0].lower() if cmd.strip() else ''
    return verb in protocol.DRONE_NO_REPLY_COMMANDS


def _video_port_from_env(index: int) -> int:
    """The port the drone's RTP is injected on.

    It is the port vpt-stream's ffmpeg reads for this device, taken from
    DEVICE{i}_VIDEO (udp://127.0.0.1:29001 -> 29001). Falling back to the
    stock 11111 keeps a half-configured drone from writing into another
    drone's port.
    """
    explicit = os.getenv(f'DEVICE{index}_TELLO_VIDEO_PORT')
    if explicit:
        return int(explicit)
    url = os.getenv(f'DEVICE{index}_VIDEO') or ''
    if url.startswith('udp://'):
        port = url.rsplit(':', 1)[-1].split('?')[0].strip()
        if port.isdigit():
            return int(port)
    return 11111
