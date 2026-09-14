"""
Bluetooth (BLE HID) Remote Controller Implementation

Wraps the standalone BLE HID remote daemon at
`backend_host/src/controllers/remote/bluetooth/` (hid_remote.py + start.sh +
resume.sh + vpt-ble-remote.service + bluez CCCD-persistence patch). The daemon
is documented in `bluetooth/bluetooth.md`; this controller is the thin
adapter that brings it into the VirtualPyTest controller framework so it
can be configured per-device via .env, instantiated by controller_manager,
and driven over the polymorphic /host/remote/executeCommand HTTP route.

Key surface for the rest of the host process:

  press_key(key)           — write key name to /tmp/hid_remote.fifo
  start_pairing()          — generate fresh MAC, run start.sh (destructive)
  resume()                 — run resume.sh (non-destructive, preserve bond)
  get_pairing_status()     — D-Bus query of bonded peer + systemctl probe
  execute_command(cmd, p)  — dispatcher for the four above + HTTP route hook

Privilege model: start.sh / resume.sh require root (btmgmt + systemctl +
systemd-run). The controller invokes them via `sudo -n`; host1 must have
a NOPASSWD sudoers entry for these specific scripts (see
setup/local/linux/backend_host/sudoers.d/ble-remote). The FIFO write and
D-Bus reads do NOT need root. systemctl is-active reads also do not.
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import threading
import time
from ..base_controller import RemoteControllerInterface


BLUEZ = 'org.bluez'
DEVICE_IFACE = 'org.bluez.Device1'
PROPS_IFACE = 'org.freedesktop.DBus.Properties'
OM_IFACE = 'org.freedesktop.DBus.ObjectManager'

# NOTE: self.fifo_path, self.status_path, self.hid_remote_unit and the
# corresponding hid-agent unit name are now PER-ADAPTER instance
# attributes (see __init__). The module-level constants are retained only
# as documentation of the naming convention.
#
#   /tmp/hid_remote-<hci>.fifo            ← daemon's key-input FIFO
#   /tmp/hid_remote_status-<hci>.json     ← daemon's StartNotify status
#   hid-remote-<hci>.service              ← daemon systemd unit
#   hid-agent-<hci>.service               ← BlueZ-agent systemd unit
#
# Multi-instance support added 2026-05-29 — see §6.7.22-followup-6.


class BluetoothRemoteController(RemoteControllerInterface):
    """BLE HID remote controller backed by the bluetooth/ daemon stack."""

    @staticmethod
    def get_remote_config() -> Dict[str, Any]:
        """Load frontend layout config (image, button overlays, key labels).

        Mirrors `IRRemoteController.get_remote_config()`; the JSON lives at
        `backend_host/src/config/remote/bluetooth_remote.json`.
        """
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'config', 'remote', 'bluetooth_remote.json',
        )
        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"Bluetooth remote config file not found at: {config_path}")
        try:
            print(f"Loading Bluetooth remote config from: {config_path}")
            with open(config_path, 'r') as config_file:
                return json.load(config_file)
        except Exception as e:
            raise RuntimeError(
                f"Error loading Bluetooth remote config from file: {e}")

    def __init__(self,
                 adapter_hci: str = 'hci0',
                 ble_type: str = 'arris',
                 **kwargs):
        """
        Args:
            adapter_hci: BlueZ adapter name (e.g. 'hci0'). The MGMT/btmgmt
                         numeric index is always the digit suffix of this
                         string (hci0 → 0, hci3 → 3) so we don't carry it
                         as a separate parameter.
            ble_type:    Profile name under bluetooth/ble_conf/ — selects
                         the key-name → HID code map. Currently only
                         'arris' is shipped.

        The scripts directory is hardcoded to the location of this file's
        sibling `bluetooth/` subpackage. The daemon, profiles, and shell
        launchers all live in git at
        `backend_host/src/controllers/remote/bluetooth/` and are deployed
        to the same path on the host via `update_core.sh`. There is no
        out-of-tree install path; making it configurable would invite
        the deployed copy and the source copy to drift.
        """
        super().__init__("BLE Remote", "bluetooth")

        self.adapter_hci = adapter_hci
        self.ble_type = ble_type
        self._pairing_in_progress = False
        # True while start.sh OR resume.sh is running in the background.
        # start.sh/resume.sh intentionally STOP the hid-remote daemon early
        # to reconfigure the adapter (power-off → MAC spoof → raw-HCI adv,
        # ~10s) and relaunch it near the end. Exposed in get_pairing_status
        # as `script_running` so the frontend doesn't misread that expected
        # daemon-down window as a crash ("hid-remote service exited during
        # pairing"). See BLUETOOTH.md §6.7.23-followup-3.
        self._script_running = False
        self.scripts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'bluetooth')

        # Per-adapter daemon resources (multi-instance, §6.7.22-followup-6).
        # Must mirror the paths/names produced by start.sh, resume.sh, and
        # hid_remote.py for this adapter — if any of these four sources
        # drifts, press_key writes to a FIFO no daemon is reading.
        self.fifo_path = f'/tmp/hid_remote-{adapter_hci}.fifo'
        self.status_path = f'/tmp/hid_remote_status-{adapter_hci}.json'
        # Persistent template units (hid-remote@hciN / hid-agent@hciN),
        # replacing the old transient hid-remote-hciN units that start.sh/
        # resume.sh launched via `systemd-run`. See BLUETOOTH.md §6.7.25.
        self.hid_remote_unit = f'hid-remote@{adapter_hci}.service'
        self.hid_agent_unit = f'hid-agent@{adapter_hci}.service'
        self.boot_resume_unit = f'vpt-ble-remote@{adapter_hci}.service'

        # Load the keymap so press_key can validate names before forwarding
        # to the FIFO. We deliberately mirror the JSON the daemon loads —
        # if they ever drift the daemon's _load_keymap will fail loudly at
        # restart.
        self.keymap_path = os.path.join(
            self.scripts_dir, 'ble_conf', f'{ble_type}.json')
        self.supported_keys: List[str] = []
        self._load_keymap()

        print(f"[@controller:BluetoothRemote] Initialized "
              f"adapter={self.adapter_hci} profile={self.ble_type} "
              f"scripts_dir={self.scripts_dir}")

        # Auto-connect — the IR controller does the same.
        self.connect()

    # ---------- Lifecycle --------------------------------------------------

    def connect(self) -> bool:
        """Make sure the BLE daemon is up; do not touch the bond.

        If hid-remote.service is already active (e.g. vpt-ble-remote.service
        ran resume.sh on boot), this is a no-op. If not, run resume.sh
        once. We never invoke start.sh from connect() — that would wipe
        the existing bond. Use start_pairing() explicitly for fresh pairs.
        """
        try:
            if self._daemon_active():
                print(f"Remote[{self.device_type.upper()}]: "
                      f"hid-remote already active, skipping resume")
            else:
                print(f"Remote[{self.device_type.upper()}]: "
                      f"hid-remote inactive — launching resume.sh in background")
                threading.Thread(target=self._run_script,
                                 args=('resume.sh',), daemon=True).start()
            self.is_connected = True
            print(f"Remote[{self.device_type.upper()}]: "
                  f"Connected ({len(self.supported_keys)} keys loaded)")
            return True
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: connect() error: {e}")
            return False

    def disconnect(self) -> bool:
        """Mark the controller disconnected without touching hid-remote.

        vpt-ble-remote.service owns the daemon's lifecycle and we want it
        running across host process restarts so the STB stays paired.
        Tearing it down here would defeat the §6.7.11 auto-resume design.
        """
        self.is_connected = False
        return True

    # ---------- Command dispatch ------------------------------------------

    def execute_command(self, command: str,
                        params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Dispatcher for the polymorphic /host/remote/executeCommand route."""
        if params is None:
            params = {}
        # Skip log line for read-only polling commands (get_pairing_status,
        # get_logs, ...) — they fire every 1-5s and drown out real actions.
        if not command.startswith('get_'):
            print(f"Remote[{self.device_type.upper()}]: "
                  f"Executing command '{command}' with params: {params}")

        if command == 'press_key':
            key = params.get('key')
            success = self.press_key(key) if key else False
            return {'success': success}
        if command == 'start_pairing':
            return self.start_pairing()
        if command == 'resume':
            return self.resume()
        if command == 'wake':
            return self.wake()
        if command == 'cold_wake':
            return self.cold_wake()
        if command == 'get_pairing_status':
            return {'success': True, 'status': self.get_pairing_status()}
        if command == 'get_logs':
            n = int(params.get('lines', 200))
            since = params.get('since')
            return {'success': True, 'logs': self.get_logs(n, since=since)}
        print(f"Remote[{self.device_type.upper()}]: Unknown command: {command}")
        return {'success': False, 'error': f'unknown command: {command}'}

    # ---------- press_key --------------------------------------------------

    def press_key(self, key: str) -> bool:
        """Send a key press by writing the key name to hid-remote's FIFO.

        The daemon's fifo_reader_thread parses each line via parse_key()
        and emits press + release notifications on both the HID Input
        Report (0x2a4d) and Arris vendor notify (2141e101) channels. If
        no peer is currently connected, hid_remote.py's wake_on_press()
        will trigger ADV_DIRECT_IND and reconnect transparently before
        sending the key (§ 6.7.10).
        """
        if not self.is_connected:
            print(f"Remote[{self.device_type.upper()}]: "
                  f"ERROR - controller not connected")
            return False
        if not key:
            return False
        key_upper = key.upper()
        if key_upper not in self.supported_keys:
            print(f"Remote[{self.device_type.upper()}]: "
                  f"Key '{key_upper}' not in profile '{self.ble_type}'")
            return False
        try:
            with open(self.fifo_path, 'w') as fifo:
                fifo.write(key_upper + '\n')
            print(f"Remote[{self.device_type.upper()}]: Sent {key_upper}")
            return True
        except FileNotFoundError:
            print(f"Remote[{self.device_type.upper()}]: "
                  f"FIFO {self.fifo_path} missing — daemon may be down")
            return False
        except BrokenPipeError:
            print(f"Remote[{self.device_type.upper()}]: "
                  f"FIFO {self.fifo_path} has no reader — daemon may be restarting")
            return False
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: "
                  f"FIFO write failed: {e}")
            return False

    # ---------- Wake --------------------------------------------------------

    def wake(self) -> Dict[str, Any]:
        """Proactively wake a standby STB by writing the WAKE sentinel to
        the daemon FIFO. The daemon's fifo_reader_thread parses WAKE as
        "trigger wake_on_press() without sending a key" — it emits
        ADV_DIRECT_IND at the bonded STB's MAC for up to WAKE_TIMEOUT_S,
        then returns. No-op if no peer is bonded or if a peer is already
        connected.

        The write is non-blocking from the caller's perspective: wake
        happens in the daemon thread, and the controller returns
        immediately. The frontend polls get_pairing_status to observe
        connected=true once the STB reconnects.
        """
        if not self.is_connected:
            return {'success': False, 'error': 'controller not connected'}
        try:
            with open(self.fifo_path, 'w') as fifo:
                fifo.write('WAKE\n')
            print(f"Remote[{self.device_type.upper()}]: Sent WAKE sentinel")
            return {'success': True}
        except FileNotFoundError:
            return {'success': False,
                    'error': f'FIFO {self.fifo_path} missing — daemon may be down'}
        except BrokenPipeError:
            return {'success': False,
                    'error': f'FIFO {self.fifo_path} has no reader — daemon may be restarting'}
        except Exception as e:
            return {'success': False, 'error': f'FIFO write failed: {e}'}

    def cold_wake(self) -> Dict[str, Any]:
        """Wake a box from deep/COLD standby (S2/S3) by writing the COLD_WAKE
        sentinel to the daemon FIFO. The daemon broadcasts the Broadcom WoBLE
        pattern (undirected ADV_IND with manufacturer data 0x000F + "WAKEUP")
        to trip the sleeping BT chip's packet filter, then restores the
        identity advert and waits for the host to reconnect — see
        cold_wake_on_press() in hid_remote.py.

        This is the user-driven POWER-from-standby path: the active-standby
        wake() (ADV_DIRECT_IND) cannot reach a box whose host CPU is off.
        Non-blocking from the caller's perspective; the frontend polls
        get_pairing_status to observe connected=true once the STB wakes.
        """
        if not self.is_connected:
            return {'success': False, 'error': 'controller not connected'}
        try:
            with open(self.fifo_path, 'w') as fifo:
                fifo.write('COLD_WAKE\n')
            print(f"Remote[{self.device_type.upper()}]: Sent COLD_WAKE sentinel")
            return {'success': True}
        except FileNotFoundError:
            return {'success': False,
                    'error': f'FIFO {self.fifo_path} missing — daemon may be down'}
        except BrokenPipeError:
            return {'success': False,
                    'error': f'FIFO {self.fifo_path} has no reader — daemon may be restarting'}
        except Exception as e:
            return {'success': False, 'error': f'FIFO write failed: {e}'}

    # ---------- Readiness gate --------------------------------------------

    def wait_for_ready(self, timeout: float = 20.0) -> bool:
        """Block until the BLE link can actually carry key events.

        Called once at script start (script_executor.setup_execution_context)
        so a script never fires its first key while the link is still
        resuming. Two cases this covers that per-press wake_on_press()
        (§ 6.7.10) does not:

          1. Pi-reboot resume — resume.sh runs in the background, the FIFO
             has no reader yet, so an early press_key would BrokenPipe and
             be lost silently.
          2. First-press latency — an idle STB takes up to WAKE_TIMEOUT_S
             (8s) to reconnect on the first press; verifying right after
             that press would read a stale frame.

        Ready means get_pairing_status() reports
        connected && services_resolved && hid_ready. If not connected, we
        send one WAKE sentinel to trigger directed advertising, then poll.
        Returns True once ready; False on timeout (the caller proceeds
        anyway — the daemon's per-press wake is the backstop).
        """
        deadline = time.time() + timeout
        woke = False
        while time.time() < deadline:
            status = self.get_pairing_status()
            if (status.get('connected')
                    and status.get('services_resolved')
                    and status.get('hid_ready')):
                print(f"Remote[{self.device_type.upper()}]: "
                      f"link ready (connected + services + hid)")
                return True
            # Daemon must be up before a WAKE write has a reader. If it's
            # still resuming, just keep polling — connect() already kicked
            # resume.sh.
            if status.get('daemon_active') and not status.get('connected') \
                    and not woke:
                print(f"Remote[{self.device_type.upper()}]: "
                      f"link not connected — sending WAKE before waiting")
                self.wake()
                woke = True
            time.sleep(1.0)
        print(f"Remote[{self.device_type.upper()}]: "
              f"wait_for_ready timed out after {timeout:.0f}s "
              f"— proceeding (per-press wake is the backstop)")
        return False

    # ---------- Pairing flow ----------------------------------------------

    def start_pairing(self) -> Dict[str, Any]:
        """Run start.sh (destructive fresh pair) in a background thread.

        Returns immediately so the HTTP request doesn't block the single
        werkzeug worker (which would freeze HLS streams for ~25s).
        The frontend polls get_pairing_status to track progress.
        """
        if self._pairing_in_progress:
            return {'success': False,
                    'error': 'Pairing already in progress'}
        self._clear_pairing_lock()
        self._pairing_in_progress = True
        print(f"Remote[{self.device_type.upper()}]: "
              f"Starting pairing in background (start.sh will auto-pick MAC)")

        self._script_running = True

        def _run():
            try:
                ok, out = self._run_script('start.sh')
                if not ok:
                    print(f"Remote[{self.device_type.upper()}]: "
                          f"start.sh failed: {out[-400:] if out else '(no output)'}")
            except Exception as e:
                print(f"Remote[{self.device_type.upper()}]: "
                      f"start.sh exception: {e}")
            finally:
                self._pairing_in_progress = False
                self._script_running = False

        threading.Thread(target=_run, daemon=True).start()
        return {'success': True, 'output': 'start.sh launched in background'}

    def resume(self) -> Dict[str, Any]:
        """Run resume.sh (non-destructive, preserves the bond) in background."""
        self._script_running = True

        def _run():
            try:
                ok, out = self._run_script('resume.sh')
                if not ok:
                    print(f"Remote[{self.device_type.upper()}]: "
                          f"resume.sh failed: {out[-400:] if out else ''}")
            except Exception as e:
                print(f"Remote[{self.device_type.upper()}]: "
                      f"resume.sh exception: {e}")
            finally:
                self._script_running = False

        threading.Thread(target=_run, daemon=True).start()
        return {'success': True, 'output': 'resume.sh launched in background'}

    # ---------- Status -----------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Controller status (mirrors IRRemoteController.get_status())."""
        return {
            'success': True,
            'controller_type': self.controller_type,
            'device_type': self.device_type,
            'device_name': self.device_name,
            'adapter_hci': self.adapter_hci,
            'ble_type': self.ble_type,
            'connected': self.is_connected,
            'supported_keys': self.supported_keys,
            'pairing_status': self.get_pairing_status(),
            'capabilities': [
                'ble_hid', 'wake_on_press', 'auto_resume',
                'navigation', 'media_control', 'volume_control',
            ],
        }

    def get_pairing_status(self) -> Dict[str, Any]:
        """Report the live pairing/connection state for the bonded STB.

        Combines three signals:
          - systemctl is-active hid-remote.service (daemon up?)
          - D-Bus org.bluez.Device1 props: Paired/Connected/Trusted/ServicesResolved
          - /tmp/hid_remote_status.json: hid_ready (Arris vendor StartNotify fired?)

        hid_ready is the critical signal: when False but connected=True,
        the STB reconnected via a cached bond and only subscribed to
        Battery — keys are silently dropped (battery-only trap, § 6.7.9).
        The frontend uses this to show a degraded state instead of green.

        bond_present is derived from D-Bus: bluetoothd loads bonds from
        /var/lib/bluetooth at startup and exposes them as Device1 objects
        under /org/bluez/<adapter>/dev_*, so any Device1 that exists with
        Bonded=true OR Paired=true is proof of a bond on disk. We
        deliberately do NOT stat /var/lib/bluetooth because that
        directory is mode 0700 root-owned and would force every status
        poll through sudo.

        Used by the frontend useBluetoothRemote hook every 2 s. Must be
        cheap and non-blocking — no subprocess >1 s, no shell scripts.
        """
        daemon_up = self._daemon_active()
        status = {
            'daemon_active': daemon_up,
            'script_running': bool(self._script_running),
            'advertising': daemon_up and self._agent_active(),
            'adapter_mac': self._adapter_address(),
            'bond_present': False,
            'stb_mac': None,
            'paired': False,
            'connected': False,
            'trusted': False,
            'services_resolved': False,
            'hid_ready': False,
            'bond_count': 0,
        }

        peer = self._query_dbus_peer_state()
        if peer:
            status.update(peer)
            status['bond_present'] = True
            # Fallback pickers (busctl/bluetoothctl) return a single peer
            # without a count; a returned peer is at least one bond.
            status['bond_count'] = peer.get('bond_count', 1)
            if status['bond_count'] > 1:
                print(f"Remote[{self.device_type.upper()}]: WARNING "
                      f"{status['bond_count']} bonds on {self.adapter_hci} — "
                      f"stale bond(s) present; keys may drop until removed "
                      f"(§6.7.20)")

        # Primary source: daemon's StartNotify tracker.
        status['hid_ready'] = self._read_hid_ready()

        # Fallback: on bonded reconnects, BlueZ silently restores the CCCD
        # state from /var/lib/bluetooth/.../info [Cccs] and does NOT fire
        # the server-side StartNotify callback. The data path works — keys
        # flow — but _read_hid_ready() stays False, falsely flagging the
        # remote as degraded. When we're bonded+connected and the bond
        # file has HID Report (0x2a4d) CCCD=0x0001, trust that as proof
        # of a live HID subscription.
        if (not status['hid_ready']
                and status.get('bond_present')
                and status.get('connected')
                and status.get('stb_mac')
                and status.get('adapter_mac')):
            if self._bond_has_hid_cccd(status['adapter_mac'], status['stb_mac']):
                status['hid_ready'] = True

        return status

    def get_logs(self, lines: int = 200,
                 since: str = None) -> Dict[str, Any]:
        """Return BLE daemon log lines plus live connection state.

        When *since* is provided (ISO-8601 or journalctl-friendly
        timestamp like '2026-04-16 10:41:00'), only entries after that
        moment are returned — letting the frontend show "logs since I
        clicked Start Pairing" instead of the full history.

        Each unit's output is also stripped of systemd transient-file
        noise lines ("Failed to open /run/systemd/transient/…") which
        are harmless race artifacts from Restart=always on transient
        units but confuse operators reading the debug panel.
        """
        units = [self.hid_remote_unit, self.hid_agent_unit, self.boot_resume_unit]
        out: Dict[str, Any] = {}
        for unit in units:
            try:
                cmd = ['sudo', '-n', 'journalctl', '-u', unit,
                       '--no-pager', '--output=short']
                if since:
                    try:
                        utc_dt = datetime.fromisoformat(
                            since.replace('Z', '+00:00'))
                        local_dt = utc_dt.astimezone()
                        ts = local_dt.strftime('%Y-%m-%d %H:%M:%S')
                    except (ValueError, TypeError):
                        ts = since.replace('T', ' ').replace('Z', '')
                        if '.' in ts:
                            ts = ts[:ts.index('.')]
                    cmd += ['--since', ts]
                else:
                    cmd += ['-n', str(lines)]
                r = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=5)
                raw = (r.stdout or '') + (r.stderr or '')
                cleaned = '\n'.join(
                    line for line in raw.splitlines()
                    if 'Failed to open /run/systemd/transient/' not in line
                )
                out[unit] = cleaned
            except Exception as e:
                out[unit] = f'error: {e}'
        out['pairing_status'] = self.get_pairing_status()
        return out

    def get_available_actions(self) -> Dict[str, Any]:
        """List supported keys as action objects, grouped by category.

        Matches IRRemoteController.get_available_actions() exactly:
        returns `{'remote': [action_dict, ...]}` where Device.get_available_actions()
        iterates values as lists and extends them. Returning anything
        else (e.g. a flat dict with scalar values) raises
        "'bool' object is not iterable" one level up.
        """
        actions = [
            {
                'id': f'ble_press_key_{name.lower()}',
                'label': name,
                'command': 'press_key',
                'action_type': 'remote',
                'params': {'key': name},
                'description': f'Press {name} via BLE HID',
                'requiresInput': False,
            }
            for name in self.supported_keys
        ]
        # Cold-standby wake (Broadcom WoBLE). Exposed like a key so it can be
        # placed on an edge / called from a script to wake a box whose host
        # CPU is off (deep/eco standby), where a plain POWER HID press can't
        # reach it. See cold_wake() / cold_wake_on_press() in hid_remote.py.
        actions.append({
            'id': 'ble_cold_wake',
            'label': 'COLD_WAKE',
            'command': 'cold_wake',
            'action_type': 'remote',
            'params': {},
            'description': 'Wake the STB from deep/cold standby via Broadcom WoBLE '
                           '(undirected 0x000F/"WAKEUP" advert)',
            'requiresInput': False,
        })
        return {'remote': actions}

    # ---------- Internals --------------------------------------------------

    def _load_keymap(self) -> None:
        """Load supported_keys from the JSON profile.

        We only need the key names here (the actual HID codes are mapped
        inside hid_remote.py). Validating against this list lets press_key
        reject typos without burning a FIFO write + subprocess wakeup.
        """
        try:
            with open(self.keymap_path, 'r') as f:
                raw = json.load(f)
            self.supported_keys = sorted(
                k.upper() for k in raw.keys() if not k.startswith('_'))
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: "
                  f"WARNING — failed to load keymap {self.keymap_path}: {e}")
            self.supported_keys = []

    def _daemon_active(self) -> bool:
        """systemctl is-active hid-remote.service — fast, no shell."""
        try:
            r = subprocess.run(
                ['systemctl', 'is-active', self.hid_remote_unit],
                capture_output=True, text=True, timeout=2)
            return r.returncode == 0
        except Exception:
            return False

    def _agent_active(self) -> bool:
        try:
            r = subprocess.run(
                ['systemctl', 'is-active', self.hid_agent_unit],
                capture_output=True, text=True, timeout=2)
            return r.returncode == 0
        except Exception:
            return False

    def _adapter_address(self) -> Optional[str]:
        """Read the adapter's current BD_ADDR via hciconfig.

        Faster and simpler than a D-Bus property read. Returns None on
        failure rather than raising — the caller treats absent address
        as "no bond can be loaded yet".
        """
        try:
            r = subprocess.run(
                ['hciconfig', self.adapter_hci],
                capture_output=True, text=True, timeout=2)
            if r.returncode != 0:
                return None
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith('BD Address:'):
                    return line.split()[2]
        except Exception:
            pass
        return None

    def _read_hid_ready(self) -> bool:
        """Read hid_ready from the daemon's status file.

        hid_remote.py writes /tmp/hid_remote_status.json with
        {"hid_ready": bool, "subscribed_uuids": [...], "ts": float}
        every time a StartNotify/StopNotify fires or the peer disconnects.
        A simple file read — no subprocess, no D-Bus.
        """
        try:
            with open(self.status_path, 'r') as f:
                data = json.load(f)
            return bool(data.get('hid_ready', False))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return False

    _HID_REPORT_UUID = '00002a4d-0000-1000-8000-00805f9b34fb'
    # Class-level so the "D-Bus unavailable, using busctl fallback" warning
    # only prints once per process, not on every get_pairing_status poll.
    _dbus_warning_printed = False

    def _bond_has_hid_cccd(self, adapter_mac: str, stb_mac: str) -> bool:
        """Return True if the persisted bond's [Cccs] has HID Report=0x0001.

        /var/lib/bluetooth/<adapter>/<peer>/info contains the bond BlueZ
        writes on pair + on any CCCD change. When a bonded peer
        reconnects, BlueZ restores notifications from this file without
        firing server-side StartNotify. Reading it lets the controller
        tell "the STB is subscribed to HID" even though the daemon never
        got a live callback.

        /var/lib/bluetooth is 0700 root, so this runs via a narrow
        sudo -n cat allowlist (see setup/local/linux/backend_host/
        sudoers.d/ble-remote).

        Returns False on any error — callers should treat a False as "we
        don't know, don't override", not as "definitely not subscribed".
        """
        path = f'/var/lib/bluetooth/{adapter_mac}/{stb_mac}/info'
        try:
            r = subprocess.run(
                ['sudo', '-n', 'cat', path],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode != 0:
                return False
        except Exception:
            return False

        in_cccs = False
        for raw_line in r.stdout.splitlines():
            line = raw_line.strip()
            if line.startswith('['):
                in_cccs = (line == '[Cccs]')
                continue
            if not in_cccs or '=' not in line:
                continue
            # Format: <svc_uuid>:<chr_uuid>=0xNNNN
            key, _, value = line.partition('=')
            if self._HID_REPORT_UUID not in key.lower():
                continue
            try:
                cccd = int(value.strip(), 0)
            except ValueError:
                continue
            # Bit 0 = notifications, bit 1 = indications. Either counts.
            if cccd & 0x0003:
                return True
        return False

    def _query_dbus_peer_state(self) -> Optional[Dict[str, Any]]:
        """Read Paired/Connected/Trusted/ServicesResolved for our STB peer.

        Walks every Device1 under /org/bluez/<adapter_hci>/ and prefers
        a peer with Connected=true; falls back to the first bonded/paired
        peer if none are connected. The "prefer Connected" rule matters
        when the adapter ends up with more than one bond (e.g. an
        STB-side factory-reset re-pairing without us re-running start.sh,
        which leaves the prior bond loaded forever). Without it, the
        first peer in lexicographic D-Bus order wins, which can be the
        long-dead one — the panel then sticks on "STB disconnected"
        forever even though a sibling bond is live.
        Returns None if no bonded peer is loaded by bluetoothd.
        """
        try:
            import dbus
            bus = dbus.SystemBus()
            om = dbus.Interface(bus.get_object(BLUEZ, '/'), OM_IFACE)
            wanted_prefix = f'/org/bluez/{self.adapter_hci}/dev_'
            candidates: List[Dict[str, Any]] = []
            for path, ifaces in om.GetManagedObjects().items():
                if not str(path).startswith(wanted_prefix):
                    continue
                dev = ifaces.get(DEVICE_IFACE)
                if not dev:
                    continue
                if not bool(dev.get('Bonded', False)) and \
                        not bool(dev.get('Paired', False)):
                    continue
                candidates.append({
                    'paired': bool(dev.get('Paired', False)),
                    'connected': bool(dev.get('Connected', False)),
                    'trusted': bool(dev.get('Trusted', False)),
                    'services_resolved': bool(dev.get('ServicesResolved', False)),
                    'stb_mac': str(dev.get('Address')) if dev.get('Address') else None,
                })
            if candidates:
                chosen = next((c for c in candidates if c['connected']), candidates[0])
                # Surface the multi-bond hazard (§6.7.20): more than one bond on
                # the adapter means a stale bond is present, which makes the
                # daemon's wake-on-press cross-check the wrong peer and reset the
                # live link on every keypress. The operator should remove the
                # stale bond(s); the frontend can warn on bond_count > 1.
                chosen = dict(chosen)
                chosen['bond_count'] = len(candidates)
                return chosen
        except Exception as e:
            # Print the fallback notice ONCE per process. The dbus import
            # fails the same way on every poll (~1-5s), so on the Minisforum
            # (no python3-dbus installed) this used to spam journalctl with
            # ~12 lines/minute. Cache the warning on the class.
            if not BluetoothRemoteController._dbus_warning_printed:
                print(f"Remote[{self.device_type.upper()}]: "
                      f"D-Bus unavailable ({e}), using busctl fallback")
                BluetoothRemoteController._dbus_warning_printed = True

        # Prefer `busctl` (available without dbus-python) because it
        # exposes the full Device1 property set including
        # ServicesResolved, which `bluetoothctl info` never prints.
        via_busctl = self._query_busctl_peer_state()
        if via_busctl is not None:
            return via_busctl
        return self._query_bluetoothctl_peer_state()

    def _query_busctl_peer_state(self) -> Optional[Dict[str, Any]]:
        """Scoped D-Bus probe via `busctl` (no dbus-python needed).

        Walks ``/org/bluez/<adapter_hci>/dev_*`` via ObjectManager,
        collects every bonded/paired Device1, then prefers Connected=true
        (see ``_query_dbus_peer_state`` for why). Returns ``None`` on
        parse failure so the caller can fall through to bluetoothctl.
        """
        try:
            om = subprocess.run(
                ['busctl', '--no-pager', 'call', 'org.bluez', '/',
                 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects'],
                capture_output=True, text=True, timeout=3)
            if om.returncode != 0:
                return None
            prefix = f'/org/bluez/{self.adapter_hci}/dev_'
            device_paths = []
            for m in re.finditer(
                    r'"(' + re.escape(prefix) + r'[A-F0-9_]{17})"', om.stdout):
                device_paths.append(m.group(1))
            if not device_paths:
                return None
            candidates: List[Dict[str, Any]] = []
            for dev_path in device_paths:
                props = subprocess.run(
                    ['busctl', '--no-pager', 'get-property', 'org.bluez',
                     dev_path, 'org.bluez.Device1',
                     'Paired', 'Connected', 'Trusted',
                     'ServicesResolved', 'Bonded', 'Address'],
                    capture_output=True, text=True, timeout=3)
                if props.returncode != 0:
                    continue
                # Each line is `<type> <value>`; booleans render as
                # `b true` / `b false`, strings as `s "AA:BB:..."`.
                lines = [l.strip() for l in props.stdout.splitlines() if l.strip()]
                if len(lines) < 6:
                    continue
                def _b(s: str) -> bool:
                    return s.endswith(' true')
                def _s(s: str) -> str:
                    m = re.search(r'"([^"]*)"', s)
                    return m.group(1) if m else ''
                paired = _b(lines[0])
                connected = _b(lines[1])
                trusted = _b(lines[2])
                services_resolved = _b(lines[3])
                bonded = _b(lines[4])
                address = _s(lines[5])
                if not (paired or bonded):
                    continue
                candidates.append({
                    'paired': paired,
                    'connected': connected,
                    'trusted': trusted,
                    'services_resolved': services_resolved,
                    'stb_mac': address or None,
                })
            if not candidates:
                return None
            return next((c for c in candidates if c['connected']), candidates[0])
        except Exception:
            return None

    def _query_bluetoothctl_peer_state(self) -> Optional[Dict[str, Any]]:
        """Fallback for _query_dbus_peer_state using bluetoothctl.

        Scoped to the peripheral's adapter (``self.adapter_hci``, from
        ``DEVICE{N}_BLE_ADAPTER_HCI`` in the .env) so hosts with multiple
        BT radios — e.g. one hci per STB, or a second dongle used for
        reverse-engineering — always return the bond under the right
        adapter. Without this scoping, ``bluetoothctl devices Paired``
        lists devices for whatever adapter bluetoothctl last selected,
        which has no relationship to this controller's device.

        Like the dbus/busctl pickers, prefers a Connected=true peer over
        the first one listed (see ``_query_dbus_peer_state``).
        """
        try:
            # Resolve the per-device adapter's MAC.
            hcicfg = subprocess.run(
                ['hciconfig', self.adapter_hci],
                capture_output=True, text=True, timeout=2)
            adapter_mac = None
            if hcicfg.returncode == 0:
                m = re.search(r'BD Address:\s*([0-9A-Fa-f:]{17})',
                              hcicfg.stdout)
                if m:
                    adapter_mac = m.group(1)
            if not adapter_mac:
                # Can't scope reliably — refuse rather than return the
                # wrong bond. Upstream get_pairing_status handles None.
                return None

            # One-shot bluetoothctl script: select our adapter, list its
            # paired devices, exit. `select` is session-scoped so it has
            # to happen in the same invocation as `devices Paired`.
            result = subprocess.run(
                ['bluetoothctl'],
                input=f'select {adapter_mac}\ndevices Paired\nquit\n',
                capture_output=True, text=True, timeout=3)
            if result.returncode != 0:
                return None
            # bluetoothctl emits ANSI colour codes + prompt prefixes, so
            # 'startswith("Device ")' doesn't work. Extract every MAC
            # that appears after a "Device " token regardless of what
            # precedes it on the line.
            candidate_macs: List[str] = []
            for m in re.finditer(
                    r'Device\s+([0-9A-Fa-f:]{17})', result.stdout):
                candidate = m.group(1).upper()
                if candidate == adapter_mac.upper():
                    continue  # the adapter itself
                if candidate.startswith('20:21:41:'):
                    continue  # UEI OUI — our peripheral spoofs or the
                              # real physical remote (never the STB)
                candidate_macs.append(candidate)
            if not candidate_macs:
                return None

            candidates: List[Dict[str, Any]] = []
            for mac in candidate_macs:
                info_result = subprocess.run(
                    ['bluetoothctl'],
                    input=f'select {adapter_mac}\ninfo {mac}\nquit\n',
                    capture_output=True, text=True, timeout=3)
                if info_result.returncode != 0:
                    continue
                lines = info_result.stdout
                candidates.append({
                    'paired': 'Paired: yes' in lines,
                    'connected': 'Connected: yes' in lines,
                    'trusted': 'Trusted: yes' in lines,
                    'services_resolved': 'ServicesResolved: yes' in lines,
                    'stb_mac': mac,
                })
            if not candidates:
                return None
            return next((c for c in candidates if c['connected']), candidates[0])
        except Exception:
            return None

    def _clear_pairing_lock(self):
        # Per-adapter lockfile path (must match start.sh's
        # `/tmp/ble-remote-pairing-${ADAPTER_HCI}.lock`). The earlier
        # global path served only one adapter per host; on multi-adapter
        # hosts (host3 has hci1 + hci2) this controller has to
        # only clear its own adapter's lock, not the sibling's.
        lock = f'/tmp/ble-remote-pairing-{self.adapter_hci}.lock'
        try:
            os.unlink(lock)
        except (FileNotFoundError, PermissionError):
            pass

    def _run_script(self, script_name: str,
                    extra_env: Dict[str, str] = None) -> Tuple[bool, str]:
        """Run start.sh / resume.sh under sudo with the right env vars.

        Returns (ok, combined_stdout_stderr). 60s timeout — start.sh
        completes in ~15s on a TTY (measured); if it takes longer when
        invoked from the controller, that's a real bug to investigate (not
        paper over with a longer wait). The TimeoutExpired branch captures
        whatever the script printed before the timer fired so we can see
        which step was slow.
        """
        script_path = os.path.join(self.scripts_dir, script_name)
        if not os.path.isfile(script_path):
            return False, f'script not found: {script_path}'

        # Best-effort: ensure the +x bit is set before `sudo -n -E <path>`
        # execs it. Prod deploys to the Minisforum have landed start.sh/
        # resume.sh without the execute mode (git tracks them 100755, so it's
        # the on-host deploy copy stripping it), which makes this exec fail
        # with permission denied until someone re-chmods by hand. We own the
        # files under the /opt deploy, so restore the mode here; if we don't
        # own them the chmod no-ops and we proceed (they may already be +x).
        # The boot unit ble-remote@.service sidesteps this entirely by going
        # through `bash <script>`; this covers the UI Pair/Resume path, whose
        # pinned sudoers rule requires the exact script path (not `bash …`).
        try:
            mode = os.stat(script_path).st_mode
            if not (mode & 0o111):
                os.chmod(script_path, mode | 0o755)
        except OSError:
            pass

        env = os.environ.copy()
        env['ADAPTER_HCI'] = self.adapter_hci
        env['BLE_TYPE'] = self.ble_type
        if extra_env:
            env.update(extra_env)

        # Use `sudo -E` so the env vars actually propagate; the sudoers
        # entry must allow this (NOPASSWD: SETENV: <script>).
        cmd = ['sudo', '-n', '-E', script_path]

        # Dump the exact env we're about to invoke under so the same run
        # can be reproduced manually outside Flask. The Flask-vs-shell
        # divergence (gunicorn worker's minimal env vs the user's login
        # shell env) is the usual reason this script behaves differently
        # when invoked from the controller. The dump path is per-script
        # so start.sh and resume.sh debugs don't overwrite each other.
        env_dump = f'/tmp/ble-{script_name.replace(".sh", "")}-env.list'
        try:
            with open(env_dump, 'w') as f:
                for k, v in sorted(env.items()):
                    f.write(f"{k}={v}\n")
        except OSError:
            pass

        invoking_user = (env.get('USER')
                         or env.get('LOGNAME')
                         or 'vpt_user')
        repro_cmd = (
            f"sudo -u {invoking_user} env -i "
            f"$(cat {env_dump} | xargs -d '\\n') "
            f"sudo -n -E {script_path}"
        )
        print(f"Remote[{self.device_type.upper()}]: "
              f"invoking {script_name} as {invoking_user} "
              f"(adapter={env.get('ADAPTER_HCI')}, ble_type={env.get('BLE_TYPE')})")
        print(f"Remote[{self.device_type.upper()}]: "
              f"reproduce manually: {repro_cmd}")

        try:
            # start_new_session=True: detach from gunicorn's process group
            #   so any SIGHUP/SIGINT in the worker doesn't take down the
            #   in-flight script mid-MGMT-call (which would leave the
            #   radio in a half-configured state).
            # NOTE: do NOT pass stdin here (neither DEVNULL nor a PIPE).
            # On the bluetoothd 5.82 build (Debian 13), `btmgmt` WEDGES
            # (blocks until killed, rc=124) when its stdin is /dev/null —
            # and gunicorn's own stdin is /dev/null (systemd StandardInput=
            # null), so inheriting it would wedge every btmgmt the script
            # runs (verified 2026-06-01). The script fixes this itself:
            # start.sh/resume.sh do `exec < <(:)` at the top to force their
            # stdin to a pipe regardless of launcher (see BLUETOOTH.md
            # §6.7.23 stdin wedge). We must NOT pass input=/stdin=PIPE here
            # either — the script's `exec` reassigns fd0 and a write from
            # this side would then hit BrokenPipe. Leave stdin inherited and
            # let the script self-heal. (An earlier note claimed closing
            # stdin only "blanked btmgmt output"; the real symptom is a hard
            # hang, and the MGMT-enumeration wait did not fix it.)
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60, env=env,
                start_new_session=True)
            output = (r.stdout or '') + (r.stderr or '')
            print(f"Remote[{self.device_type.upper()}]: "
                  f"{script_name} rc={r.returncode}")
            if r.stdout:
                print(f"Remote[{self.device_type.upper()}]: "
                      f"stdout (last 400): {r.stdout[-400:]}")
            if r.stderr:
                print(f"Remote[{self.device_type.upper()}]: "
                      f"stderr (last 400): {r.stderr[-400:]}")
            return r.returncode == 0, output
        except subprocess.TimeoutExpired as e:
            # Surface whatever the script printed before the timeout fired —
            # without this the frontend just sees "timed out after 60s"
            # with no clue what step was slow. `capture_output=True` causes
            # TimeoutExpired to carry the partial stdout/stderr.
            partial_stdout = (e.stdout or '') if isinstance(e.stdout, str) else (e.stdout.decode(errors='replace') if e.stdout else '')
            partial_stderr = (e.stderr or '') if isinstance(e.stderr, str) else (e.stderr.decode(errors='replace') if e.stderr else '')
            print(f"Remote[{self.device_type.upper()}]: "
                  f"{script_name} timed out after 60s")
            if partial_stdout:
                print(f"Remote[{self.device_type.upper()}]: "
                      f"stdout before timeout (last 600): {partial_stdout[-600:]}")
            if partial_stderr:
                print(f"Remote[{self.device_type.upper()}]: "
                      f"stderr before timeout (last 600): {partial_stderr[-600:]}")
            return False, f'{script_name} timed out after 60s\n{partial_stdout}{partial_stderr}'
        except Exception as e:
            return False, f'{script_name} exception: {e}'
