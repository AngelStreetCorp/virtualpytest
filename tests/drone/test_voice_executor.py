"""Tello voice executor (TASK-160): lock, bounds, battery, stop / abort priority, no confirmation, dropped link.

Part 1 uses a fake host (a recording ``send``). Part 2 drives the real TelloRemoteController against the Tello
simulator on loopback: no real drone is ever contacted.
"""

import socket

import pytest

from backend_host.src.controllers.remote.tello import TelloRemoteController
from backend_server.src.lib.utils.drone_voice import (
    VoiceExecutor,
    VoiceSettings,
    holds_lock,
)
from shared.src.lib.drone.sim.tello_sim import TelloSim, sim_ip
from shared.src.lib.drone.sim.world import Pose, default_room

DEVS = [{'device_id': 'device5', 'device_name': 'Tello-C5B142', 'name': 'Tello-C5B142'},
        {'device_id': 'device6', 'device_name': 'Tello-F014A0', 'name': 'Tello-F014A0'}]
CALLER = {'user_id': 'u1', 'user_name': 'Ann', 'session_ids': ['s1']}


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Host:
    """Recording fake host. ``bat`` None = no battery reading (dropped link)."""

    def __init__(self, bat=80):
        self.bat = bat
        self.calls = []
        self.reply = {'success': True}

    def send(self, host, device, command, params):
        self.calls.append((command, params))
        if command == 'get_telemetry':
            return {'success': True, 'telemetry': {'bat': self.bat} if self.bat is not None else {}}
        return dict(self.reply)

    def flight(self):
        return [c for c in self.calls if c[0] != 'get_telemetry']


def make(bat=80, locked=True, **settings):
    host, clock, audit = Host(bat), Clock(), []
    ex = VoiceExecutor(host.send, lambda h, d, c: locked, audit.append, VoiceSettings(**settings), clock)
    return ex, host, clock, audit


def say(ex, text, lang='en', device='device5'):
    return ex.handle(transcript=text, lang=lang, host_name='pi4', device_id=device, devices=DEVS, caller=CALLER)


def test_move_small_is_sent_without_confirmation():
    ex, host, _, audit = make()
    out = say(ex, 'go up thirty centimetres')
    assert out['decision'] == 'sent' and host.flight() == [('move', {'direction': 'up', 'cm': 30})]
    assert audit and audit[0]['transcript'] == 'go up thirty centimetres' and audit[0]['decision'] == 'sent'


def test_takeoff_and_large_moves_run_at_once_without_confirmation():
    ex, host, _, _ = make()
    assert say(ex, 'take off')['decision'] == 'sent'
    assert say(ex, 'go forward 90 centimetres')['decision'] == 'sent'
    assert say(ex, 'turn left 90 degrees')['decision'] == 'sent'
    assert [c[0] for c in host.flight()] == ['takeoff', 'move', 'rotate']
    assert say(ex, 'yes')['reason'] == 'not_understood'


def test_stop_hovers_and_closes_the_microphone_whatever_happens():
    ex, host, _, _ = make()
    out = say(ex, 'stop')
    assert out['decision'] == 'sent' and out['listening'] is False
    assert host.flight() == [('rc', {'lr': 0, 'fb': 0, 'ud': 0, 'yaw': 0})]
    ex2, host2, _, _ = make(locked=False)                  # no lock: nothing sent, the mic still closes
    out = say(ex2, 'stop')
    assert out['reason'] == 'no_lock' and out['listening'] is False and host2.calls == []


def test_abort_hovers_keeps_listening_and_drops_a_command_in_processing():
    ex, _host, _, _ = make()
    out = say(ex, 'abort')
    assert out['decision'] == 'sent' and out['listening'] is True and 'Aborted' in out['reply']

    # an abort that lands while a takeoff waits on the battery read: the takeoff is never sent
    ex2, host2, _, _ = make()
    real_send = host2.send

    def send_then_abort(h, d, command, params):
        res = real_send(h, d, command, params)
        if command == 'get_telemetry':
            say(ex2, 'cancel')                              # the abort word arrives mid-processing
        return res
    ex2._send = send_then_abort
    out = say(ex2, 'take off')
    assert out['decision'] == 'refused' and out['reason'] == 'aborted'
    assert [c for c in host2.flight() if c[0] == 'takeoff'] == []


