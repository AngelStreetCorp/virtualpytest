"""Voice actions for the device the user holds under Take Control (TASK-160, phase 2).

Any device: the spoken command is matched to one of the device's OWN listed actions (``device_action_types``, the same
list ``list_actions`` / ``execute_device_action`` use) and run through ``/host/action/executeBatch``. The model only picks
an id from that list; it never writes a command. A Tello keeps its stricter grammar and limits (``drone_voice``) as a
free, instant first stage and is never sent through the model.

Two steps so the client can read the command back before it runs:

- ``plan``: parse / classify, check the lock, store the plan server-side, return a short ``label`` to read back;
- ``run``: execute a stored plan by id (the client never sends a command), unless an abort / stop arrived in between.

``stop`` and ``abort`` are final at once (no plan, no readback): they bump the device's generation, so any plan or command
still being processed for it is dropped, and a Tello is told to hover.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

PLAN_TTL_S = 30.0
# Never offered to a voice command whatever the device lists: raw SDK text, reconfiguration, pairing, motors off.
BLOCKED_COMMANDS = frozenset({'emergency', 'sdk', 'configure', 'link', 'start_pairing', 'get_telemetry'})
_MAX_ACTIONS = 120

_LOCK = threading.Lock()
_PLANS: dict[str, dict[str, Any]] = {}
_GEN: dict[tuple[str, str], int] = {}


def flatten_actions(device_data: dict[str, Any]) -> list[dict[str, Any]]:
    """The device's actions a voice command may use: id, label, command, params, action_type. Actions that need a
    typed value (``requiresInput``) and blocked commands are left out."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for category, actions in (device_data.get('device_action_types') or {}).items():
        for a in actions or []:
            if not isinstance(a, dict) or a.get('requiresInput') or a.get('command') in BLOCKED_COMMANDS:
                continue
            command = a.get('command')
            if not command:
                continue
            aid = str(a.get('id') or f"{category}:{command}:{a.get('label') or ''}")
            if aid in seen:
                continue
            seen.add(aid)
            out.append({'id': aid, 'label': str(a.get('label') or command), 'command': command,
                        'params': dict(a.get('params') or {}), 'action_type': a.get('action_type') or category})
            if len(out) >= _MAX_ACTIONS:
                return out
    return out


def sanitize_params(defaults: dict[str, Any], given: Any) -> dict[str, Any]:
    """The listed parameters, a value changed only when the key is declared and it converts to the declared type."""
    out = dict(defaults)
    if not isinstance(given, dict):
        return out
    for key, value in given.items():
        if key not in defaults or isinstance(value, (dict, list)):
            continue
        try:
            default = defaults[key]
            if isinstance(default, bool):
                out[key] = bool(value)
            elif isinstance(default, int):
                out[key] = int(float(value))
            elif isinstance(default, float):
                out[key] = float(value)
            else:
                out[key] = str(value)[:80]
        except (TypeError, ValueError):
            continue
    return out


def _caller_key(caller: dict[str, Any]) -> str:
    return f"{caller.get('user_id') or ''}|{','.join(sorted(s for s in caller.get('session_ids') or [] if s))}"


def generation(host_name: str, device_id: str) -> int:
    with _LOCK:
        return _GEN.get((host_name, device_id), 0)


def abort_device(host_name: str, device_id: str) -> None:
    """An abort / stop: bump the generation, so every plan made before it is dropped when it is run."""
    with _LOCK:
        _GEN[(host_name, device_id)] = _GEN.get((host_name, device_id), 0) + 1


def _store(plan: dict[str, Any]) -> str:
    pid = uuid.uuid4().hex[:12]
    now = time.monotonic()
    with _LOCK:
        for old in [p for p, v in _PLANS.items() if now - v['created'] > PLAN_TTL_S]:
            _PLANS.pop(old, None)
        _PLANS[pid] = {**plan, 'created': now}
    return pid


def _refused(reason: str, reply: str) -> dict[str, Any]:
    return {'success': False, 'decision': 'refused', 'reason': reason, 'reply': reply}


_REPLIES = {
    'en': {'no_lock': "Take control of this device first. Nothing sent.", 'not_understood': "I did not understand. Nothing sent.",
           'no_actions': "This device has no action I can do by voice. Nothing sent.", 'model': "The voice model is not available. Nothing sent.",
           'stop': "Stopped.", 'abort': "Aborted.", 'gone': "That command expired. Nothing sent.",
           'aborted': "Aborted. Nothing sent.", 'done': "Done.", 'failed': "Failed: {error}"},
    'fr': {'no_lock': "Prenez d'abord le contrôle de cet appareil. Rien envoyé.", 'not_understood': "Je n'ai pas compris. Rien envoyé.",
           'no_actions': "Cet appareil n'a aucune action possible à la voix. Rien envoyé.", 'model': "Le modèle vocal n'est pas disponible. Rien envoyé.",
           'stop': "Arrêté.", 'abort': "Annulé.", 'gone': "Cette commande a expiré. Rien envoyé.",
           'aborted': "Annulé. Rien envoyé.", 'done': "Terminé.", 'failed': "Échec : {error}"},
}


def say(lang: str, key: str, **kw: Any) -> str:
    return _REPLIES.get(lang if lang in _REPLIES else 'en')[key].format(**kw)


