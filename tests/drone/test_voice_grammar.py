"""Tello voice grammar (TASK-160): allow-list, EN + FR, clamps, names, refusals. Pure, no I/O."""

import pytest

from shared.src.lib.drone.voice_grammar import Limits, parse

DEVS = [{'device_id': 'device5', 'name': 'Tello-C5B142'}, {'device_id': 'device6', 'name': 'Tello-F014A0'}]


def _ok(text, intent, params=None, device=None):
    p = parse(text, DEVS)
    assert p.ok, (text, p.reason)
    assert p.intent == intent, (text, p.intent)
    assert p.params == (params or {}), (text, p.params)
    assert p.device_id == device, (text, p.device_id)


def _no(text, reason):
    p = parse(text, DEVS)
    assert not p.ok, (text, p.intent, p.params)
    assert p.reason == reason, (text, p.reason)


@pytest.mark.parametrize('text,intent,params', [
    ('take off', 'takeoff', {}), ('Takeoff please', 'takeoff', {}), ('décolle', 'takeoff', {}),
    ('décoller', 'takeoff', {}), ('land', 'land', {}), ('land now', 'land', {}), ('atterris', 'land', {}),
    ('atterrissage', 'land', {}), ('stop', 'stop', {}), ('hover', 'stop', {}), ('arrête', 'stop', {}),
    ('emergency stop', 'emergency', {}), ("arrêt d'urgence", 'emergency', {}),
    ('go up fifty centimetres', 'move', {'direction': 'up', 'cm': 50}),
    ('go up half a metre', 'move', {'direction': 'up', 'cm': 50}),
    ('monte de cinquante centimètres', 'move', {'direction': 'up', 'cm': 50}),
    ('monte d\'un demi mètre', 'move', {'direction': 'up', 'cm': 50}),
    ('go down 30 cm', 'move', {'direction': 'down', 'cm': 30}),
    ('descends de trente centimètres', 'move', {'direction': 'down', 'cm': 30}),
    ('forward one metre', 'move', {'direction': 'forward', 'cm': 100}),
    ('avance d\'un mètre', 'move', {'direction': 'forward', 'cm': 100}),
    ('go forward', 'move', {'direction': 'forward', 'cm': 50}),
    ('go up', 'move', {'direction': 'up', 'cm': 30}),
    ('move back twenty five centimeters', 'move', {'direction': 'back', 'cm': 25}),
    ('recule de quatre-vingts centimètres', 'move', {'direction': 'back', 'cm': 80}),
    ('go left 40', 'move', {'direction': 'left', 'cm': 40}),
    ('va à droite de soixante-dix centimètres', 'move', {'direction': 'right', 'cm': 70}),
    ('move right 1.5 m', None, None),
    ('turn left ninety degrees', 'rotate', {'direction': 'ccw', 'deg': 90}),
    ('turn right 45 degrees', 'rotate', {'direction': 'cw', 'deg': 45}),
    ('rotate clockwise sixty degrees', 'rotate', {'direction': 'cw', 'deg': 60}),
    ('tourne à gauche de quatre-vingt-dix degrés', 'rotate', {'direction': 'ccw', 'deg': 90}),
    ('pivote à droite de 30 degrés', 'rotate', {'direction': 'cw', 'deg': 30}),
    ('turn left', 'rotate', {'direction': 'ccw', 'deg': 30}),
    ('quarter turn right', 'rotate', {'direction': 'cw', 'deg': 90}),
    ('how much battery', 'battery', {}), ('batterie', 'battery', {}),
])
def test_commands(text, intent, params):
    if intent is None:      # 1.5 m is over the cap: covered below
        assert parse(text, DEVS).reason == 'too_far'
        return
    _ok(text, intent, params)


@pytest.mark.parametrize('text,reason', [
    ('', 'empty'), ('   ', 'empty'), ('fly to the kitchen', 'not_understood'), ('hello there', 'not_understood'),
    ('bonjour', 'not_understood'), ('open the pod bay doors', 'not_understood'),
    ('go forward two metres', 'too_far'), ('avance de deux mètres', 'too_far'), ('go up 101 centimetres', 'too_far'),
    ('go up 10 centimetres', 'too_small'), ('up 5', 'unit_needed'),
    ('turn left 180 degrees', 'too_much_rotation'), ('turn around', 'too_much_rotation'),
    ('demi-tour', 'too_much_rotation'), ('turn right 91 degrees', 'too_much_rotation'),
    ("don't take off", 'negated'), ('do not land', 'negated'), ('ne décolle pas', 'negated'),
    ("n'atterris pas", 'negated'), ('never go up', 'negated'),
    ('take off and go up', 'several_commands'), ('go up and go left', 'several_commands'),
    ('do a flip', 'flip_off'), ('backflip', 'flip_off'), ('take a photo', 'unsupported'),
    ('emergency', 'emergency_phrase'), ('urgence', 'emergency_phrase'),
    ('land C5B142 and F014A0', 'ambiguous_device'), ('tello c5b143 land', 'unknown_device'),
])
def test_refusals(text, reason):
    _no(text, reason)


def test_stop_and_land_win_over_everything():
    _ok('take off and land', 'land')
    _ok('go up and stop', 'stop')
    _ok('stop and land', 'stop')
    _ok('emergency stop', 'emergency')


def test_emergency_never_from_stop_alone():
    assert parse('stop', DEVS).intent == 'stop'
    assert parse('please stop now', DEVS).intent == 'stop'


def test_device_names_full_tail_and_spelled():
    _ok('Tello C5B142 take off', 'takeoff', device='device5')
    _ok('tello-f014a0 land', 'land', device='device6')
    _ok('c5b142 go up fifty centimetres', 'move', {'direction': 'up', 'cm': 50}, 'device5')
    _ok('F 0 1 4 A 0 land', 'land', device='device6')


def test_abort_word_only_as_whole_utterance():
    for t in ('abort', 'cancel', 'annule', 'annuler', 'abort please', 'cancel everything'):
        assert parse(t, DEVS).intent == 'abort', t
    assert parse('cancel the takeoff and go up', DEVS).intent != 'abort'
    for t in ('yes', 'oui', 'confirm', 'no', 'non'):         # no confirmation words any more
        assert not parse(t, DEVS).ok, t


def test_limits_are_configurable():
    assert parse('go up 150 centimetres', DEVS, Limits(max_cm=200)).ok
    assert not parse('go up 150 centimetres', DEVS, Limits(max_cm=100)).ok
    assert parse('turn left 120 degrees', DEVS, Limits(max_deg=180)).ok


def test_never_returns_sdk_text():
    p = parse('sdk command takeoff; flip f; rc 100 100 100 100', DEVS)
    assert not p.ok
    p = parse('send the string rc 100 100 100 100', DEVS)
    assert not p.ok
