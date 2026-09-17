"""
tests/backend_host/test_mobile_app_bridge.py — TASK-17 W1 unit tests for
features/mobile-app/backend_host: pairing, the fake phone (phone_sim.py)
round-tripping frames and commands through PhoneAgentRemoteController, and the
offline/placeholder lifecycle (docs/tasks/TASK-17-mobile-app-phone-agent.md §5,
row W1). No external server and no network beyond localhost: one minimal Flask +
Flask-SocketIO app is booted in-process (threading async_mode - gevent is not
installed on this Mac, see the W1 final report) and driven with PhoneSim exactly
like a real host would be driven by the Android app.

The 8 numbered scenarios from the task doc are one continuous pairing lifecycle
(pair -> connect -> use -> reject -> reconnect -> go offline -> unpair), so the
test functions below share state through the module-scoped `session` fixture and
must run in file order (no randomized-order plugin is installed in this repo -
verified before writing this file).

Run:
    cd <worktree> && PYTHONPATH=. python3 -m pytest tests/backend_host -q
"""
import importlib
import os
import socket
import threading
import time

import pytest
import requests
from flask import Flask
from flask_socketio import SocketIO
from PIL import Image

protocol = importlib.import_module('features.mobile-app.lib.protocol')
mobile_app_backend_host = importlib.import_module('features.mobile-app.backend_host')
phone_sim_module = importlib.import_module('features.mobile-app.backend_host.phone_sim')
bridge_module = importlib.import_module('features.mobile-app.backend_host.bridge')
phone_agent_module = importlib.import_module('features.mobile-app.backend_host.controllers.phone_agent')

PhoneSim = phone_sim_module.PhoneSim
PhoneAgentRemoteController = phone_agent_module.PhoneAgentRemoteController

DEVICE_ID = 'device2'


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class _FakeDevice:
    """Stand-in for shared.src.lib.models.device.Device - only the attribute the
    bridge touches (device_name) is needed to exercise the hello rename path."""

    def __init__(self, device_id, device_name):
        self.device_id = device_id
        self.device_name = device_name


@pytest.fixture(scope='module')
def session(tmp_path_factory):
    """Boots one host process (Flask + Socket.IO) with a single phone_agent slot
    (device2) and registers the mobile-app feature exactly like
    backend_host/src/app.py does at Step 3 (register_host_routes ->
    register_feature_blueprints), minus the DB/env machinery a real host needs.
    """
    tmp_dir = tmp_path_factory.mktemp('mobile_app_phone')
    frame_path = tmp_dir / 'phone_frames' / 'device2' / 'latest.jpg'
    capture_path = tmp_dir / 'capture2'

    env = {
        'DEVICE2_NAME': 'Phone slot 1',
        'DEVICE2_MODEL': 'phone_agent',
        'DEVICE2_VIDEO': str(frame_path),
        'DEVICE2_VIDEO_CAPTURE_PATH': str(capture_path),
        'PHONE_AGENT_FPS': '5',
        'PHONE_AGENT_STATE_FILE': str(tmp_dir / 'state.json'),
        'HOST_NAME': 'test-host',
        'HOST_URL': 'https://vpt.example/host/test-host',
    }
    old_env = {k: os.environ.get(k) for k in list(env) + ['HOST_API_URL']}
    os.environ.update(env)

    app = Flask(__name__)
    # threading, not gevent: gevent is not installed in this dev environment (the
    # deployed host uses gevent via app_utils.py - see shared/src/lib/utils/app_utils.py
    # lines ~240-266 - flask_socketio.SocketIO.call()/emit(callback=) work the same
    # way under both, which is exactly what bridge.py's _call() relies on).
    socketio = SocketIO(app, async_mode='threading', cors_allowed_origins='*')
    app.socketio = socketio
    # A bare test app has no controller_manager-built device registry; give it one
    # fake Device so the hello rename path (bridge._rename_device) has something to
    # exercise instead of silently no-op'ing.
    app.host_devices = {DEVICE_ID: _FakeDevice(DEVICE_ID, 'Phone slot 1')}

    mobile_app_backend_host.register(app)

    port = _free_port()
    os.environ['HOST_API_URL'] = f'http://127.0.0.1:{port}'
    base_url = f'http://127.0.0.1:{port}'

    server_thread = threading.Thread(
        target=lambda: socketio.run(app, host='127.0.0.1', port=port,
                                     allow_unsafe_werkzeug=True, log_output=False,
                                     use_reloader=False, debug=False),
        daemon=True,
    )
    server_thread.start()

    for _ in range(50):
        try:
            r = requests.get(f'{base_url}/host/phone/slots', timeout=1)
            if r.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.1)
    else:
        pytest.fail('mobile-app test host did not start in time')

    state = {
        'app': app,
        'bridge': bridge_module.get_bridge(),
        'base_url': base_url,
        'frame_path': str(frame_path),
        'fake_device': app.host_devices[DEVICE_ID],
    }
    yield state

    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _read_frame_bytes(path: str) -> bytes:
    with open(path, 'rb') as fh:
        return fh.read()


