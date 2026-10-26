#!/usr/bin/env python3
"""
features/mobile-app/backend_host/drone_phone_sim.py — a fake phone that also carries
drones (TASK-167).

The real phone app is the radio end of a remote drone: it holds the drone's SDK
conversation over Wi-Fi and relays it to the host over the Socket.IO channel. This
module is that phone without a phone, so the whole chain can be tested on one
machine:

    drone simulator (real UDP)  <--UDP-->  this module  <--Socket.IO-->  drone_bridge

It speaks the drone half of the phone protocol (features/mobile-app/lib/protocol.py):
the host sends `drone_cmd`, this module runs the command on the drone over UDP and
answers with the drone's own reply; the drone's pushed state and RTP go the other
way, up to the host.

Details of the real Tello shape this reproduces, because the host side depends on
them:

  * ONE command socket for every drone. A Tello only answers the address:port
    that sent its first `command` after power-on, so the socket that talks to a
    drone has to stay the same socket. The drones are told apart by source address.
  * The drone pushes state and video to FIXED ports (8890 / 11111) of its client,
    so every drone on this phone pushes to the same two ports and is demultiplexed
    by source address.

The ports are explicit rather than ephemeral, because the drone simulator has to
be told where to push its state and its video.

Run standalone:
    python3 drone_phone_sim.py --host-url http://127.0.0.1:6109 --token <token> \
        --drone 127.0.0.1 --label droneA
"""
import argparse
import importlib
import os
import socket
import sys
import threading
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, '..', '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

protocol = importlib.import_module('features.mobile-app.lib.protocol')  # noqa: E402

import socketio as sio_client  # noqa: E402

_LOG = '[@mobile-app:drone_phone_sim]'

# The drone's own ports, on the phone's hotspot interface.
DRONE_CMD_PORT = 8889
DRONE_STATE_PORT = 8890
DRONE_VIDEO_PORT = 11111


