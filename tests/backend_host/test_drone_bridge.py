"""
tests/backend_host/test_drone_bridge.py — TASK-167 end-to-end test of the phone as the
drone's radio end.

The chain is the real one, with real sockets on every hop:

    drone simulator (real UDP: 8889/8890/11111)
        <--UDP-->  DronePhoneSim (the phone: one cmd socket, N drones)
            <--Socket.IO-->  DroneBridge (the host sidecar, on 127.0.0.1)
                <--UDP-->  TelloClient (the host's ordinary drone client)

The point of the test is that the LAST hop is the ordinary TelloClient: nothing in
shared/src/lib/drone/tello.py or in the Tello controller knows that this drone is
behind a phone. If the drone flies, the state arrives and the video lands on the
injected port, then the design holds.

Run:
    cd <worktree> && PYTHONPATH=. python3 -m pytest tests/backend_host/test_drone_bridge.py -q
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
drone_bridge_module = importlib.import_module('features.mobile-app.backend_host.drone_bridge')
drone_phone_sim_module = importlib.import_module('features.mobile-app.backend_host.drone_phone_sim')
bridge_module = importlib.import_module('features.mobile-app.backend_host.bridge')

DronePhoneSim = drone_phone_sim_module.DronePhoneSim

# The drone's ports on the phone's side, and the host's sidecar ports. Every
# number is its own so nothing collides inside one test machine.
PHONE_CMD_PORT = 18889
PHONE_STATE_PORT = 18890
PHONE_VIDEO_PORT = 18891
SIM_CMD_PORT = 18892
SIM_STATE_PORT = 18893
SIM_VIDEO_PORT = 18894

HOST_CMD_PORT = 28001        # the sidecar answers SDK commands here
HOST_STATE_PORT = 28901      # the sidecar injects the drone's state here
HOST_LOCAL_CMD_PORT = 28801  # the host's TelloClient binds this locally
HOST_VIDEO_PORT = 29001      # the sidecar injects the drone's RTP here

DRONE_LABEL = 'droneA'


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout_s: float = 10.0) -> bool:
    """True once something is listening on `port` (the simulator's own sockets)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.bind(('127.0.0.1', port))
                return True
        except OSError:
            time.sleep(0.05)
    return False


@pytest.fixture(scope='module')
def session(tmp_path_factory):
    """One host process with a bridged drone, a phone slot and a drone simulator.

    The environment is shaped like a real host's: DEVICE3_MODEL=tello with
    DEVICE3_TELLO_BRIDGE=phone, and the drone's ports pointing at the sidecar.
    """
    tmp_dir = tmp_path_factory.mktemp('drone_bridge')
    frame_path = tmp_dir / 'phone_frames' / 'device2' / 'latest.jpg'

    env = {
        'DEVICE2_NAME': 'Phone slot 1',
        'DEVICE2_MODEL': 'phone_agent',
        'DEVICE2_VIDEO': str(frame_path),
        'PHONE_AGENT_STATE_FILE': str(tmp_dir / 'state.json'),
        # The bridged drone.
        'DEVICE3_NAME': 'Tello remote',
        'DEVICE3_MODEL': 'tello',
        'DEVICE3_TELLO_BRIDGE': 'phone',
        'DEVICE3_TELLO_BRIDGE_PHONE': 'device2',
        'DEVICE3_TELLO_BRIDGE_DRONE': DRONE_LABEL,
        'DEVICE3_TELLO_IP': '127.0.0.1',
        'DEVICE3_TELLO_CMD_PORT': str(HOST_CMD_PORT),
        'DEVICE3_TELLO_STATE_PORT': str(HOST_STATE_PORT),
        'DEVICE3_TELLO_LOCAL_CMD_PORT': str(HOST_LOCAL_CMD_PORT),
        'DEVICE3_VIDEO': f'udp://127.0.0.1:{HOST_VIDEO_PORT}',
        'HOST_NAME': 'test-host',
        'HOST_URL': 'https://vpt.example/host/test-host',
    }
    old_env = {k: os.environ.get(k) for k in list(env) + ['HOST_API_URL']}
    os.environ.update(env)

    # The bridge is a per-process singleton. A host has exactly one, so the
    # singleton is right in production - but each test module boots its own host
    # app, and the second one would otherwise inherit the first one's slots.
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
            r = requests.get(f'{base_url}/host/phone/slots', timeout=1)
            if r.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.1)
    else:
        pytest.fail('drone bridge test host did not start in time')

    # The drone simulator: the real SDK on real UDP ports, pushing its state to
    # the phone's state port and its video to the phone's video port.
    from shared.src.lib.drone.sim.tello_sim import TelloSim
    from shared.src.lib.drone.sim.world import Room
    sim = TelloSim(Room(), drone_id=1, bind_ip='127.0.0.1', cmd_port=SIM_CMD_PORT,
                   client_ip='127.0.0.1', state_port=PHONE_STATE_PORT,
                   video_port=PHONE_VIDEO_PORT, fps=5)
    sim.start()

    # The phone: carries the drone and relays it to the host. The drone's
    # address is the simulator's, and the phone's sockets are the ones the
    # simulator pushes to.
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
        'bridge': bridge_module.get_bridge(),
        'drone_bridge': mobile_app_backend_host.get_drone_bridge(),
        'phone': phone,
        'sim': sim,
    }
    yield state

    try:
        phone.stop()
    except Exception:
        pass
    sim.stop()
    mobile_app_backend_host.reset_drone_bridge()
    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---- 1. the sidecar exists and is configured ---------------------------------