def test_battery_floor_and_no_reading_refuse():
    ex, host, _, _ = make(bat=35)
    out = say(ex, 'take off')
    assert out['reason'] == 'battery_low' and out['battery'] == 35
    ex, host, _, _ = make(bat=None)
    assert say(ex, 'take off')['reason'] == 'no_reading'
    assert say(ex, 'go up 30 cm')['reason'] == 'no_reading'
    assert host.flight() == []


def test_nothing_understood_sends_nothing():
    ex, host, _, _ = make()
    for t in ('fly to the kitchen', '', 'send rc 100 100 100 100', 'go forward three metres', "don't take off"):
        out = say(ex, t)
        assert out['decision'] == 'refused', t
    assert host.calls == []


def test_no_lock_sends_nothing_even_for_land_and_stop():
    ex, host, _, _ = make(locked=False)
    for t in ('take off', 'land', 'stop', 'abort', 'go up 30 cm', 'emergency stop'):
        assert say(ex, t)['reason'] in ('no_lock',), t
    assert host.calls == []


def test_stop_and_land_ignore_battery():
    ex, host, _, _ = make(bat=5)
    assert say(ex, 'land')['decision'] == 'sent'
    assert say(ex, 'stop')['decision'] == 'sent'
    assert [c[0] for c in host.calls] == ['land', 'rc']       # not even a battery read first


def test_battery_question():
    ex, host, _, _ = make(bat=63)
    out = say(ex, 'how much battery')
    assert out['battery'] == 63 and '63' in out['reply'] and host.flight() == []


def test_other_drone_named_is_never_substituted():
    ex, host, _, _ = make()
    out = say(ex, 'Tello F014A0 land', device='device5')
    assert out['reason'] == 'wrong_device' and 'Tello-C5B142' in out['reply'] and host.calls == []
    assert say(ex, 'Tello C5B142 land')['decision'] == 'sent'


def test_emergency_is_opt_in_per_device():
    ex, host, _, _ = make()
    assert say(ex, 'emergency stop')['reason'] == 'emergency_off' and host.calls == []
    ex, host, _, _ = make(emergency_devices=frozenset({'device5'}))
    assert say(ex, 'emergency stop')['decision'] == 'sent' and host.calls == [('emergency', {})]
    assert say(ex, 'emergency')['reason'] == 'emergency_phrase'


def test_flip_refused():
    ex, host, _, _ = make()
    assert say(ex, 'do a flip')['reason'] == 'flip_off' and host.calls == []


def test_host_exception_and_refusal_are_reported_not_raised():
    ex, host, _, _ = make()
    host.reply = {'success': False, 'blocked': True, 'error': 'blocked: outside the room'}
    out = say(ex, 'go up thirty centimetres')
    assert out['decision'] == 'refused' and 'outside the room' in out['reply']

    def boom(*a):
        raise ConnectionError('link down')
    ex2 = VoiceExecutor(boom, lambda *a: True)
    out = say(ex2, 'land')
    assert out['decision'] == 'failed'
    assert say(ex2, 'go up thirty centimetres')['reason'] == 'no_reading'     # dropped link never moves


def test_french_replies():
    ex, _host, _, _ = make()
    out = say(ex, "monte de trente centimètres", lang='fr')
    assert out['decision'] == 'sent' and 'Déplacé' in out['reply']
    assert 'Rien envoyé' in say(ex, 'bonjour', lang='fr')['reply']


def test_audit_failure_never_breaks_a_command():
    host = Host()
    ex = VoiceExecutor(host.send, lambda *a: True, lambda e: 1 / 0)
    assert say(ex, 'land')['decision'] == 'sent'