def _get_slot(session, device_id=DEVICE_ID) -> dict:
    r = requests.get(f"{session['base_url']}/host/phone/slots/{device_id}", timeout=5)
    assert r.status_code == 200, r.text
    return r.json()['slot']


# ---- 1. placeholder written at register ------------------------------------

def test_1_placeholder_written_at_register(session):
    assert os.path.isfile(session['frame_path'])
    img = Image.open(session['frame_path'])
    assert img.size == (720, 1280)  # spec: portrait 720x1280 "not paired" placeholder
    img.close()


# ---- 2. POST /host/phone/pairings + pending slot ---------------------------

def test_2_pairing_creates_pending_slot(session):
    r = requests.post(f"{session['base_url']}/host/phone/pairings", json={'device_id': DEVICE_ID}, timeout=5)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['success'] is True
    assert body['token']
    assert body['expires_at']
    assert body['device_id'] == DEVICE_ID
    assert body['connect']['host_name'] == 'test-host'
    assert body['connect']['host_api_url'] == session['base_url']
    assert body['connect']['host_url'] == 'https://vpt.example/host/test-host'

    slot = _get_slot(session)
    assert slot['state'] == 'pending'

    session['pairing_token'] = body['token']


# ---- 3. sim pairs with the token -------------------------------------------

def test_3_sim_pairs_with_token(session):
    placeholder_bytes = _read_frame_bytes(session['frame_path'])

    sim = PhoneSim(session['base_url'], token=session['pairing_token'], fps=5,
                    manufacturer='Google', model='Pixel 8 Sim')
    ack = sim.start(wait_connected=8.0)
    assert ack['ok'] is True
    assert ack['device_id'] == DEVICE_ID
    assert ack['device_secret']

    slot = None
    for _ in range(30):
        slot = _get_slot(session)
        if slot['state'] == 'connected':
            break
        time.sleep(0.2)
    assert slot['state'] == 'connected'
    assert slot['phone']['manufacturer'] == 'Google'
    assert slot['phone']['model'] == 'Pixel 8 Sim'

    # A live frame must land on disk within 3s and must not be the placeholder.
    live_bytes = None
    for _ in range(30):
        time.sleep(0.1)
        if os.path.isfile(session['frame_path']):
            candidate = _read_frame_bytes(session['frame_path'])
            if candidate != placeholder_bytes:
                live_bytes = candidate
                break
    assert live_bytes is not None, 'no live frame written within 3s of pairing'
    live_img = Image.open(session['frame_path'])
    live_img.verify()  # a valid JPEG, not a half-written file

    # hello renamed the fake Device to "<manufacturer> <model>" (TASK-17 §1.2 step 5).
    assert session['fake_device'].device_name == 'Google Pixel 8 Sim'

    session['sim'] = sim
    session['device_secret'] = ack['device_secret']


# ---- 4. controller round-trip ------------------------------------------------

