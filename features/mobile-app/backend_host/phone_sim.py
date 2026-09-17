#!/usr/bin/env python3
"""
features/mobile-app/backend_host/phone_sim.py — FAKE PHONE.

A python-socketio client that speaks the same wire protocol the Android app will
speak (features/mobile-app/lib/protocol.py, docs/tasks/TASK-17-mobile-app-phone-
agent.md §1.3): it pairs with a one-time token or a saved device_secret, streams
JPEG frames at N fps, and answers every cmd in protocol.ALL_COMMANDS. Used by
tests/backend_host/test_mobile_app_bridge.py and by host-clone-1 acceptance runs
that don't have a real APK yet (TASK-17 §6 step 4).

This file doubles as a standalone script and as an importable module
(`PhoneSim`), so it cannot rely on the package-relative import the rest of
features/mobile-app/backend_host uses (`from ..lib import protocol`) - run
directly with `python3 phone_sim.py`, this module has no parent package. Instead
it puts the project root on sys.path and reaches protocol.py the same way the
task doc requires everywhere the hyphenated `mobile-app` folder name makes a
normal `import` statement illegal: importlib.import_module().

Usage:
    python3 phone_sim.py --qr '<json pairing payload from the web UI>' [--image path.png] [--fps 3]
    python3 phone_sim.py --token <token> --host-url http://host:6109 [--device-id device2]
    python3 phone_sim.py --device-secret <secret> --host-url http://host:6109
"""
import argparse
import base64
import io
import json
import os
import sys
import threading
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, '..', '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import importlib  # noqa: E402
protocol = importlib.import_module('features.mobile-app.lib.protocol')  # noqa: E402

import socketio as sio_client  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

_LOG = '[@mobile-app:phone_sim]'


