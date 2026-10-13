#!/usr/bin/env python3
"""
vpt-procon: emulate ONE Nintendo Switch Pro Controller over Bluetooth (nxbt).

Runs as root under systemd (vpt-procon.service) with the nxbt venv
(/opt/nxbt-venv/bin/python, see setup/local/linux/backend_host/install_procon.sh).
It must NOT import anything from VirtualPyTest: the host's
`bluetooth_procon` switch controller talks to it over a tiny local HTTP API.

What it owns
------------
- Adapter prep (each time a controller is created): optional MAC (so the
  existing Switch bond keeps matching after a reboot), power on, Gamepad
  class 0x002508.
- A NoInputNoOutput default pairing agent on D-Bus (without one bluetoothd
  refuses the Switch's auth request: "No agent available for request type 2").
- ONE nxbt Pro Controller:
    * reconnect mode (default when a Switch is bonded): page the bonded
      Switch; when it is unreachable (asleep, off, out of range) retry every
      PROCON_RETRY_S. nxbt's own fallback into "accept any Switch" is
      disabled in this mode, so the bond is never touched by accident.
    * pairing mode (POST /pair, or automatically when no Switch is bonded):
      discoverable, waiting for Controllers -> Change Grip/Order. Closes
      after PROCON_PAIR_WINDOW_S if nothing paired.
- Exit when bluetoothd restarts (new org.bluez owner): systemd restarts us
  and everything is re-registered (same self-heal as hid_remote.py).

nxbt patches (applied before nxbt.Nxbt() is created)
- toggle_clean_bluez -> no-op. nxbt otherwise writes its own bluetooth
  drop-in at start and, at EXIT, deletes it and restarts bluetoothd, which
  kills any live link. The bluetoothd flags (--compat --noplugin=*) come
  from the persistent drop-in installed by install_procon.sh instead.
- ControllerServer._on_exit -> no-op (it calls a non-existent bt.reset_address()).
- ControllerServer.connect refuses to run in reconnect mode (see above).
- nxbt's multiprocessing Lock -> threading.Lock: one controller only, and a
  controller process killed while waiting for a Switch can never leave a
  cross-process lock held.

HTTP API (PROCON_BIND:PROCON_PORT, default 127.0.0.1:6190, JSON in/out;
X-Procon-Token header required when PROCON_TOKEN is set)
  GET  /status
  POST /press     {"button": "a", "hold_ms": 100}
  POST /sequence  {"buttons": ["down", "down", "a"], "hold_ms": 100, "gap_ms": 150}
  POST /hold      {"buttons": ["zr"]}           (held until /release)
  POST /release   {}
  POST /stick     {"stick": "left", "direction": "up", "duration_ms": 200}
                  or {"stick": "left", "x": 100, "y": 0, "duration_ms": 200}  (-100..100)
  POST /pair      {}

Never run another nxbt program (nxbt CLI, a test script) while this runs:
two nxbt instances fight over the adapter, and a plain nxbt exiting
restarts bluetoothd.
"""

import collections
import collections.abc
import hmac
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# nxbt pins dbus-python 1.2.16, whose dbus.service still does
# `from collections import Sequence` (removed in Python 3.10).
collections.Sequence = collections.abc.Sequence

import dbus  # noqa: E402
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

import nxbt
import nxbt.nxbt as nxbt_core
from nxbt import bluez as nxbt_bluez
from nxbt.controller import server as nxbt_server

