"""
features/mobile-app/backend_host/bridge.py — PhoneBridge: the in-process state
machine for every `phone_agent` slot on this host (docs/tasks/TASK-17-mobile-app-
phone-agent.md §1.1-§1.3). Owns the DEVICEn_* slot list built from env, pairing
tokens, live Socket.IO sessions, the frame writer, and the request/ack RPC that
PhoneAgentRemoteController uses instead of ADB.

One PhoneBridge per host process — created once from backend_host/__init__.py via
the module-level get_bridge() singleton, so REST routes and Socket.IO handlers
(registered separately, both from __init__.py) always see the same slot state.
"""
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from . import placeholder
from ..lib import protocol

_LOG = '[@mobile-app:bridge]'
# Shown while the phone is connected but sending no frames.
IDLE_SUBTITLE = 'not streaming - allow screen capture on the phone'
# How long frames must have been absent before the idle placeholder replaces the last one.
# Comfortably longer than a status tick, so a client that simply omits `capture_active`
# (phone_sim does) is judged on whether frames are arriving rather than on a missing field.
IDLE_FRAME_GRACE_S = 20.0


class _Slot:
    """Mutable state for one phone_agent device slot (one DEVICEn_MODEL=phone_agent)."""

    def __init__(self, device_id: str, device_name: str, frame_path: str, capture_path: Optional[str]):
        self.device_id = device_id
        self.original_name = device_name  # the .env slot label; restored on unpair
        self.frame_path = frame_path
        self.capture_path = capture_path
        self.device_secret: Optional[str] = None
        self.pending_token: Optional[str] = None
        self.pending_token_expiry: float = 0.0
        self.sid: Optional[str] = None  # bound Socket.IO session id while the phone is live
        self.phone: Optional[Dict[str, Any]] = None  # {manufacturer, model, android, screen}
        self.status: Dict[str, Any] = {}
        self.last_seen: Optional[float] = None
        self.fps: float = 0.0
        self.cmd_lock = threading.Lock()  # socketio.call() is not thread-safe per client (see flask-socketio docs)
        self._offline_timer: Optional[threading.Timer] = None
        # True while the idle placeholder is the thing on disk, so it is written once rather
        # than on every status tick, and cleared as soon as a real frame lands.
        self.idle_placeholder: bool = False
        self.last_frame_at: Optional[float] = None

    @property
    def state(self) -> str:
        if self.sid:
            return 'connected'
        if self.pending_token and self.pending_token_expiry > time.time():
            return 'pending'
        if self.device_secret:
            return 'offline'
        return 'free'

    def summary(self) -> Dict[str, Any]:
        return {
            'device_id': self.device_id,
            'device_name': self.original_name,
            'state': self.state,
            'phone': self.phone,
            'last_seen': self.last_seen,
            'fps': self.fps,
            # Whether frames are actually ARRIVING, which `fps` does not say: that is the rate
            # the host asked the phone for (PHONE_AGENT_FPS), fixed at capture start and
            # unchanged when a phone stops sending. A phone whose screen-capture consent was
            # dropped — every app upgrade drops it — stays connected and answers commands while
            # producing nothing, and the last frame it ever sent keeps being served. Same rule
            # the idle placeholder uses, so the two can never disagree.
            'streaming': bool(self.status.get('capture_active'))
            and (time.time() - (self.last_frame_at or 0.0)) <= IDLE_FRAME_GRACE_S,
            # For RemoteBridgeClient: a script subprocess runs on this same machine, so
            # it reads the latest frame off disk instead of pulling it through the API.
            'frame_path': self.frame_path,
            # …and writes its UI-dump traces beside the device's captures.
            'capture_path': self.capture_path,
        }