def test_4_controller_roundtrip(session):
    controller = PhoneAgentRemoteController(device_id=DEVICE_ID, device_name='Phone slot 1',
                                             bridge=session['bridge'])

    assert controller.tap_coordinates(100, 200) is True

    success, elements, error = controller.dump_elements()
    assert success is True, error
    assert len(elements) == 3
    assert controller.last_ui_elements == elements

    shot_ok, shot_b64, shot_err = controller.take_screenshot()
    assert shot_ok is True, shot_err
    assert len(shot_b64) > 100

    apps = controller.get_installed_apps()
    assert len(apps) == 2
    assert {a.package_name for a in apps} == {'com.android.settings', 'com.android.chrome'}

    assert controller.press_key('KEYCODE_BACK') is True  # ADB name -> agent 'BACK'
    assert controller.press_key('NOT_A_REAL_KEY') is False  # unmapped key -> False, no RPC

    info = controller.get_device_info()
    assert info['manufacturer'] == 'Google'
    resolution = controller.get_device_resolution()
    assert resolution and resolution['width'] > 0 and resolution['height'] > 0

    status = controller.get_status()
    assert status['success'] is True

    session['controller'] = controller


# ---- 5. wrong token is rejected and disconnected ---------------------------

def test_5_wrong_token_rejected(session):
    bad_sim = PhoneSim(session['base_url'], token='not-a-real-token', fps=5)
    with pytest.raises(RuntimeError):
        bad_sim.start(wait_connected=5.0)
    assert bad_sim._hello_ack.get('ok') is False
    time.sleep(0.3)
    assert bad_sim.sio.connected is False


# ---- 6. reconnect with device_secret works without a token -----------------

def test_6_reconnect_with_device_secret(session):
    session['sim'].stop()
    for _ in range(30):
        slot = _get_slot(session)
        if slot['state'] != 'connected':
            break
        time.sleep(0.1)

    sim2 = PhoneSim(session['base_url'], device_secret=session['device_secret'], fps=5,
                     manufacturer='Google', model='Pixel 8 Sim')
    ack = sim2.start(wait_connected=8.0)
    assert ack['ok'] is True
    assert ack['device_id'] == DEVICE_ID

    slot = None
    for _ in range(30):
        slot = _get_slot(session)
        if slot['state'] == 'connected':
            break
        time.sleep(0.2)
    assert slot['state'] == 'connected'

    session['sim'] = sim2
    session['device_secret'] = ack['device_secret']  # rotated on every successful hello


# ---- 7. offline placeholder after the delay --------------------------------

def test_7_offline_placeholder_after_delay(session):
    # PhoneSim streams a portrait 1080x2400 image thumbnailed to
    # PHONE_AGENT_MAX_SIDE (1280) -> (576, 1280): a different shape from the
    # 720x1280 placeholder, so image *size* (not exact bytes, which a live stream
    # keeps re-encoding even with unchanged pixels) is the stable "still live" vs
    # "back to placeholder" signal here.
    live_size = Image.open(session['frame_path']).size
    assert live_size != (720, 1280)
    session['sim'].stop()

    slot = None
    for _ in range(30):
        slot = _get_slot(session)
        if slot['state'] == 'offline':
            break
        time.sleep(0.2)
    assert slot['state'] == 'offline'

    # protocol.OFFLINE_PLACEHOLDER_DELAY_S (5s) must pass before the placeholder lands.
    time.sleep(0.5)
    assert Image.open(session['frame_path']).size != (720, 1280), \
        'offline placeholder written before OFFLINE_PLACEHOLDER_DELAY_S elapsed'

    became_placeholder = False
    for _ in range(60):
        time.sleep(0.2)
        if Image.open(session['frame_path']).size == (720, 1280):
            became_placeholder = True
            break
    assert became_placeholder, 'offline placeholder never written'


# ---- 8. unpair -------------------------------------------------------------

def test_8_unpair_resets_slot(session):
    r = requests.delete(f"{session['base_url']}/host/phone/slots/{DEVICE_ID}", timeout=5)
    assert r.status_code == 200, r.text
    assert r.json()['success'] is True

    slot = _get_slot(session)
    assert slot['state'] == 'free'
    assert slot['phone'] is None

    # the fake Device's name is restored to the slot label.
    assert session['fake_device'].device_name == 'Phone slot 1'


def test_unknown_slot_returns_404(session):
    r = requests.post(f"{session['base_url']}/host/phone/pairings", json={'device_id': 'device9'}, timeout=5)
    assert r.status_code == 404
    r = requests.get(f"{session['base_url']}/host/phone/slots/device9", timeout=5)
    assert r.status_code == 404
    r = requests.delete(f"{session['base_url']}/host/phone/slots/device9", timeout=5)
    assert r.status_code == 404