ADAPTER = os.getenv('PROCON_ADAPTER', 'hci0')
# nxbt takes the FIRST adapter when none is given: on a host whose other
# adapter runs a BLE STB remote it would grab that one. Always pin it.
ADAPTER_PATH = f'/org/bluez/{ADAPTER}'
ADAPTER_MAC = os.getenv('PROCON_ADAPTER_MAC', '').strip().upper()
PORT = int(os.getenv('PROCON_PORT', '6190'))
# 127.0.0.1 by default. To serve a vpt-host on another LAN host (the one with
# the Switch's HDMI grabber), bind 0.0.0.0 and set PROCON_TOKEN: every request
# must then carry it in X-Procon-Token.
BIND = os.getenv('PROCON_BIND', '127.0.0.1')
TOKEN = os.getenv('PROCON_TOKEN', '')
RETRY_S = float(os.getenv('PROCON_RETRY_S', '15'))
PAIR_WINDOW_S = float(os.getenv('PROCON_PAIR_WINDOW_S', '180'))
GAMEPAD_CLASS = '0x002508'
RECONNECT_ONLY = 'reconnect-only mode: Switch unreachable'
AGENT_PATH = '/vpt/procon/agent'
# nxbt's manager process leaks fds on every controller re-creation; at the
# ulimit it dies for good (BUG-0361). Exit before that so systemd restarts us.
MAX_MANAGER_FDS = int(os.getenv('PROCON_MAX_MANAGER_FDS', '400'))
MAX_CREATE_FAILURES = 5

# Audio profile UUIDs (HFP/HSP/A2DP). If any is registered on the adapter the
# Switch pairs but never opens the HID channels (PipeWire/WirePlumber does this).
AUDIO_UUIDS = {
    '0000111e-0000-1000-8000-00805f9b34fb': 'Handsfree',
    '0000111f-0000-1000-8000-00805f9b34fb': 'Handsfree AG',
    '00001108-0000-1000-8000-00805f9b34fb': 'Headset',
    '00001112-0000-1000-8000-00805f9b34fb': 'Headset AG',
    '0000110a-0000-1000-8000-00805f9b34fb': 'A2DP Source',
    '0000110b-0000-1000-8000-00805f9b34fb': 'A2DP Sink',
}

BUTTONS = {
    'a': 'A', 'b': 'B', 'x': 'X', 'y': 'Y',
    'l': 'L', 'r': 'R', 'zl': 'ZL', 'zr': 'ZR',
    'minus': 'MINUS', 'plus': 'PLUS', 'home': 'HOME', 'capture': 'CAPTURE',
    'l3': 'L_STICK_PRESS', 'lstick': 'L_STICK_PRESS',
    'r3': 'R_STICK_PRESS', 'rstick': 'R_STICK_PRESS',
    'up': 'DPAD_UP', 'down': 'DPAD_DOWN', 'left': 'DPAD_LEFT', 'right': 'DPAD_RIGHT',
    'dpad_up': 'DPAD_UP', 'dpad_down': 'DPAD_DOWN',
    'dpad_left': 'DPAD_LEFT', 'dpad_right': 'DPAD_RIGHT',
}
STICK_DIRECTIONS = {'up': (0, 100), 'down': (0, -100), 'left': (-100, 0), 'right': (100, 0)}


def log(msg):
    print(f'[vpt-procon] {msg}', flush=True)


# ---------------------------------------------------------------- nxbt patches
nxbt_core.toggle_clean_bluez = lambda *_a, **_k: None
nxbt_core.Lock = threading.Lock
nxbt_server.ControllerServer._on_exit = lambda self: None

_orig_run = nxbt_server.ControllerServer.run
_orig_connect = nxbt_server.ControllerServer.connect


def _run(self, reconnect_address=None):
    self._vpt_pairing = not reconnect_address
    return _orig_run(self, reconnect_address)


def _connect(self):
    if not getattr(self, '_vpt_pairing', True):
        raise OSError(RECONNECT_ONLY)
    return _orig_connect(self)


nxbt_server.ControllerServer.run = _run
nxbt_server.ControllerServer.connect = _connect


# ---------------------------------------------------------------- adapter prep
def run_cmd(args, timeout=10):
    # stdin is an empty closed pipe, never /dev/null: btmgmt wedges on /dev/null.
    try:
        r = subprocess.run(args, input=b'', capture_output=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).decode(errors='replace')
    except Exception as e:  # timeout, missing binary
        return -1, str(e)