class PhoneBridge:
    """Slots + pairing + live sessions + frame writer + RPC for this host's phone_agent devices."""

    def __init__(self, app, socketio=None):
        self.app = app
        self.socketio = socketio
        self._lock = threading.RLock()
        self.fps = _env_int('PHONE_AGENT_FPS', protocol.DEFAULT_FPS)
        self.max_side = _env_int('PHONE_AGENT_MAX_SIDE', protocol.DEFAULT_MAX_SIDE)
        self.quality = protocol.DEFAULT_QUALITY
        self.slots: Dict[str, _Slot] = _build_slots_from_env()
        self.state_file = _resolve_state_file(self.slots)
        # source IP -> {'count', 'window_start', 'locked_until'} for handle_hello's lockout.
        self._hello_failures: Dict[str, Dict[str, float]] = {}
        self._load_state()
        self._bootstrap_placeholders()
        print(f"{_LOG} {len(self.slots)} phone_agent slot(s): {sorted(self.slots)} "
              f"fps={self.fps} max_side={self.max_side} state_file={self.state_file}")

    # ---- slot lookups -------------------------------------------------------

    def get_slot(self, device_id: str) -> Optional[_Slot]:
        return self.slots.get(device_id)

    def slot_by_sid(self, sid: str) -> Optional[_Slot]:
        with self._lock:
            for slot in self.slots.values():
                if slot.sid == sid:
                    return slot
        return None

    def list_slots(self) -> List[Dict[str, Any]]:
        return [s.summary() for s in self.slots.values()]

    # ---- pairing --------------------------------------------------------

    def create_pairing(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Mint a one-time token for `device_id`, replacing any still-pending one."""
        slot = self.slots.get(device_id)
        if not slot:
            return None
        token = secrets.token_urlsafe(32)
        expiry = time.time() + protocol.TOKEN_TTL_S
        with self._lock:
            slot.pending_token = token
            slot.pending_token_expiry = expiry
        print(f"{_LOG} {device_id}: new pairing token (expires in {protocol.TOKEN_TTL_S}s)")
        return {'token': token, 'expires_at': _iso(expiry)}

    def unpair(self, device_id: str) -> bool:
        slot = self.slots.get(device_id)
        if not slot:
            return False
        with self._lock:
            sid = slot.sid
            slot.pending_token = None
            slot.pending_token_expiry = 0.0
            slot.device_secret = None
            slot.phone = None
            slot.status = {}
            slot.sid = None
            self._cancel_offline_timer(slot)
        self._save_state()
        if sid and self.socketio:
            try:
                self.socketio.emit(protocol.EV_UNPAIR, {}, to=sid, namespace=protocol.NAMESPACE)
            except Exception as e:
                print(f"{_LOG} {device_id}: unpair emit failed: {e}")
            self._disconnect_sid(sid)
        self._restore_device_name(slot)
        self._write_placeholder(slot, offline=False)
        print(f"{_LOG} {device_id}: unpaired")
        return True

    # ---- Socket.IO event handlers (invoked by backend_host/__init__.py) -------

    def handle_hello(self, sid: str, payload: Dict[str, Any], client_ip: str = '') -> Dict[str, Any]:
        payload = payload or {}
        token = payload.get('token')
        device_secret = payload.get('device_secret')
        device_info = payload.get('device') or {}

        locked_for = self._hello_locked_for(client_ip)
        if locked_for is not None:
            return {'ok': False, 'error': f'too many failed attempts, retry in {locked_for:.0f}s'}

        with self._lock:
            slot = None
            if token:
                slot = next((s for s in self.slots.values()
                             if s.pending_token == token and s.pending_token_expiry > time.time()), None)
                if not slot:
                    self._record_hello_failure(client_ip)
                    return {'ok': False, 'error': 'invalid or expired token'}
            elif device_secret:
                slot = next((s for s in self.slots.values() if s.device_secret == device_secret), None)
                if not slot:
                    self._record_hello_failure(client_ip)
                    return {'ok': False, 'error': 'invalid device_secret'}
            else:
                self._record_hello_failure(client_ip)
                return {'ok': False, 'error': 'token or device_secret required'}

            # A fresh hello replaces whatever session currently holds the slot (phone
            # reconnected on a new socket, or a re-pair happened over an old session).
            old_sid = slot.sid if slot.sid and slot.sid != sid else None
            slot.device_secret = secrets.token_urlsafe(32)  # rotate on every successful hello
            slot.pending_token = None
            slot.pending_token_expiry = 0.0
            slot.sid = sid
            slot.phone = {
                'manufacturer': device_info.get('manufacturer', ''),
                'model': device_info.get('model', ''),
                'android': device_info.get('android', ''),
                'screen': device_info.get('screen') or {},
            }
            slot.last_seen = time.time()
            slot.fps = self.fps
            self._cancel_offline_timer(slot)

        self._reset_hello_failures(client_ip)
        self._save_state()
        self._rename_device(slot)
        if old_sid:
            self._disconnect_sid(old_sid)

        capture = {'fps': self.fps, 'max_side': self.max_side, 'quality': self.quality}
        if self.socketio:
            try:
                self.socketio.emit(protocol.EV_CAPTURE, capture, to=sid, namespace=protocol.NAMESPACE)
            except Exception as e:
                print(f"{_LOG} {slot.device_id}: capture emit failed: {e}")

        print(f"{_LOG} {slot.device_id}: paired ({slot.phone.get('manufacturer')} {slot.phone.get('model')})")
        return {'ok': True, 'device_id': slot.device_id, 'device_secret': slot.device_secret, 'capture': capture}

    def handle_frame(self, sid: str, meta: Dict[str, Any], jpeg_bytes: bytes) -> None:
        slot = self.slot_by_sid(sid)
        if not slot or not jpeg_bytes:
            return
        try:
            tmp_path = f'{slot.frame_path}.tmp'
            with open(tmp_path, 'wb') as fh:
                fh.write(jpeg_bytes)
            os.replace(tmp_path, slot.frame_path)
        except OSError as e:
            print(f"{_LOG} {slot.device_id}: frame write failed: {e}")
            return
        slot.idle_placeholder = False
        slot.last_frame_at = time.time()
        slot.last_seen = time.time()

    def handle_status(self, sid: str, payload: Dict[str, Any]) -> None:
        slot = self.slot_by_sid(sid)
        if not slot:
            return
        slot.status = payload or {}
        slot.last_seen = time.time()
        # A phone can be connected and still send nothing — screen-capture consent is not
        # granted, or capture stopped. Until now the last frame it ever sent stayed on disk
        # and kept being served, so a phone that had stopped capturing looked exactly like one
        # that was streaming: a frozen picture with nothing to say it was frozen, which is
        # worse than an empty panel. Say so instead; the next real frame overwrites it.
        if slot.status.get('capture_active'):
            return
        frames_stopped = time.time() - (slot.last_frame_at or 0.0) > IDLE_FRAME_GRACE_S
        if frames_stopped and not slot.idle_placeholder:
            print(f"{_LOG} {slot.device_id}: no frames and capture inactive - showing placeholder")
            self._write_placeholder(slot, offline=False, subtitle=IDLE_SUBTITLE)
            slot.idle_placeholder = True

    def handle_disconnect(self, sid: str) -> None:
        slot = self.slot_by_sid(sid)
        if not slot:
            return
        with self._lock:
            slot.sid = None
        print(f"{_LOG} {slot.device_id}: disconnected, offline placeholder in "
              f"{protocol.OFFLINE_PLACEHOLDER_DELAY_S}s unless it reconnects")
        self._schedule_offline_placeholder(slot)

    # ---- RPC used by PhoneAgentRemoteController -----------------------------

    def rpc(self, device_id: str, name: str, params: Optional[Dict[str, Any]] = None,
            timeout: Optional[float] = None) -> Dict[str, Any]:
        slot = self.slots.get(device_id)
        if not slot or not slot.sid:
            return {'ok': False, 'error': 'phone not connected'}
        if not self.socketio:
            return {'ok': False, 'error': 'socketio not available on this host'}

        timeout = timeout or (protocol.CMD_TIMEOUT_SLOW_S if protocol.is_slow_command(name) else protocol.CMD_TIMEOUT_S)
        cmd_payload = {'id': str(uuid.uuid4()), 'name': name, 'params': params or {}}

        with slot.cmd_lock:
            try:
                ack = self._call(protocol.EV_CMD, cmd_payload, slot.sid, timeout)
            except Exception as e:
                print(f"{_LOG} {device_id}: cmd '{name}' failed: {e}")
                return {'ok': False, 'error': str(e)}

        if not isinstance(ack, dict):
            return {'ok': False, 'error': f"malformed ack for '{name}': {ack!r}"}
        return ack

    def _call(self, event: str, payload: Dict[str, Any], sid: str, timeout: float) -> Any:
        # Prefer flask_socketio's built-in call() (Flask-SocketIO >= 5.3; confirmed
        # present in the pinned 5.5.1) — it works under gevent (host, Linux) and
        # threading (this Mac, no gevent installed - see TASK-17 W1 final report)
        # without any code difference. Fall back to a manual emit()+callback+Event
        # for an older flask-socketio that predates call().
        if hasattr(self.socketio, 'call'):
            return self.socketio.call(event, payload, namespace=protocol.NAMESPACE, to=sid, timeout=timeout)

        done = threading.Event()
        box: Dict[str, Any] = {}

        def _ack(*args):
            box['result'] = args[0] if args else None
            done.set()

        self.socketio.emit(event, payload, to=sid, namespace=protocol.NAMESPACE, callback=_ack)
        if not done.wait(timeout):
            raise TimeoutError(f'{event} timed out after {timeout}s')
        return box.get('result')

    # ---- hello rate limiting (TASK-19 P0 #2) ----------------------------

    def _hello_locked_for(self, client_ip: str) -> Optional[float]:
        """Seconds left in a lockout for `client_ip`, or None if it may try now."""
        if not client_ip:
            return None
        with self._lock:
            entry = self._hello_failures.get(client_ip)
            if not entry:
                return None
            remaining = entry['locked_until'] - time.time()
            return remaining if remaining > 0 else None

    def _record_hello_failure(self, client_ip: str) -> None:
        if not client_ip:
            return
        now = time.time()
        with self._lock:
            entry = self._hello_failures.get(client_ip)
            if not entry or now - entry['window_start'] > protocol.HELLO_FAILURE_WINDOW_S:
                entry = {'count': 0, 'window_start': now, 'locked_until': 0.0}
            entry['count'] += 1
            if entry['count'] >= protocol.HELLO_MAX_FAILURES:
                entry['locked_until'] = now + protocol.HELLO_LOCKOUT_S
                print(f"{_LOG} {client_ip}: locked out for {protocol.HELLO_LOCKOUT_S}s "
                      f"after {entry['count']} failed hello attempts")
            self._hello_failures[client_ip] = entry

    def _reset_hello_failures(self, client_ip: str) -> None:
        if not client_ip:
            return
        with self._lock:
            self._hello_failures.pop(client_ip, None)

    # ---- internals -----------------------------------------------------

    def _rename_device(self, slot: _Slot) -> None:
        # app.host_devices is populated by backend_host/src/app.py Step 2.5, which
        # runs AFTER register(app) (Step 3) but BEFORE any phone can actually pair
        # (that needs a running server) — so by the time hello fires, it's there.
        devices = getattr(self.app, 'host_devices', None) or {}
        device = devices.get(slot.device_id)
        if device is None or not slot.phone:
            return
        manufacturer = (slot.phone.get('manufacturer') or '').strip()
        model = (slot.phone.get('model') or '').strip()
        device.device_name = f'{manufacturer} {model}'.strip() or slot.original_name

    def _restore_device_name(self, slot: _Slot) -> None:
        devices = getattr(self.app, 'host_devices', None) or {}
        device = devices.get(slot.device_id)
        if device is not None:
            device.device_name = slot.original_name

    def _disconnect_sid(self, sid: str) -> None:
        if not self.socketio:
            return
        try:
            self.socketio.server.disconnect(sid, namespace=protocol.NAMESPACE)
        except Exception as e:
            print(f"{_LOG} disconnect({sid}) failed: {e}")

    def _schedule_offline_placeholder(self, slot: _Slot) -> None:
        self._cancel_offline_timer(slot)

        def _fire():
            if slot.sid:  # reconnected meanwhile - nothing to do
                return
            self._write_placeholder(slot, offline=True)

        timer = threading.Timer(protocol.OFFLINE_PLACEHOLDER_DELAY_S, _fire)
        timer.daemon = True
        slot._offline_timer = timer
        timer.start()

    def _cancel_offline_timer(self, slot: _Slot) -> None:
        if slot._offline_timer:
            slot._offline_timer.cancel()
            slot._offline_timer = None

    def _bootstrap_placeholders(self) -> None:
        for slot in self.slots.values():
            fresh = False
            try:
                fresh = (time.time() - os.path.getmtime(slot.frame_path)) < 5
            except OSError:
                fresh = False
            if not fresh:
                self._write_placeholder(slot, offline=False)

    def _write_placeholder(self, slot: _Slot, offline: bool, subtitle: Optional[str] = None) -> None:
        if subtitle is None:
            subtitle = 'phone offline' if offline else 'not paired - scan QR in Settings'
        try:
            placeholder.render_placeholder(slot.frame_path, slot.original_name, subtitle)
        except Exception as e:
            print(f"{_LOG} {slot.device_id}: placeholder render failed: {e}")

    def _load_state(self) -> None:
        if not self.state_file or not os.path.isfile(self.state_file):
            return
        try:
            with open(self.state_file, encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            print(f"{_LOG} could not read state file {self.state_file}: {e}")
            return
        for device_id, saved in (data or {}).items():
            slot = self.slots.get(device_id)
            if not slot:
                continue
            slot.device_secret = saved.get('device_secret')
            slot.phone = saved.get('phone')

    def _save_state(self) -> None:
        if not self.state_file:
            return
        data = {
            device_id: {'device_secret': slot.device_secret, 'phone': slot.phone}
            for device_id, slot in self.slots.items() if slot.device_secret
        }
        try:
            directory = os.path.dirname(self.state_file) or '.'
            os.makedirs(directory, exist_ok=True)
            tmp_path = f'{self.state_file}.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as fh:
                json.dump(data, fh)
            os.replace(tmp_path, self.state_file)
        except OSError as e:
            print(f"{_LOG} could not write state file {self.state_file}: {e}")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _iso(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat().replace('+00:00', 'Z')


def _build_slots_from_env() -> Dict[str, _Slot]:
    """Every DEVICEi where MODEL (before the first '-platform' dash) == phone_agent
    (matches controller_manager._get_devices_config_from_environment's own
    raw_model.partition('-') parsing, so a variant tag like `phone_agent-pixel8`
    still selects the slot)."""
    slots: Dict[str, _Slot] = {}
    for i in range(1, 13):
        name = os.getenv(f'DEVICE{i}_NAME')
        if not name:
            continue
        raw_model = os.getenv(f'DEVICE{i}_MODEL', '')
        model = raw_model.partition('-')[0]
        if model != protocol.DEVICE_MODEL:
            continue
        frame_path = os.getenv(f'DEVICE{i}_VIDEO')
        if not frame_path or os.path.splitext(frame_path)[1].lower() not in ('.jpg', '.jpeg', '.png'):
            print(f"{_LOG} device{i} ({name}) is phone_agent but DEVICE{i}_VIDEO is missing or not .jpg/.png - skipped")
            continue
        capture_path = os.getenv(f'DEVICE{i}_VIDEO_CAPTURE_PATH')
        device_id = f'device{i}'
        os.makedirs(os.path.dirname(frame_path) or '.', exist_ok=True)
        slots[device_id] = _Slot(device_id, name, frame_path, capture_path)
    return slots


def _resolve_state_file(slots: Dict[str, _Slot]) -> str:
    configured = os.getenv('PHONE_AGENT_STATE_FILE')
    if configured:
        candidate = configured
    elif slots:
        first_frame_dir = os.path.dirname(next(iter(slots.values())).frame_path)
        candidate = os.path.normpath(os.path.join(first_frame_dir, '..', 'state.json'))
    else:
        candidate = os.path.join(tempfile.gettempdir(), 'mobile-app-phone-state.json')

    directory = os.path.dirname(candidate) or '.'
    try:
        os.makedirs(directory, exist_ok=True)
        probe = os.path.join(directory, f'.write_test_{os.getpid()}')
        with open(probe, 'w') as fh:
            fh.write('')
        os.remove(probe)
        return candidate
    except OSError:
        fallback = os.path.join(tempfile.gettempdir(), 'mobile-app-phone-state.json')
        print(f"{_LOG} state dir {directory} unwritable, falling back to {fallback}")
        return fallback


_bridge_instance: Optional[PhoneBridge] = None
_bridge_lock = threading.Lock()


def get_bridge(app=None, socketio=None) -> PhoneBridge:
    """Module-level singleton accessor. The first call (from register(app)) must
    pass `app`; later calls (route handlers, the controller factory) just return
    the existing instance."""
    global _bridge_instance
    with _bridge_lock:
        if _bridge_instance is None:
            if app is None:
                raise RuntimeError('get_bridge() called before the bridge was created (register(app) has not run yet)')
            _bridge_instance = PhoneBridge(app, socketio)
        return _bridge_instance
