"""
tests/backend_host/test_drone_hybrid_link.py — TASK-173 end-to-end test of the HYBRID link.

The drone sits on ONE Wi-Fi network at a time. The owner decides which one: the
lab's own radio (the host's USB dongle) or the phone's hotspot. The host does
not choose networks - it watches both paths and uses the one that answers,
preferring the lab.

So the test has TWO drones, one on each path, and watches which one is flown:

    direct drone simulator  <--UDP-->  DroneBridge (the host's own radio)
    phone drone simulator   <--UDP-->  DronePhoneSim (the phone)
                              <--Socket.IO-->  DroneBridge  <--UDP-->  TelloClient

Every hop is a real socket. The last hop is the ordinary TelloClient: nothing in
shared/src/lib/drone/tello.py knows that this drone may be in a field.

Run:
    cd <worktree> && PYTHONPATH=. python3 -m pytest tests/backend_host/test_drone_hybrid_link.py -q
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

protocol = importlib.import_module('features.mobile-app.lib.protocol')
mobile_app_backend_host = importlib.import_module('features.mobile-app.backend_host')
drone_phone_sim_module = importlib.import_module('features.mobile-app.backend_host.drone_phone_sim')
bridge_module = importlib.import_module('features.mobile-app.backend_host.bridge')

DronePhoneSim = drone_phone_sim_module.DronePhoneSim

# Every port is its own so nothing collides inside one test machine.
HOST_CMD_PORT = 28101        # the sidecar answers SDK commands here
HOST_STATE_PORT = 28911      # the sidecar injects the drone's state here
HOST_LOCAL_CMD_PORT = 28811  # the host's TelloClient binds this locally
HOST_VIDEO_PORT = 29101      # the sidecar injects the drone's RTP here

DIRECT_CMD_PORT = 18895      # the drone's SDK port on the lab network
DIRECT_STATE_PORT = 18896    # where the drone pushes its state on the lab network
DIRECT_VIDEO_PORT = 18897    # where the drone pushes its RTP on the lab network
DIRECT_LOCAL_CMD_PORT = 18898  # the sidecar's own SDK socket towards the drone

PHONE_CMD_PORT = 18889
PHONE_STATE_PORT = 18890
PHONE_VIDEO_PORT = 18891
SIM_CMD_PORT = 18892
SIM_STATE_PORT = 18893
SIM_VIDEO_PORT = 18894

DRONE_LABEL = 'droneA'


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _make_sim(drone_id: int, cmd_port: int, state_port: int, video_port: int):
    """One drone simulator: the real SDK on real UDP ports."""
    from shared.src.lib.drone.sim.tello_sim import TelloSim
    from shared.src.lib.drone.sim.world import Room
    sim = TelloSim(Room(), drone_id=drone_id, bind_ip='127.0.0.1', cmd_port=cmd_port,
                   client_ip='127.0.0.1', state_port=state_port, video_port=video_port, fps=5)
    sim.start()
    return sim


@pytest.fixture(scope='module')
def session(tmp_path_factory):
    """One host with a hybrid drone, a phone and a drone on each path.

    The environment is shaped like a real host's: a tello device with
    DEVICE3_TELLO_BRIDGE=phone (the phone can carry it), DEVICE3_TELLO_LINK=auto
    (the lab path is preferred) and DEVICE3_TELLO_DIRECT_IP (the drone's address
    on the lab network).
    """
    tmp_dir = tmp_path_factory.mktemp('drone_hybrid')
    frame_path = tmp_dir / 'phone_frames' / 'device2' / 'latest.jpg'

    env = {
        'DEVICE2_NAME': 'Phone slot 1',
        'DEVICE2_MODEL': 'phone_agent',
        'DEVICE2_VIDEO': str(frame_path),
        'PHONE_AGENT_STATE_FILE': str(tmp_dir / 'state.json'),
        # The hybrid drone.
        'DEVICE3_NAME': 'Tello hybrid',
        'DEVICE3_MODEL': 'tello',
        'DEVICE3_TELLO_BRIDGE': 'phone',
        'DEVICE3_TELLO_BRIDGE_PHONE': 'device2',
        'DEVICE3_TELLO_BRIDGE_DRONE': DRONE_LABEL,
        'DEVICE3_TELLO_LINK': 'auto',
        'DEVICE3_TELLO_IP': '127.0.0.1',
        'DEVICE3_TELLO_CMD_PORT': str(HOST_CMD_PORT),
        'DEVICE3_TELLO_STATE_PORT': str(HOST_STATE_PORT),
        'DEVICE3_TELLO_LOCAL_CMD_PORT': str(HOST_LOCAL_CMD_PORT),
        'DEVICE3_VIDEO': f'udp://127.0.0.1:{HOST_VIDEO_PORT}',
        # The direct path: the host's own radio reaching the drone.
        'DEVICE3_TELLO_DIRECT_IP': '127.0.0.1',
        'DEVICE3_TELLO_DIRECT_LOCAL_IP': '127.0.0.1',
        'DEVICE3_TELLO_DIRECT_LOCAL_CMD_PORT': str(DIRECT_LOCAL_CMD_PORT),
        'DEVICE3_TELLO_DIRECT_CMD_PORT': str(DIRECT_CMD_PORT),
        'DEVICE3_TELLO_DIRECT_STATE_PORT': str(DIRECT_STATE_PORT),
        'DEVICE3_TELLO_DIRECT_VIDEO_PORT': str(DIRECT_VIDEO_PORT),
        # Timings: a test must not wait for the real ones.
        # The simulator's take-off takes 2.5 s (a real drone answers in
        # milliseconds), so the test's direct timeout is generous.
        'VPT_DRONE_DIRECT_SEND_TIMEOUT_S': '4.0',
        'VPT_DRONE_DIRECT_PROBE_TIMEOUT_S': '1.0',
        'VPT_DRONE_DIRECT_PROBE_INTERVAL_S': '2.0',
        'HOST_NAME': 'test-host',
        'HOST_URL': 'https://vpt.example/host/test-host',
    }
    old_env = {k: os.environ.get(k) for k in list(env) + ['HOST_API_URL']}
    os.environ.update(env)

    mobile_app_backend_host.reset_drone_bridge()

    app = Flask(__name__)
    socketio = SocketIO(app, async_mode='threading', cors_allowed_origins='*')
    app.socketio = socketio
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
            if requests.get(f'{base_url}/host/phone/slots', timeout=1).status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.1)
    else:
        pytest.fail('drone hybrid test host did not start in time')

    # The drone ON THE LAB NETWORK: the host's own radio reaches it.
    direct_sim = _make_sim(2, DIRECT_CMD_PORT, DIRECT_STATE_PORT, DIRECT_VIDEO_PORT)

    # The drone ON THE PHONE'S HOTSPOT: the phone carries it.
    phone_sim = _make_sim(1, SIM_CMD_PORT, SIM_STATE_PORT, SIM_VIDEO_PORT)
    phone = DronePhoneSim(base_url, device_secret=None, drone_ips=['127.0.0.1'],
                           drone_labels=[DRONE_LABEL], device_id='device2',
                           cmd_port=PHONE_CMD_PORT, state_port=PHONE_STATE_PORT,
                           video_port=PHONE_VIDEO_PORT, drone_cmd_port=SIM_CMD_PORT)
    pairing = requests.post(f'{base_url}/host/phone/pairings',
                             json={'device_id': 'device2'}, timeout=5).json()
    phone.token = pairing['token']
    phone.start()

    state = {
        'app': app,
        'base_url': base_url,
        'drone_bridge': mobile_app_backend_host.get_drone_bridge(),
        'phone': phone,
        'direct_sim': direct_sim,
        'phone_sim': phone_sim,
    }
    yield state

    try:
        phone.stop()
    except Exception:
        pass
    direct_sim.stop()
    phone_sim.stop()
    mobile_app_backend_host.reset_drone_bridge()
    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _client():
    from shared.src.lib.drone.tello import TelloClient
    return TelloClient('127.0.0.1', cmd_port=HOST_CMD_PORT, state_port=HOST_STATE_PORT,
                       local_ip='127.0.0.1', name='hybrid', local_cmd_port=HOST_LOCAL_CMD_PORT)


def _summary(session):
    return session['drone_bridge'].summary()['device3']


def _land_sim(cmd_port: int) -> None:
    """Put one simulator on the ground, straight to its own port.

    The simulator refuses a second take-off while it is flying, so each test
    starts from a known state. This bypasses the bridge on purpose: it is the
    bench, not the path under test.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(1.0)
        s.sendto(b'land', ('127.0.0.1', cmd_port))
        try:
            s.recvfrom(2048)
        except socket.timeout:
            pass
    time.sleep(0.3)