def adapter_address():
    _, out = run_cmd(['hciconfig', ADAPTER])
    for token in out.split():
        if token.count(':') == 5:
            return token.upper()
    return None


def ensure_adapter():
    index = ADAPTER.replace('hci', '')
    if ADAPTER_MAC and adapter_address() != ADAPTER_MAC:
        log(f'setting {ADAPTER} address {adapter_address()} -> {ADAPTER_MAC}')
        for _ in range(20):
            for step in (['power', 'off'], ['public-addr', ADAPTER_MAC],
                         ['bredr', 'on'], ['power', 'on']):
                run_cmd(['btmgmt', '--index', index] + step, timeout=5)
                time.sleep(1)
            if adapter_address() == ADAPTER_MAC:
                break
            time.sleep(2)
        else:
            log(f'WARNING: {ADAPTER} still on {adapter_address()}; the bonded Switch '
                f'will not recognise it (re-pair, or fix PROCON_ADAPTER_MAC)')
    run_cmd(['btmgmt', '--index', index, 'power', 'on'], timeout=5)
    run_cmd(['hciconfig', ADAPTER, 'class', GAMEPAD_CLASS])


# ---------------------------------------------------------------- D-Bus agent
class Agent(dbus.service.Object):
    """NoInputNoOutput agent: accept everything (Just Works)."""

    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Release(self):
        pass

    @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        log(f'agent: authorize service {uuid} for {device}')

    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='s')
    def RequestPinCode(self, device):
        return '0000'

    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='u')
    def RequestPasskey(self, device):
        return dbus.UInt32(0)

    @dbus.service.method('org.bluez.Agent1', in_signature='ouq', out_signature='')
    def DisplayPasskey(self, device, passkey, entered):
        pass

    @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
    def DisplayPinCode(self, device, pincode):
        pass

    @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='')
    def RequestConfirmation(self, device, passkey):
        log(f'agent: confirm pairing with {device}')

    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        log(f'agent: authorize {device}')

    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Cancel(self):
        pass


def start_dbus_side():
    """Register the agent and exit when bluetoothd restarts. Runs a GLib loop thread."""
    # Private connection: nxbt calls bus.close() on the shared SystemBus.
    bus = dbus.SystemBus(private=True, mainloop=dbus.mainloop.glib.DBusGMainLoop())
    agent = Agent(bus, AGENT_PATH)
    manager = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.AgentManager1')
    manager.RegisterAgent(AGENT_PATH, 'NoInputNoOutput')
    manager.RequestDefaultAgent(AGENT_PATH)
    log('pairing agent registered (NoInputNoOutput, default)')

    def owner_changed(name, old, new):
        if name == 'org.bluez' and old:
            log('bluetoothd restarted (org.bluez owner changed): exiting so systemd restarts us')
            os._exit(1)

    bus.add_signal_receiver(owner_changed, signal_name='NameOwnerChanged',
                            dbus_interface='org.freedesktop.DBus', arg0='org.bluez')
    threading.Thread(target=GLib.MainLoop().run, daemon=True, name='glib').start()
    return bus, agent


def adapter_audio_profiles():
    bus = None
    try:
        bus = dbus.SystemBus(private=True)
        props = dbus.Interface(bus.get_object('org.bluez', f'/org/bluez/{ADAPTER}'),
                               'org.freedesktop.DBus.Properties')
        uuids = [str(u).lower() for u in props.Get('org.bluez.Adapter1', 'UUIDs')]
        return [AUDIO_UUIDS[u] for u in uuids if u in AUDIO_UUIDS]
    except Exception:
        return []
    finally:
        if bus is not None:
            bus.close()