def test_holds_lock_rules():
    lock = {'owner_session_id': 's1', 'owner_user_id': 'u9'}
    assert holds_lock(lock, {'session_ids': ['s1']})
    assert holds_lock({'owner_session_id': 'x', 'owner_user_id': 'u1'}, {'user_id': 'u1', 'session_ids': []})
    assert not holds_lock(None, CALLER)                              # a free device is not a held one
    assert not holds_lock({'owner_session_id': 'x', 'owner_user_id': 'u2'}, CALLER)
    assert not holds_lock(lock, {'session_ids': []})


# ---- part 2: real controller + simulator (loopback only) ------------------------------------------------------

def _free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def sim_rig():
    state_port = _free_udp_port()
    sim = TelloSim(default_room(), 3, sim_ip(3), state_port=state_port, video_port=_free_udp_port(), drift=0.0,
                   seed=1, time_scale=8.0, idle_timeout_s=30.0, start_pose=Pose(100, 100, 0, 0))
    sim.start()
    ctrl = TelloRemoteController(tello_ip=sim_ip(3), state_port=state_port, local_ip="127.0.0.1",
                                 local_cmd_port=_free_udp_port(), name="t3", keepalive_s=5.0)
    ctrl.connect()
    yield ctrl
    ctrl.disconnect()
    sim.stop()


def test_end_to_end_against_the_simulator(sim_rig):
    ctrl = sim_rig
    ctrl.execute_command('link', {})
    ex = VoiceExecutor(lambda h, d, c, p: ctrl.execute_command(c, p), lambda *a: True, settings=VoiceSettings())
    assert say(ex, 'take off')['decision'] == 'sent' and ctrl.airborne
    assert say(ex, 'go up thirty centimetres')['decision'] == 'sent'
    assert say(ex, 'turn right 30 degrees')['decision'] == 'sent'
    out = say(ex, 'go up fifty centimetres')                 # the controller's own ceiling still applies
    assert out['decision'] in ('sent', 'refused')
    assert say(ex, 'stop')['decision'] == 'sent'
    assert say(ex, 'land')['decision'] == 'sent' and not ctrl.airborne


# ---- part 3: the plan / read back / run path of Actions > Voice, controller on the simulator -------------------------

def test_plan_and_run_end_to_end_against_the_simulator(sim_rig):
    import sys
    sys.path.insert(0, 'backend_server/src')
    from agent import voice_device as vd

    ctrl = sim_rig
    ctrl.execute_command('link', {})
    ex = VoiceExecutor(lambda h, d, c, p: ctrl.execute_command(c, p), lambda *a: True, settings=VoiceSettings())
    host_info = {'devices': [{'device_id': 'device5', 'device_name': 'Tello-C5B142', 'device_model': 'tello',
                              'device_action_types': {}}]}
    held = {'user_id': 'u1', 'session_ids': ['s1']}

    def never(**kw):
        raise AssertionError('the model must not be asked for a Tello')

    def hear(text):
        return vd.plan(text=text, lang='en', host_name='pi4', device_id='device5', host_info=host_info, caller=held,
                       team_id='t', holds_lock=lambda *a: True, drone=ex, classify=never)

    def run(plan):
        return vd.run(plan_id=plan['plan_id'], caller=held, team_id='t', holds_lock=lambda *a: True, drone=ex,
                      execute=lambda *a: 1 / 0)

    plan = hear('take off')
    assert plan['decision'] == 'plan' and plan['label'] == 'Take off' and not ctrl.airborne      # read back, not yet sent
    assert run(plan)['decision'] == 'sent' and ctrl.airborne
    assert run(hear('go up thirty centimetres'))['decision'] == 'sent'
    assert hear('go forward two metres')['reason'] == 'too_far'
    assert hear('stop')['listening'] is False
    assert hear('land')['decision'] == 'sent' and not ctrl.airborne
    out = vd.plan(text='take off', lang='en', host_name='pi4', device_id='device5', host_info=host_info, caller=held,
                  team_id='t', holds_lock=lambda *a: False, drone=ex, classify=never)
    assert out['reason'] == 'no_lock'                                  # a device that is not held