class PhoneSim:
    """Fake phone: connects, pairs, streams frames, answers commands."""

    def __init__(self, host_url: str, token: str = None, device_secret: str = None,
                 image: str = None, fps: float = None, socketio_path: str = None,
                 manufacturer: str = 'VPT', model: str = 'PhoneSim', android: str = '14',
                 device_id: str = None):
        self.host_url = host_url.rstrip('/')
        self.token = token
        self.device_secret = device_secret
        self.image_path = image
        self.fps = fps or protocol.DEFAULT_FPS
        self.socketio_path = socketio_path or 'socket.io'
        self.manufacturer = manufacturer
        self.model = model
        self.android = android
        # Only a hint for the logs before the hello ack lands: the host resolves the
        # slot from the token/secret and its answer overwrites this (see _on_hello_ack).
        self.device_id = device_id

        self.sio = sio_client.Client(reconnection=False)
        self._img = None
        self._img_lock = threading.Lock()
        self._stream_stop = threading.Event()
        self._stream_thread = None
        self._connected_event = threading.Event()
        self._hello_ack = {}
        self._register_handlers()

    # ---- lifecycle -------------------------------------------------------

    def start(self, wait_connected: float = 8.0) -> dict:
        """Connect and wait for the hello ack (not just the transport handshake).
        Raises RuntimeError both when the ack never arrives and when it arrives
        with ok:false (the host also disconnects us in that case)."""
        self._connected_event.clear()
        self.sio.connect(
            self.host_url, namespaces=[protocol.NAMESPACE],
            socketio_path=self.socketio_path, wait_timeout=wait_connected,
            # A reverse proxy in front of the host (Cloudflare) rejects the default
            # python-requests / websocket-client agents with 403; look like the app.
            headers={'User-Agent': 'Mozilla/5.0 (VirtualPyTest phone_sim)'},
        )
        acked = self._connected_event.wait(wait_connected)
        if not acked or not self._hello_ack.get('ok'):
            try:
                self.sio.disconnect()
            except Exception:
                pass
            if not acked:
                raise RuntimeError(f'phone_sim: hello not acknowledged within {wait_connected}s')
            raise RuntimeError(f"phone_sim: hello rejected: {self._hello_ack.get('error')}")
        return self._hello_ack

    def stop(self) -> None:
        self._stop_streaming()
        try:
            if self.sio.connected:
                self.sio.disconnect()
        except Exception:
            pass

    # ---- Socket.IO handlers ------------------------------------------------

    def _register_handlers(self) -> None:
        sio = self.sio

        @sio.on('connect', namespace=protocol.NAMESPACE)
        def _on_connect():
            print(f'{_LOG} transport connected, sending hello')
            self._send_hello()

        @sio.on('connect_error', namespace=protocol.NAMESPACE)
        def _on_connect_error(data):
            print(f'{_LOG} connect_error: {data}')

        @sio.on('disconnect', namespace=protocol.NAMESPACE)
        def _on_disconnect():
            print(f'{_LOG} disconnected')
            self._connected_event.clear()
            self._stop_streaming()

        @sio.on(protocol.EV_CAPTURE, namespace=protocol.NAMESPACE)
        def _on_capture(payload):
            fps = (payload or {}).get('fps', self.fps)
            if fps and fps > 0:
                self.fps = fps
                self._start_streaming()
            else:
                self._stop_streaming()

        @sio.on(protocol.EV_CMD, namespace=protocol.NAMESPACE)
        def _on_cmd(payload):
            return self._handle_cmd(payload or {})

        @sio.on(protocol.EV_UNPAIR, namespace=protocol.NAMESPACE)
        def _on_unpair(_payload=None):
            print(f'{_LOG} unpaired by host')
            self.device_secret = None
            self._stop_streaming()

    def _send_hello(self) -> None:
        w, h = self._image_size()
        device = {
            'manufacturer': self.manufacturer, 'model': self.model, 'android': self.android,
            'app_version': '0.0.0-sim',
            'screen': {'w': w, 'h': h, 'density': 3.0},
        }
        payload = {'v': protocol.PROTOCOL_VERSION, 'device': device}
        if self.device_secret:
            payload['device_secret'] = self.device_secret
        elif self.token:
            payload['token'] = self.token
        else:
            raise ValueError('phone_sim needs a token or a device_secret to say hello')

        def _ack(ack):
            self._hello_ack = ack or {}
            if ack and ack.get('ok'):
                self.device_secret = ack.get('device_secret')
                self.device_id = ack.get('device_id')
                print(f"{_LOG} paired as {self.device_id}")
            else:
                print(f'{_LOG} hello rejected: {ack}')
            self._connected_event.set()  # set on both outcomes - start() inspects _hello_ack['ok']

        self.sio.emit(protocol.EV_HELLO, payload, namespace=protocol.NAMESPACE, callback=_ack)

    # ---- image / frame -----------------------------------------------------

    def _load_image(self) -> Image.Image:
        if self.image_path and os.path.isfile(self.image_path):
            return Image.open(self.image_path).convert('RGB')
        img = Image.new('RGB', (1080, 2400), (32, 96, 160))
        draw = ImageDraw.Draw(img)
        draw.text((40, 40), 'phone_sim', fill=(255, 255, 255))
        return img

    def _image_size(self):
        with self._img_lock:
            if self._img is None:
                self._img = self._load_image()
            return self._img.size

    def _draw_marker(self, x: int, y: int, label: str = '') -> None:
        with self._img_lock:
            if self._img is None:
                self._img = self._load_image()
            draw = ImageDraw.Draw(self._img)
            r = 18
            draw.ellipse([x - r, y - r, x + r, y + r], outline=(255, 60, 60), width=4)
            if label:
                draw.text((x + r + 4, y - r), label, fill=(255, 60, 60))

    def _start_streaming(self) -> None:
        self._stop_streaming()
        self._stream_stop.clear()

        def _loop():
            max_side = protocol.DEFAULT_MAX_SIDE
            while not self._stream_stop.is_set():
                with self._img_lock:
                    if self._img is None:
                        self._img = self._load_image()
                    frame = self._img.copy()
                frame.thumbnail((max_side, max_side))
                buf = io.BytesIO()
                frame.save(buf, 'JPEG', quality=protocol.DEFAULT_QUALITY)
                meta = {'ts': time.time(), 'w': frame.width, 'h': frame.height, 'rotation': 0}
                try:
                    self.sio.emit(protocol.EV_FRAME, (meta, buf.getvalue()), namespace=protocol.NAMESPACE)
                except Exception:
                    break
                self._stream_stop.wait(1.0 / max(self.fps, 0.1))

        self._stream_thread = threading.Thread(target=_loop, daemon=True)
        self._stream_thread.start()

    def _stop_streaming(self) -> None:
        self._stream_stop.set()
        if self._stream_thread:
            self._stream_thread.join(timeout=2)
        self._stream_thread = None

    # ---- command handling ------------------------------------------------

    def _handle_cmd(self, payload: dict) -> dict:
        name = payload.get('name')
        params = payload.get('params') or {}
        try:
            if name == protocol.CMD_TAP:
                self._draw_marker(int(params.get('x', 0)), int(params.get('y', 0)), 'tap')
                return {'ok': True}

            if name == protocol.CMD_SWIPE:
                self._draw_marker(int(params.get('x2', params.get('x1', 0))),
                                   int(params.get('y2', params.get('y1', 0))), 'swipe')
                return {'ok': True}

            if name == protocol.CMD_KEY:
                key = params.get('key')
                if key not in protocol.AGENT_KEYS:
                    return {'ok': False, 'error': f'unknown key {key}'}
                self._draw_marker(60, 60, key)
                return {'ok': True}

            if name == protocol.CMD_TEXT:
                self._draw_marker(60, 120, (params.get('text') or '')[:12])
                return {'ok': True}

            if name == protocol.CMD_LAUNCH_APP:
                return {'ok': True}

            if name == protocol.CMD_CLOSE_APP:
                return {'ok': True}

            if name == protocol.CMD_LIST_APPS:
                return {'ok': True, 'result': {'apps': [
                    {'package': 'com.android.settings', 'label': 'Settings'},
                    {'package': 'com.android.chrome', 'label': 'Chrome'},
                ]}}

            if name == protocol.CMD_DUMP_UI:
                w, h = self._image_size()
                elements = [
                    {'id': 0, 'text': 'Home', 'content_desc': '', 'class': 'android.widget.TextView',
                     'package': 'com.phonesim', 'bounds': [0, 0, w // 3, 80],
                     'clickable': True, 'enabled': True, 'focused': False},
                    {'id': 1, 'text': '', 'content_desc': 'Search', 'class': 'android.widget.ImageButton',
                     'package': 'com.phonesim', 'bounds': [w - 100, 0, w, 80],
                     'clickable': True, 'enabled': True, 'focused': False},
                    {'id': 2, 'text': 'Settings item', 'content_desc': '', 'class': 'android.widget.TextView',
                     'package': 'com.phonesim', 'bounds': [0, h - 200, w, h - 120],
                     'clickable': True, 'enabled': True, 'focused': False},
                ]
                return {'ok': True, 'result': {'elements': elements}}

            if name == protocol.CMD_SCREENSHOT:
                with self._img_lock:
                    if self._img is None:
                        self._img = self._load_image()
                    frame = self._img.copy()
                buf = io.BytesIO()
                frame.save(buf, 'JPEG', quality=90)
                b64 = base64.b64encode(buf.getvalue()).decode('ascii')
                return {'ok': True, 'result': {'jpeg_b64': b64, 'w': frame.width, 'h': frame.height}}

            if name == protocol.CMD_DEVICE_INFO:
                w, h = self._image_size()
                return {'ok': True, 'result': {
                    'manufacturer': self.manufacturer, 'model': self.model, 'android': self.android,
                    'screen': {'w': w, 'h': h, 'density': 3.0}, 'battery': 87,
                }}

            return {'ok': False, 'error': f'unknown command {name}'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}


def _connect_urls_from_qr(qr: dict):
    """host_api_url (LAN) first, host_url + PROXIED_SOCKETIO_SUFFIX as fallback -
    same order the real app uses (TASK-17 §1.4)."""
    primary = qr.get('host_api_url')
    fallback = qr.get('host_url')
    return primary, fallback


def main() -> int:
    parser = argparse.ArgumentParser(description='Fake phone for features/mobile-app (TASK-17 W1)')
    parser.add_argument('--qr', help='JSON pairing payload, as produced by the web UI (kind=pair)')
    parser.add_argument('--token', help='One-time pairing token (alternative to --qr)')
    parser.add_argument('--device-secret', help='Saved device_secret to reconnect without a token')
    parser.add_argument('--host-url', help='Host base URL (used with --token/--device-secret)')
    parser.add_argument('--device-id', help='Informational only - the slot is resolved by token/secret')
    parser.add_argument('--image', help='Image file to stream instead of the built-in placeholder')
    parser.add_argument('--fps', type=float, default=protocol.DEFAULT_FPS)
    args = parser.parse_args()

    if args.qr:
        qr = json.loads(args.qr)
        primary, fallback = _connect_urls_from_qr(qr)
        attempts = [(primary, 'socket.io')] if primary else []
        if fallback:
            # python-socketio keeps only scheme+host of the URL, so the proxy prefix
            # (/host/<name>) has to travel in socketio_path, exactly like the app does.
            from urllib.parse import urlparse
            prefix = urlparse(fallback).path.rstrip('/')
            attempts.append((fallback, (prefix + protocol.PROXIED_SOCKETIO_SUFFIX).lstrip('/')))
        if not attempts:
            print(f'{_LOG} --qr payload has neither host_api_url nor host_url', file=sys.stderr)
            return 2
        last_err = None
        for host_url, path in attempts:
            sim = PhoneSim(host_url, token=qr.get('token'), image=args.image, fps=args.fps, socketio_path=path)
            try:
                ack = sim.start()
                print(f'{_LOG} paired: {ack}')
                break
            except Exception as e:
                last_err = e
                print(f'{_LOG} connect via {host_url} ({path}) failed: {e}')
        else:
            print(f'{_LOG} all connection attempts failed: {last_err}', file=sys.stderr)
            return 1
    elif args.token or args.device_secret:
        if not args.host_url:
            print(f'{_LOG} --host-url is required with --token/--device-secret', file=sys.stderr)
            return 2
        sim = PhoneSim(args.host_url, token=args.token, device_secret=args.device_secret,
                        image=args.image, fps=args.fps, device_id=args.device_id)
        sim.start()
        print(f'{_LOG} paired as {sim.device_id}, streaming at {sim.fps}fps - Ctrl+C to stop')
    else:
        parser.error('one of --qr, --token, --device-secret is required')
        return 2

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