def plan(*, text: str, lang: str, host_name: str, device_id: str, host_info: dict[str, Any], caller: dict[str, Any],
         team_id: str, holds_lock, drone, classify) -> dict[str, Any]:
    """One utterance -> a decision. ``holds_lock(host, device, caller)``, ``drone`` (a ``VoiceExecutor``) and ``classify``
    (``voice_command.classify``) are injected so tests need no server."""
    lang = lang if lang in _REPLIES else 'en'
    devices = host_info.get('devices') or []
    device = next((d for d in devices if str(d.get('device_id')) == device_id), None)
    if device is None:
        return _refused('no_device', say(lang, 'not_understood'))
    if not holds_lock(host_name, device_id, caller):
        return _refused('no_lock', say(lang, 'no_lock'))

    is_tello = str(device.get('device_model') or '').lower() == 'tello'
    from shared.src.lib.drone.voice_grammar import parse
    heard = parse(text, [])
    word = heard.intent if heard.ok else ''
    if word in ('stop', 'abort'):
        abort_device(host_name, device_id)
        listening = word == 'abort'
        if is_tello:                                    # the drone's safe stop (hover) and its own audit record
            out = drone.handle(transcript=text, lang=lang, host_name=host_name, device_id=device_id,
                               devices=_tellos(devices), caller=caller)
            out['listening'] = listening
            return out
        return {'success': True, 'decision': word, 'reply': say(lang, word), 'listening': listening}

    if is_tello:
        out = drone.handle(transcript=text, lang=lang, host_name=host_name, device_id=device_id,
                           devices=_tellos(devices), caller=caller, plan_only=True)
        if out.get('decision') == 'plan':
            out['plan_id'] = _store({'kind': 'drone', 'host_name': host_name, 'device_id': device_id, 'lang': lang,
                                     'caller': _caller_key(caller), 'intent': out['intent'], 'params': out['params'],
                                     'gen': out['gen'], 'mgen': generation(host_name, device_id), 'label': out['label']})
        return out

    actions = flatten_actions(device)
    if not actions:
        return _refused('no_actions', say(lang, 'no_actions'))
    gen = generation(host_name, device_id)
    names = [str(d.get('device_name') or d.get('device_id')) for d in devices]
    current = str(device.get('device_name') or device_id)
    command = classify(lang=lang, text=text, devices=[{'device_name': n} for n in names], current_device=current,
                       team_id=team_id, actions=actions)
    if command.get('error'):
        return _refused('model', say(lang, 'model'))
    args = command.get('args') or {}
    if command.get('tool') != 'device_action':
        return _refused('not_understood', say(lang, 'not_understood'))
    chosen = next((a for a in actions if a['id'] == args.get('action')), None)
    if chosen is None:                                  # not on the device's list: never guessed
        return _refused('not_understood', say(lang, 'not_understood'))
    params = sanitize_params(chosen['params'], args.get('params'))
    pid = _store({'kind': 'action', 'host_name': host_name, 'device_id': device_id, 'lang': lang,
                  'caller': _caller_key(caller), 'action': {**chosen, 'params': params}, 'mgen': gen,
                  'label': chosen['label']})
    return {'success': True, 'decision': 'plan', 'plan_id': pid, 'label': chosen['label']}


def _tellos(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{'device_id': d.get('device_id'), 'device_name': d.get('device_name'), 'name': d.get('device_name')}
            for d in devices if str(d.get('device_model') or '').lower() == 'tello']


def run(*, plan_id: str, caller: dict[str, Any], team_id: str, holds_lock, drone, execute) -> dict[str, Any]:
    """Execute a stored plan. ``execute(host_name, device_id, action, team_id)`` runs one action on the host."""
    with _LOCK:
        stored = _PLANS.pop(plan_id, None)
    lang = (stored or {}).get('lang', 'en')
    if stored is None or time.monotonic() - stored['created'] > PLAN_TTL_S:
        return _refused('gone', say(lang, 'gone'))
    if stored['caller'] != _caller_key(caller):
        return _refused('gone', say(lang, 'gone'))
    host_name, device_id = stored['host_name'], stored['device_id']
    if generation(host_name, device_id) != stored['mgen']:          # an abort / stop since the plan was made
        return _refused('aborted', say(lang, 'aborted'))
    if not holds_lock(host_name, device_id, caller):
        return _refused('no_lock', say(lang, 'no_lock'))
    if stored['kind'] == 'drone':
        return drone.run(lang=lang, host_name=host_name, device_id=device_id, intent=stored['intent'],
                         params=stored['params'], gen=stored['gen'], caller=caller)
    try:
        res = execute(host_name, device_id, stored['action'], team_id) or {}
    except Exception as exc:  # noqa: BLE001 - reported to the speaker, never raised
        return {'success': False, 'decision': 'failed', 'reason': 'failed',
                'reply': say(lang, 'failed', error=str(exc)[:120])}
    ok = bool(res.get('success'))
    return {'success': ok, 'decision': 'sent' if ok else 'failed', 'reason': '' if ok else 'failed',
            'reply': say(lang, 'done') if ok else say(lang, 'failed', error=str(res.get('error') or 'unknown')[:120])}