class DronePhoneSim:
    """A phone that carries drones: one SDK socket, N drones, one Socket.IO link."""

    def __init__(self, host_url: str, token: str = None, device_secret: str = None,
                 drone_ips=None, drone_labels=None, socketio_path: str = None,
                 device_id: str = None, cmd_port: int = DRONE_CMD_PORT,
                 state_port: int = DRONE_STATE_PORT, video_port: int = DRONE_VIDEO_PORT,
                 drone_cmd_port: int = DRONE_CMD_PORT,
                 hotspot_enabled: bool = True, drone_present: bool = True):
        self.host_url = host_url.rstrip('/')
        self.token = token
        self.device_secret = device_secret
        self.socketio_path = socketio_path or 'socket.io'
        self.device_id = device_id
        # The port the DRONE answers commands on. A real drone always uses 8889;
        # the simulator may sit on another number, so it is a parameter.
        self.drone_cmd_port = drone_cmd_port
        # The drones this phone carries, as (ip, label) pairs. The label is what
        # the host's .env names (DEVICE3_TELLO_BRIDGE_DRONE=droneA).
        self.drones = list(zip(drone_ips or [], drone_labels or []))
        # The hybrid (TASK-173): the phone says whether its hotspot is on and
        # whether the drone is really on it. The host needs both to know if the
        # phone can carry the drone at all.
        self.hotspot_enabled = hotspot_enabled
        self.drone_present = drone_present

        # ONE command socket for every drone: a drone only answers the
        # address:port that sent its first `command`, so this socket must be the
        # one that keeps talking to all of them.
        self.cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cmd_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.cmd_sock.bind(('127.0.0.1', cmd_port))
        self.cmd_sock.settimeout(0.3)

        # State and video are pushed by the drone to fixed ports.
        self.state_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.state_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.state_sock.bind(('127.0.0.1', state_port))
        self.state_sock.settimeout(0.3)

        self.video_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.video_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.video_sock.bind(('127.0.0.1', video_port))
        self.video_sock.settimeout(0.3)

        self.sio = sio_client.Client(reconnection=False)
        self._connected_event = threading.Event()
        self._stop = threading.Event()
        self._threads = []
        self._register_handlers()

    # ---- lifecycle -------------------------------------------------------

    def start(self, wait_connected: float = 8.0) -> dict:
        self._connected_event.clear()
        self.sio.connect(
            self.host_url, namespaces=[protocol.NAMESPACE],
            socketio_path=self.socketio_path, wait_timeout=wait_connected,
            headers={'User-Agent': 'Mozilla/5.0 (VirtualPyTest drone_phone_sim)'},
        )
        if not self._connected_event.wait(wait_connected):
            raise RuntimeError('drone phone sim did not connect in time')
        self._send_hello(wait_connected)
        self._start_threads()
        self._send_status()
        return {'device_id': self.device_id, 'drones': self.drones}

    def _send_hello(self, timeout_s: float) -> None:
        """Claim the phone slot, the same way the real app does.

        Without this the host does not know which session carries the drone, and
        the drone commands have nowhere to go.
        """
        if not self.token and not self.device_secret:
            raise RuntimeError('the drone phone sim needs a token or a device_secret')
        payload = {'v': protocol.PROTOCOL_VERSION}
        if self.token:
            payload['token'] = self.token
        else:
            payload['device_secret'] = self.device_secret
        payload['device'] = {'manufacturer': 'VPT', 'model': 'DronePhoneSim', 'android': '14'}

        answer = {}

        def _ack(result):
            answer['result'] = result

        self.sio.emit(protocol.EV_HELLO, payload, namespace=protocol.NAMESPACE, callback=_ack)
        deadline = time.time() + timeout_s
        while time.time() < deadline and 'result' not in answer:
            time.sleep(0.05)
        result = answer.get('result') or {}
        if not result.get('ok'):
            raise RuntimeError(f'the host refused the hello: {result.get("error")}')
        self.device_id = result.get('device_id') or self.device_id
        self.device_secret = result.get('device_secret') or self.device_secret
        print(f"{_LOG} paired as {self.device_id}")

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        self._threads = []
        try:
            self.sio.disconnect()
        except Exception:
            pass
        for s in (self.cmd_sock, self.state_sock, self.video_sock):
            try:
                s.close()
            except OSError:
                pass

    # ---- the drone side --------------------------------------------------

    def _start_threads(self) -> None:
        for fn, name in ((self._state_loop, 'state'), (self._video_loop, 'video'),
                         (self._status_loop, 'status')):
            t = threading.Thread(target=fn, daemon=True, name=f'drone-phone-{name}')
            t.start()
            self._threads.append(t)

    def _state_loop(self) -> None:
        """Push the drone's state datagrams up to the host."""
        while not self._stop.is_set():
            try:
                data, addr = self.state_sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            label = self._label_for(addr[0])
            if not label:
                continue
            payload = {'drone': label, 'text': data.decode(errors='replace').strip()}
            try:
                self.sio.emit(protocol.EV_DRONE_STATE, payload, namespace=protocol.NAMESPACE)
            except Exception:
                return

    def _video_loop(self) -> None:
        """Push the drone's RTP packets up to the host."""
        while not self._stop.is_set():
            try:
                data, addr = self.video_sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            label = self._label_for(addr[0])
            if not label:
                continue
            try:
                # The tuple form, the same one the frame event uses: socketio.emit
                # takes ONE data argument, so a dict and a packet have to travel
                # together as (meta, bytes) or the bytes land in the namespace.
                self.sio.emit(protocol.EV_DRONE_VIDEO, ({'drone': label}, data),
                              namespace=protocol.NAMESPACE)
            except Exception:
                return

    def _label_for(self, ip: str):
        for drone_ip, label in self.drones:
            if drone_ip == ip:
                return label
        return None

    def _run_on_drone(self, ip: str, cmd: str) -> str:
        """Send the command straight to the drone and wait for its reply.

        This is the phone's own radio work. The command leaves from the socket
        the drone is bound to, and the drone's answer comes back on it.

        A command the drone never answers (`rc`) is sent without waiting: the
        joystick streams at 10 Hz and a wait per stick value would cap it at one
        command per round trip.
        """
        verb = cmd.strip().split(' ')[0].lower() if cmd.strip() else ''
        try:
            self.cmd_sock.sendto(cmd.encode(), (ip, self.drone_cmd_port))
            if verb in protocol.DRONE_NO_REPLY_COMMANDS:
                return 'ok'
            self.cmd_sock.settimeout(3.0)
            data, _ = self.cmd_sock.recvfrom(2048)
            return data.decode(errors='replace').strip()
        except socket.timeout:
            return 'error'
        finally:
            self.cmd_sock.settimeout(0.3)

    # ---- the phone side --------------------------------------------------

    def _send_status(self) -> None:
        """Tell the host which drones this phone is carrying, and whether it can.

        The host chooses the path (TASK-173): it prefers the lab's own radio
        and falls back to this phone, so it has to know whether the hotspot is
        on and whether the drone is on it right now.
        """
        payload = {'drones': [{'label': label, 'ip': ip, 'present': self.drone_present}
                              for ip, label in self.drones],
                   'hotspot': self.hotspot_enabled}
        try:
            self.sio.emit(protocol.EV_DRONE_STATUS, payload, namespace=protocol.NAMESPACE)
        except Exception:
            pass

    def _status_loop(self) -> None:
        """Keep the host's picture of this phone fresh."""
        while not self._stop.is_set():
            try:
                self._stop.wait(5.0)
            except Exception:
                return
            if self._stop.is_set():
                return
            self._send_status()

    def _register_handlers(self) -> None:
        sio = self.sio

        @sio.on('connect', namespace=protocol.NAMESPACE)
        def _on_connect():
            self._connected_event.set()
            print(f'{_LOG} connected')

        @sio.on('disconnect', namespace=protocol.NAMESPACE)
        def _on_disconnect():
            self._connected_event.clear()
            print(f'{_LOG} disconnected')

        @sio.on(protocol.EV_DRONE_CMD, namespace=protocol.NAMESPACE)
        def _on_drone_cmd(payload):
            """The host sent a command for one of our drones."""
            payload = payload or {}
            label = payload.get('target') or payload.get('drone')
            cmd = payload.get('cmd') or ''
            for drone_ip, drone_label in self.drones:
                if drone_label != label:
                    continue
                return {'ok': True, 'reply': self._run_on_drone(drone_ip, cmd)}
            return {'ok': False, 'error': f'this phone does not carry a drone called {label}'}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--host-url', required=True)
    parser.add_argument('--token')
    parser.add_argument('--device-secret')
    parser.add_argument('--drone', action='append', default=[],
                        help='drone address on the phone hotspot (repeatable)')
    parser.add_argument('--label', action='append', default=[],
                        help='label for the matching --drone (repeatable)')
    parser.add_argument('--device-id')
    parser.add_argument('--no-hotspot', action='store_true',
                        help='report the hotspot as off (the phone cannot carry a drone)')
    parser.add_argument('--no-drone', action='store_true',
                        help='report the drone as not present on the hotspot')
    args = parser.parse_args()

    sim = DronePhoneSim(args.host_url, token=args.token, device_secret=args.device_secret,
                        drone_ips=args.drone, drone_labels=args.label or None,
                        device_id=args.device_id,
                        hotspot_enabled=not args.no_hotspot,
                        drone_present=not args.no_drone)
    try:
        print(sim.start())
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