def test_1_sidecar_knows_the_drone(session):
    summary = session['drone_bridge'].summary()
    assert 'device3' in summary, summary
    link = summary['device3']
    assert link['cmd_port'] == HOST_CMD_PORT
    assert link['state_port'] == HOST_STATE_PORT
    assert link['video_port'] == HOST_VIDEO_PORT
    assert link['local_cmd_port'] == HOST_LOCAL_CMD_PORT
    assert link['phone_slot'] == 'device2'
    assert link['drone_label'] == DRONE_LABEL


# ---- 2. the phone is connected and the drone is known ------------------------

def test_2_phone_connected_and_drone_seen(session):
    deadline = time.time() + 10
    while time.time() < deadline:
        summary = session['drone_bridge'].summary()
        if summary['device3']['ip']:
            break
        time.sleep(0.2)
    summary = session['drone_bridge'].summary()
    assert summary['device3']['ip'] == '127.0.0.1', summary


# ---- 3. a command reaches the drone and its answer comes back ---------------

def test_3_command_travels_to_the_drone(session):
    from shared.src.lib.drone.tello import TelloClient, TelloError
    client = TelloClient('127.0.0.1', cmd_port=HOST_CMD_PORT, state_port=HOST_STATE_PORT,
                          local_ip='127.0.0.1', name='bridged', local_cmd_port=HOST_LOCAL_CMD_PORT)
    try:
        client.connect(timeout_s=10)
        # `command` is the SDK handshake: the drone only answers the socket that
        # sent it, so this also proves the phone's socket is the bound one.
        assert client.send('battery?') != '', 'the drone did not answer'
    finally:
        client.close()


# ---- 4. the state stream reaches the client ----------------------------------

def test_4_state_stream_arrives(session):
    from shared.src.lib.drone.tello import TelloClient
    client = TelloClient('127.0.0.1', cmd_port=HOST_CMD_PORT, state_port=HOST_STATE_PORT,
                          local_ip='127.0.0.1', name='bridged', local_cmd_port=HOST_LOCAL_CMD_PORT)
    try:
        client.connect(timeout_s=10)
        deadline = time.time() + 8
        while time.time() < deadline and not client.state():
            time.sleep(0.1)
        state = client.state()
        assert state, 'no state arrived through the bridge'
        assert 'bat' in state, state
    finally:
        client.close()


# ---- 5. the video is injected on the port ffmpeg reads ----------------------

def test_5_video_is_injected(session):
    """The drone's RTP must arrive on the port vpt-stream's ffmpeg reads.

    ffmpeg binds udp://127.0.0.1:<video port>; the sidecar injects there. The
    test listens on that port the way ffmpeg would.

    The drone only streams after `streamon`, which is what the real controller
    sends right after it links (backend_host/src/controllers/remote/tello.py).
    """
    from shared.src.lib.drone.tello import TelloClient
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', HOST_VIDEO_PORT))
    listener.settimeout(5)
    client = TelloClient('127.0.0.1', cmd_port=HOST_CMD_PORT, state_port=HOST_STATE_PORT,
                          local_ip='127.0.0.1', name='bridged', local_cmd_port=HOST_LOCAL_CMD_PORT)
    try:
        client.connect(timeout_s=10)
        assert client.send_ok('streamon') is True
        try:
            packet, _ = listener.recvfrom(65535)
        except socket.timeout:
            packet = b''
        assert packet, 'no video packet was injected on the video port'
        assert len(packet) > 0
    finally:
        client.close()
        listener.close()


# ---- 6. the flight works end to end -----------------------------------------

def test_6_takeoff_and_land(session):
    from shared.src.lib.drone.tello import TelloClient
    client = TelloClient('127.0.0.1', cmd_port=HOST_CMD_PORT, state_port=HOST_STATE_PORT,
                          local_ip='127.0.0.1', name='bridged', local_cmd_port=HOST_LOCAL_CMD_PORT)
    try:
        client.connect(timeout_s=10)
        assert client.send_ok('takeoff') is True
        time.sleep(1.0)
        assert client.send_ok('land') is True
    finally:
        client.close()


# ---- 7. the host's REST status shows the link --------------------------------

def test_7_rest_status(session):
    r = requests.get(f"{session['base_url']}/host/phone/drones", timeout=5)
    assert r.status_code == 200, r.text
    drones = r.json()['drones']
    assert 'device3' in drones
    assert drones['device3']['commands_sent'] >= 1
