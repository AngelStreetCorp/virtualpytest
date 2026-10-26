"""Generic voice actions for a held device (TASK-160 phase 2): plan -> read back -> run, abort, lock, allow-list."""

import sys

sys.path.insert(0, 'backend_server/src')          # the routes import the agent package as `agent`

from agent import voice_device as vd

from backend_server.src.lib.utils.drone_voice import VoiceExecutor

CALLER = {'user_id': 'u1', 'user_name': 'Ann', 'session_ids': ['s1']}
STB = {'device_id': 'device3', 'device_name': 'STB', 'device_model': 'stb', 'device_action_types': {
    'remote': [
        {'id': 'home', 'label': 'Home', 'command': 'press_key', 'params': {'key': 'HOME'}, 'action_type': 'remote'},
        {'id': 'vol', 'label': 'Volume up', 'command': 'press_key', 'params': {'key': 'VOL_UP', 'times': 1}, 'action_type': 'remote'},
        {'id': 'sdk', 'label': 'Raw', 'command': 'sdk', 'params': {'cmd': 'x'}, 'action_type': 'remote'},
        {'id': 'typed', 'label': 'Type text', 'command': 'type', 'params': {}, 'requiresInput': True, 'action_type': 'remote'}]}}
TELLO = {'device_id': 'device5', 'device_name': 'Tello-C5B142', 'device_model': 'tello', 'device_action_types': {}}
HOST = {'host_name': 'h', 'devices': [STB, TELLO]}


class Drone:
    """A VoiceExecutor over a recording fake host."""

    def __init__(self, bat=80):
        self.calls = []
        self.bat = bat
        self.ex = VoiceExecutor(self.send, lambda *a: True)

    def send(self, host, device, command, params):
        self.calls.append((command, params))
        if command == 'get_telemetry':
            return {'success': True, 'telemetry': {'bat': self.bat}}
        return {'success': True}

    def __getattr__(self, name):
        return getattr(self.ex, name)


def classify_returning(action, params=None, tool='device_action'):
    seen = {}

    def classify(**kw):
        seen.update(kw)
        return {'tool': tool, 'args': {'action': action, 'params': params or {}}}
    classify.seen = seen
    return classify


def plan(text, device='device3', locked=True, classify=None, drone=None):
    return vd.plan(text=text, lang='en', host_name='h', device_id=device, host_info=HOST, caller=CALLER, team_id='t',
                   holds_lock=lambda h, d, c: locked, drone=drone or Drone(), classify=classify or classify_returning('home'))


def test_actions_exclude_blocked_and_typed_ones():
    ids = [a['id'] for a in vd.flatten_actions(STB)]
    assert ids == ['home', 'vol']


def test_sanitize_params_only_declared_keys_and_types():
    d = {'cm': 50, 'key': 'A', 'ratio': 1.5}
    assert vd.sanitize_params(d, {'cm': '30', 'evil': 1, 'key': 'B', 'ratio': 'x'}) == {'cm': 30, 'key': 'B', 'ratio': 1.5}
    assert vd.sanitize_params(d, {'cm': [1]}) == d and vd.sanitize_params(d, 'nope') == d


def test_generic_plan_then_run_executes_one_listed_action():
    classify = classify_returning('vol', {'times': '3', 'key': 'POWER'})
    out = plan('turn the volume up three times', classify=classify)
    assert out['decision'] == 'plan' and out['label'] == 'Volume up'
    assert [a['id'] for a in classify.seen['actions']] == ['home', 'vol']
    ran = []
    res = vd.run(plan_id=out['plan_id'], caller=CALLER, team_id='t', holds_lock=lambda *a: True, drone=Drone(),
                 execute=lambda h, d, a, t: ran.append(a) or {'success': True})
    assert res['decision'] == 'sent' and res['reply'] == 'Done.'
    assert ran[0]['command'] == 'press_key' and ran[0]['params'] == {'key': 'POWER', 'times': 3}


def test_a_plan_runs_once_and_only_for_its_caller():
    pid = plan('home')['plan_id']
    other = {'user_id': 'u2', 'session_ids': ['s2']}
    kw = {'team_id': 't', 'holds_lock': lambda *a: True, 'drone': Drone(), 'execute': lambda *a: {'success': True}}
    assert vd.run(plan_id=pid, caller=other, **kw)['reason'] == 'gone'
    pid = plan('home')['plan_id']
    assert vd.run(plan_id=pid, caller=CALLER, **kw)['decision'] == 'sent'
    assert vd.run(plan_id=pid, caller=CALLER, **kw)['reason'] == 'gone'