def _grounded(session):
    """Both simulators on the ground."""
    _land_sim(DIRECT_CMD_PORT)
    _land_sim(SIM_CMD_PORT)
    time.sleep(0.5)


# ---- 1. the hybrid is configured --------------------------------------------

def test_1_the_hybrid_is_configured(session):
    link = _summary(session)
    assert link['link_mode'] == 'auto', link
    assert link['direct_ip'] == '127.0.0.1', link
    assert link['active_path'] == 'direct', link


# ---- 2. the lab path carries the command ------------------------------------

def test_2_the_lab_path_carries_the_command(session):
    """With the drone on the lab network, the host's own radio flies it.

    The phone carries a drone too, so this proves which one was used: only the
    drone on the lab network may take off.
    """
    _grounded(session)
    client = _client()
    try:
        client.connect(timeout_s=10)
        assert client.send_ok('takeoff') is True
        time.sleep(0.5)
        assert session['direct_sim'].flying is True, 'the lab path did not carry the command'
        assert session['phone_sim'].flying is False, 'the command went to the phone'
        assert client.send_ok('land') is True
    finally:
        client.close()


# ---- 3. the phone takes over when the drone leaves the lab ------------------

def test_3_the_phone_takes_over_when_the_drone_leaves_the_lab(session):
    """The drone moved to the phone's hotspot: the phone path takes over.

    The direct path fails (the drone is not there any more), and the bridge
    carries the command on the phone instead - the drone is flown either way.
    """
    _grounded(session)
    session['direct_sim'].stop()

    client = _client()
    try:
        client.connect(timeout_s=15)
        assert client.send_ok('takeoff') is True
        time.sleep(0.5)
        assert session['phone_sim'].flying is True, 'the phone path did not carry the command'
        assert _summary(session)['active_path'] == 'phone', _summary(session)
        assert client.send_ok('land') is True
    finally:
        client.close()