# ---------------------------------------------------------------- supervisor
class Procon:
    def __init__(self):
        self.nx = nxbt.Nxbt()
        self.lock = threading.RLock()
        self.idx = None
        self.mode = 'starting'          # reconnect | pairing
        self.pair_until = None
        self.pair_requested = False
        self.next_attempt = 0.0
        self.last_error = None
        self.switch_address = None
        self.held = None                # direct-input packet while /hold is active
        self.create_failures = 0

    # -- helpers
    def bonded_switches(self):
        # Only Switches bonded to OUR adapter (another adapter may hold other bonds).
        try:
            addresses, paths = nxbt_bluez.find_devices_by_alias('Nintendo Switch', return_path=True)
        except Exception:
            return []
        return [a for a, p in zip(addresses, paths) if p.startswith(ADAPTER_PATH + '/')]

    def controller_state(self):
        if self.idx is None:
            return None
        try:
            return self.nx.state[self.idx]['state']
        except Exception:
            return None

    def _remove(self):
        if self.idx is not None:
            try:
                self.nx.remove_controller(self.idx)
            except Exception:
                pass
            self.idx = None
            self.held = None

    def _create(self, pairing):
        ensure_adapter()
        audio = adapter_audio_profiles()
        if audio:
            log(f'WARNING: audio profiles registered on {ADAPTER}: {audio}. The Switch will '
                f'not open the HID channels; disable the PipeWire/WirePlumber bluetooth monitor.')
        bonded = self.bonded_switches()
        if pairing or not bonded:
            self.mode = 'pairing'
            self.pair_until = time.time() + PAIR_WINDOW_S if bonded else None
            log('pairing mode: open Controllers -> Change Grip/Order on the Switch'
                + ('' if bonded else ' (no bonded Switch yet)'))
            self.idx = self.nx.create_controller(nxbt.PRO_CONTROLLER, adapter_path=ADAPTER_PATH)
        else:
            self.mode = 'reconnect'
            self.pair_until = None
            self.idx = self.nx.create_controller(nxbt.PRO_CONTROLLER, adapter_path=ADAPTER_PATH,
                                              reconnect_address=bonded)

    def fatal_reason(self):
        """Why this daemon cannot recover by itself, or None. A fresh process can."""
        proc = getattr(self.nx, 'controllers', None)
        if proc is not None and not proc.is_alive():
            return 'nxbt manager process is dead'
        try:
            fds = len(os.listdir(f'/proc/{proc.pid}/fd'))
        except Exception:
            fds = 0
        if fds > MAX_MANAGER_FDS:
            return f'nxbt manager process leaked {fds} file descriptors'
        if self.create_failures >= MAX_CREATE_FAILURES:
            return f'{self.create_failures} consecutive create-controller failures ({self.last_error})'
        return None

    def tick(self):
        with self.lock:
            now = time.time()
            reason = self.fatal_reason()
            if reason:
                log(f'FATAL: {reason}: exiting so systemd restarts vpt-procon')
                os._exit(1)
            if self.pair_requested:
                self.pair_requested = False
                self._remove()
                self._create(pairing=True)
                return
            state = self.controller_state()
            if state == 'connected':
                try:
                    self.switch_address = self.nx.state[self.idx].get('last_connection')
                except Exception:
                    pass
                if self.mode == 'pairing':
                    log(f'paired and connected to {self.switch_address}')
                    self.mode = 'reconnect'
                    self.pair_until = None
                self.last_error = None
                return
            if state == 'crashed':
                errors = ''
                try:
                    errors = self.nx.state[self.idx].get('errors') or ''
                except Exception:
                    pass
                if RECONNECT_ONLY in errors:
                    self.last_error = 'Switch unreachable (asleep, off or out of range)'
                    delay = RETRY_S
                else:
                    # A live link dropped (e.g. ConnectionAbortedError): retry right away.
                    self.last_error = errors.strip().splitlines()[-1] if errors else 'controller crashed'
                    log(f'controller stopped: {self.last_error}')
                    delay = 2
                self._remove()
                self.next_attempt = now + delay
                return
            if state == 'connecting' and self.mode == 'pairing' and self.pair_until and now > self.pair_until:
                log('pairing window closed without a Switch: back to reconnect mode')
                self._remove()
                self.next_attempt = now
                return
            if self.idx is None and now >= self.next_attempt:
                try:
                    self._create(pairing=False)
                    self.create_failures = 0
                except Exception as e:
                    self.create_failures += 1
                    self.last_error = f'create controller failed: {e}'
                    log(self.last_error)
                    self._remove()
                    self.next_attempt = now + RETRY_S

    def run_forever(self):
        while True:
            try:
                self.tick()
            except Exception:
                log(f'supervisor error: {traceback.format_exc()}')
            time.sleep(1)

    # -- public state
    def status(self):
        state = self.controller_state()
        if state == 'connected':
            public = 'connected'
        elif self.mode == 'pairing' and state in ('connecting', 'initializing'):
            public = 'pairing'
        elif state in ('reconnecting', 'initializing'):
            public = 'reconnecting'
        else:
            public = 'disconnected'
        out = {
            'success': True,
            'state': public,
            'nxbt_state': state,
            'mode': self.mode,
            'switch_address': self.switch_address if public == 'connected' else None,
            'bonded_switches': self.bonded_switches(),
            'adapter': ADAPTER,
            'adapter_address': adapter_address(),
            'last_error': self.last_error,
        }
        if public == 'pairing' and self.pair_until:
            out['pair_window_remaining_s'] = max(0, int(self.pair_until - time.time()))
        audio = adapter_audio_profiles()
        if audio:
            out['warning'] = f'audio profiles registered on the adapter: {", ".join(audio)}'
        return out

    def request_pair(self):
        with self.lock:
            self.pair_requested = True
        return {'success': True, 'state': 'pairing',
                'message': 'Pairing mode: open Controllers -> Change Grip/Order on the Switch'}

    # -- input
    def _require_connected(self):
        if self.controller_state() != 'connected':
            st = self.status()
            hint = ('pairing mode: open Controllers -> Change Grip/Order on the Switch'
                    if st['state'] == 'pairing' else
                    'Switch not connected: wake the Switch, or open Controllers -> '
                    'Change Grip/Order and press Pair')
            raise ConnectionError(hint)
        return self.idx

    def _macro(self, macro, timeout_s):
        idx = self._require_connected()
        macro_id = self.nx.macro(idx, macro, block=False)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if macro_id in self.nx.state[idx]['finished_macros']:
                    return
            except Exception:
                raise ConnectionError('Switch disconnected during the input')
            time.sleep(1 / 120)
        raise TimeoutError('input did not complete in time')

    @staticmethod
    def _button(name):
        b = BUTTONS.get(str(name).strip().lower())
        if not b:
            raise ValueError(f'unknown button {name!r}; known: {sorted(BUTTONS)}')
        return b

    def press(self, button, hold_ms=100):
        b = self._button(button)
        hold = max(20, int(hold_ms)) / 1000
        self._macro(f'{b} {hold:.3f}s\n0.050s', timeout_s=hold + 5)

    def sequence(self, buttons, hold_ms=100, gap_ms=150):
        hold = max(20, int(hold_ms)) / 1000
        gap = max(20, int(gap_ms)) / 1000
        lines = [f'{self._button(b)} {hold:.3f}s\n{gap:.3f}s' for b in buttons]
        self._macro('\n'.join(lines), timeout_s=len(lines) * (hold + gap) + 5)

    def stick(self, stick, direction=None, x=None, y=None, duration_ms=200):
        side = str(stick).strip().lower()
        if side in ('left', 'l'):
            name = 'L_STICK'
        elif side in ('right', 'r'):
            name = 'R_STICK'
        else:
            raise ValueError("stick must be 'left' or 'right'")
        if direction is not None:
            if direction not in STICK_DIRECTIONS:
                raise ValueError(f'direction must be one of {sorted(STICK_DIRECTIONS)}')
            x, y = STICK_DIRECTIONS[direction]
        x = max(-100, min(100, int(x or 0)))
        y = max(-100, min(100, int(y or 0)))
        dur = max(20, int(duration_ms)) / 1000
        xs = f'+{x:03}' if x >= 0 else f'{x:04}'
        ys = f'+{y:03}' if y >= 0 else f'{y:04}'
        self._macro(f'{name}@{xs}{ys} {dur:.3f}s\n0.050s', timeout_s=dur + 5)

    def hold(self, buttons):
        idx = self._require_connected()
        packet = self.nx.create_input_packet()
        for b in buttons:
            key = self._button(b)
            if key == 'L_STICK_PRESS':
                packet['L_STICK']['PRESSED'] = True
            elif key == 'R_STICK_PRESS':
                packet['R_STICK']['PRESSED'] = True
            else:
                packet[key] = True
        self.nx.set_controller_input(idx, packet)
        self.held = list(buttons)

    def release(self):
        idx = self._require_connected()
        self.nx.set_controller_input(idx, self.nx.create_input_packet())
        self.held = None