def test_abort_between_plan_and_run_drops_the_command():
    pid = plan('home')['plan_id']
    out = plan('abort')
    assert out['decision'] == 'abort' and out['listening'] is True
    ran = []
    res = vd.run(plan_id=pid, caller=CALLER, team_id='t', holds_lock=lambda *a: True, drone=Drone(),
                 execute=lambda *a: ran.append(1) or {'success': True})
    assert res['reason'] == 'aborted' and ran == []


def test_stop_is_final_and_closes_the_microphone():
    out = plan('stop')
    assert out['decision'] == 'stop' and out['listening'] is False


def test_only_a_held_device():
    assert plan('home', locked=False)['reason'] == 'no_lock'
    pid = plan('home')['plan_id']
    res = vd.run(plan_id=pid, caller=CALLER, team_id='t', holds_lock=lambda *a: False, drone=Drone(), execute=lambda *a: 1 / 0)
    assert res['reason'] == 'no_lock'


def test_model_outside_the_list_or_not_a_device_action_is_refused():
    assert plan('x', classify=classify_returning('format_disk'))['reason'] == 'not_understood'
    assert plan('x', classify=classify_returning('home', tool='ask_atlas'))['reason'] == 'not_understood'
    assert plan('x', classify=lambda **kw: {'error': 'voice model HTTP 500'})['reason'] == 'model'


def test_no_actions_device():
    host = {'devices': [{'device_id': 'd9', 'device_name': 'Empty', 'device_model': 'x', 'device_action_types': {}}]}
    out = vd.plan(text='home', lang='en', host_name='h', device_id='d9', host_info=host, caller=CALLER, team_id='t',
                  holds_lock=lambda *a: True, drone=Drone(), classify=classify_returning('home'))
    assert out['reason'] == 'no_actions'


def test_execute_failure_is_reported():
    pid = plan('home')['plan_id']
    res = vd.run(plan_id=pid, caller=CALLER, team_id='t', holds_lock=lambda *a: True, drone=Drone(),
                 execute=lambda *a: {'success': False, 'error': 'device offline'})
    assert res['decision'] == 'failed' and 'device offline' in res['reply']


# ---- a Tello: grammar stage, never the model ---------------------------------------------------------------------

def never(**kw):
    raise AssertionError('the model must not be asked for a Tello')


def test_tello_plan_read_back_then_run_with_limits():
    drone = Drone()
    out = plan('go up fifty centimetres', device='device5', classify=never, drone=drone)
    assert out['decision'] == 'plan' and out['label'] == 'Move up 50 cm' and drone.calls == []
    res = vd.run(plan_id=out['plan_id'], caller=CALLER, team_id='t', holds_lock=lambda *a: True, drone=drone,
                 execute=lambda *a: 1 / 0)
    assert res['decision'] == 'sent' and drone.calls[-1] == ('move', {'direction': 'up', 'cm': 50})


def test_tello_refusals_and_land_are_final():
    drone = Drone()
    assert plan('go forward two metres', device='device5', classify=never, drone=drone)['reason'] == 'too_far'
    assert plan('fly to the kitchen', device='device5', classify=never, drone=drone)['reason'] == 'not_understood'
    out = plan('land', device='device5', classify=never, drone=drone)
    assert out['decision'] == 'sent' and drone.calls == [('land', {})]


def test_tello_stop_hovers_and_closes_the_mic_abort_keeps_it():
    drone = Drone()
    out = plan('stop', device='device5', classify=never, drone=drone)
    assert out['decision'] == 'sent' and out['listening'] is False and drone.calls[-1][0] == 'rc'
    out = plan('abort', device='device5', classify=never, drone=drone)
    assert out['listening'] is True and drone.calls[-1][0] == 'rc'


def test_tello_abort_between_plan_and_run_drops_takeoff():
    drone = Drone()
    pid = plan('take off', device='device5', classify=never, drone=drone)['plan_id']
    plan('abort', device='device5', classify=never, drone=drone)
    res = vd.run(plan_id=pid, caller=CALLER, team_id='t', holds_lock=lambda *a: True, drone=drone, execute=lambda *a: 1 / 0)
    assert res['reason'] == 'aborted' and ('takeoff', {}) not in drone.calls


def test_tello_battery_floor_still_applies_at_run():
    drone = Drone(bat=30)
    pid = plan('take off', device='device5', classify=never, drone=drone)['plan_id']
    res = vd.run(plan_id=pid, caller=CALLER, team_id='t', holds_lock=lambda *a: True, drone=drone, execute=lambda *a: 1 / 0)
    assert res['reason'] == 'battery_low' and all(c[0] == 'get_telemetry' for c in drone.calls)