# ---- 4. the bridge comes back to the lab ------------------------------------

def test_4_the_bridge_comes_back_to_the_lab(session):
    """The drone came back to the lab network: the bridge returns to it.

    Nothing tells the host that the drone moved - it finds out by asking, which
    is what the probe on the direct path does.
    """
    _grounded(session)
    session['direct_sim'] = _make_sim(2, DIRECT_CMD_PORT, DIRECT_STATE_PORT, DIRECT_VIDEO_PORT)

    deadline = time.time() + 30
    while time.time() < deadline:
        if _summary(session)['active_path'] == 'direct':
            break
        time.sleep(0.5)
    assert _summary(session)['active_path'] == 'direct', _summary(session)

    client = _client()
    try:
        client.connect(timeout_s=10)
        assert client.send_ok('takeoff') is True
        time.sleep(0.5)
        assert session['direct_sim'].flying is True, 'the lab path did not take the drone back'
        assert client.send_ok('land') is True
    finally:
        client.close()


# ---- 5. the host's REST status shows the whole story ------------------------

def test_5_rest_status_shows_the_hybrid(session):
    r = requests.get(f"{session['base_url']}/host/phone/drones", timeout=5)
    assert r.status_code == 200, r.text
    link = r.json()['drones']['device3']
    assert link['link_mode'] == 'auto', link
    assert link['active_path'] in ('direct', 'phone'), link
    assert link['direct_ip'] == '127.0.0.1', link
    assert link['commands_sent'] >= 1, link