PROCON = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        if not TOKEN:
            return True
        if hmac.compare_digest(self.headers.get('X-Procon-Token', ''), TOKEN):
            return True
        self._send(401, {'success': False, 'error': 'vpt-procon: missing or wrong X-Procon-Token'})
        return False

    def do_GET(self):
        if not self._authorized():
            return
        if self.path.split('?')[0] == '/status':
            return self._send(200, PROCON.status())
        self._send(404, {'success': False, 'error': 'not found'})

    def do_POST(self):
        if not self._authorized():
            return
        path = self.path.split('?')[0]
        try:
            length = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(length) or b'{}') if length else {}
            if path == '/pair':
                return self._send(200, PROCON.request_pair())
            if path == '/press':
                PROCON.press(body['button'], body.get('hold_ms', 100))
            elif path == '/sequence':
                PROCON.sequence(body['buttons'], body.get('hold_ms', 100), body.get('gap_ms', 150))
            elif path == '/stick':
                PROCON.stick(body['stick'], body.get('direction'), body.get('x'), body.get('y'),
                             body.get('duration_ms', 200))
            elif path == '/hold':
                PROCON.hold(body['buttons'])
            elif path == '/release':
                PROCON.release()
            else:
                return self._send(404, {'success': False, 'error': 'not found'})
            self._send(200, {'success': True})
        except ConnectionError as e:
            self._send(409, {'success': False, 'error': str(e), 'state': PROCON.status()['state']})
        except (KeyError, ValueError, TypeError) as e:
            self._send(400, {'success': False, 'error': f'bad request: {e}'})
        except Exception as e:
            self._send(500, {'success': False, 'error': str(e)})


def main():
    global PROCON
    if os.geteuid() != 0:
        sys.exit('vpt-procon must run as root (raw L2CAP HID sockets, hciconfig, btmgmt)')
    if BIND not in ('127.0.0.1', 'localhost', '::1') and not TOKEN:
        sys.exit(f'vpt-procon: PROCON_BIND={BIND} needs PROCON_TOKEN (the API would be open to the LAN)')
    log(f'starting: adapter={ADAPTER} mac={ADAPTER_MAC or "(unchanged)"} '
        f'listen={BIND}:{PORT} token={"set" if TOKEN else "none"}')
    ensure_adapter()
    # nxbt forks its manager process here; start the GLib/D-Bus thread only after.
    PROCON = Procon()
    start_dbus_side()
    threading.Thread(target=PROCON.run_forever, daemon=True, name='supervisor').start()
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    log(f'API on http://{BIND}:{PORT}')
    server.serve_forever()


if __name__ == '__main__':
    main()
