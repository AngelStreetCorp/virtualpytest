"""Safe executor for Tello voice commands (TASK-160).

``VoiceExecutor.handle`` turns one transcript into at most one controller command. Order of checks (task doc rules):

1. parse (``voice_grammar``): allow-list only, nothing understood = nothing sent;
2. the drone must be the one the caller holds under Take Control (device lock, rule 5);
3. stop / abort / land / emergency go straight out, no confirmation, no cooldown. ``stop`` also tells the client to
   close the microphone; ``abort`` drops any command of that drone still being processed (owner, 2026-10-23: no
   confirmations anywhere, an abort word works at any moment);
4. battery is read before takeoff and moves; no reading (dropped link) = refusal (rule 3);
5. the command goes to the controller's high-level ``execute_command`` (which keeps ``_send_guarded``, the room box,
   the ceiling and the battery floor); never raw SDK text.

The three I/O edges are injected (``send``, ``holds_lock``, ``audit``) so tests run against a fake host.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from shared.src.lib.drone.voice_grammar import Limits, Parsed, parse

BAT_TAKEOFF_MIN = 40       # same as the controller's SafetyLimits.bat_takeoff
BAT_MOVE_MIN = 25          # a few points above the controller's landing floor (bat_land 20)
STOP_RC = {'lr': 0, 'fb': 0, 'ud': 0, 'yaw': 0}   # hover: the controller has no stop command, rc 0 0 0 0 is one

Send = Callable[[str, str, str, dict[str, Any]], dict[str, Any]]
HoldsLock = Callable[[str, str, dict[str, Any]], bool]
Audit = Callable[[dict[str, Any]], None]


@dataclass
class VoiceSettings:
    max_cm: int = 100
    max_deg: int = 90
    emergency_devices: frozenset = field(default_factory=frozenset)   # opt-in per device, off by default


# --- replies (EN / FR) ------------------------------------------------------------------------------------------

_T: dict[str, dict[str, str]] = {
    'en': {
        'empty': "I heard nothing. Nothing sent.",
        'not_understood': "I did not understand. Nothing sent.",
        'negated': "That sounded like a \"don't\". Nothing sent.",
        'several_commands': "One command at a time. Nothing sent.",
        'ambiguous_device': "Which drone? Name only one. Nothing sent.",
        'unknown_device': "I do not know that drone. Nothing sent.",
        'wrong_device': "You hold {held}, not that drone. Nothing sent.",
        'emergency_phrase': "Say \"emergency stop\" to cut the motors. Nothing sent.",
        'emergency_off': "Emergency stop by voice is off for this drone. Say \"land\" or use the button. Nothing sent.",
        'too_far': "{cm} cm is over the {max} cm voice limit. Nothing sent.",
        'too_small': "That is below the minimum. Nothing sent.",
        'too_much_rotation': "{deg} degrees is over the {max} degree voice limit. Nothing sent.",
        'unit_needed': "Say the distance with its unit, for example fifty centimetres. Nothing sent.",
        'flip_off': "Flips by voice are off. Nothing sent.",
        'unsupported': "The drone cannot do that by voice. Nothing sent.",
        'no_lock': "Take control of this drone first. Nothing sent.",
        'no_device': "No drone selected. Nothing sent.",
        'no_reading': "I cannot read the drone's battery, so I do not move. Nothing sent.",
        'battery_low': "Battery {bat} percent is below the {min} percent minimum. Nothing sent.",
        'sent_takeoff': "Taking off.",
        'sent_land': "Landing.",
        'sent_stop': "Hovering.",
        'sent_abort': "Aborted.",
        'aborted': "Aborted. Nothing sent.",
        'sent_emergency': "Motors cut.",
        'sent_move': "Moved {direction} {cm} cm.",
        'sent_rotate': "Turned {direction} {deg} degrees.",
        'battery': "Battery {bat} percent.",
        'refused_by_drone': "The drone refused: {error}",
        'failed': "Command failed: {error}",
        'dir_up': 'up', 'dir_down': 'down', 'dir_forward': 'forward', 'dir_back': 'back',
        'dir_left': 'left', 'dir_right': 'right', 'dir_cw': 'right', 'dir_ccw': 'left',
    },
    'fr': {
        'empty': "Je n'ai rien entendu. Rien envoyé.",
        'not_understood': "Je n'ai pas compris. Rien envoyé.",
        'negated': "Cela ressemblait à une négation. Rien envoyé.",
        'several_commands': "Une seule commande à la fois. Rien envoyé.",
        'ambiguous_device': "Quel drone ? Nommez-en un seul. Rien envoyé.",
        'unknown_device': "Je ne connais pas ce drone. Rien envoyé.",
        'wrong_device': "Vous contrôlez {held}, pas ce drone. Rien envoyé.",
        'emergency_phrase': "Dites « arrêt d'urgence » pour couper les moteurs. Rien envoyé.",
        'emergency_off': "L'arrêt d'urgence vocal est désactivé pour ce drone. Dites « atterris » ou utilisez le bouton. Rien envoyé.",
        'too_far': "{cm} cm dépasse la limite vocale de {max} cm. Rien envoyé.",
        'too_small': "C'est en dessous du minimum. Rien envoyé.",
        'too_much_rotation': "{deg} degrés dépasse la limite vocale de {max} degrés. Rien envoyé.",
        'unit_needed': "Dites la distance avec son unité, par exemple cinquante centimètres. Rien envoyé.",
        'flip_off': "Les flips vocaux sont désactivés. Rien envoyé.",
        'unsupported': "Le drone ne peut pas faire cela à la voix. Rien envoyé.",
        'no_lock': "Prenez d'abord le contrôle de ce drone. Rien envoyé.",
        'no_device': "Aucun drone sélectionné. Rien envoyé.",
        'no_reading': "Je ne peux pas lire la batterie du drone, je ne bouge pas. Rien envoyé.",
        'battery_low': "Batterie à {bat} % sous le minimum de {min} %. Rien envoyé.",
        'sent_takeoff': "Décollage.",
        'sent_land': "Atterrissage.",
        'sent_stop': "Stationnaire.",
        'sent_abort': "Annulé.",
        'aborted': "Annulé. Rien envoyé.",
        'sent_emergency': "Moteurs coupés.",
        'sent_move': "Déplacé {direction} de {cm} cm.",
        'sent_rotate': "Tourné {direction} de {deg} degrés.",
        'battery': "Batterie à {bat} %.",
        'refused_by_drone': "Le drone a refusé : {error}",
        'failed': "Commande échouée : {error}",
        'dir_up': 'vers le haut', 'dir_down': 'vers le bas', 'dir_forward': 'en avant', 'dir_back': 'en arrière',
        'dir_left': 'à gauche', 'dir_right': 'à droite', 'dir_cw': 'à droite', 'dir_ccw': 'à gauche',
    },
}


class VoiceExecutor:
    def __init__(self, send: Send, holds_lock: HoldsLock, audit: Audit | None = None,
                 settings: VoiceSettings | None = None, clock: Callable[[], float] = time.monotonic):
        self._send = send
        self._holds_lock = holds_lock
        self._audit = audit or (lambda event: None)
        self.settings = settings or VoiceSettings()
        self._clock = clock
        self._gen: dict[tuple[str, str], int] = {}     # bumped by every abort / stop
        self._mutex = threading.Lock()

    # ---- text -------------------------------------------------------------------------------------------------

    @staticmethod
    def _say(lang: str, key: str, **kw: Any) -> str:
        table = _T.get(lang if lang in _T else 'en')
        return table.get(key, _T['en'].get(key, key)).format(**kw)

    # ---- entry point ------------------------------------------------------------------------------------------

    def handle(self, *, transcript: str, lang: str, host_name: str, device_id: str,
               devices: Sequence[dict[str, Any]], caller: dict[str, Any], plan_only: bool = False) -> dict[str, Any]:
        """One transcript -> one decision. ``plan_only``: a takeoff / move / turn is not sent but returned as a plan
        (decision 'plan', with its readback ``label``) for the client to read back and then ``run``; everything else
        (stop, abort, land, battery, refusals) is final at once."""
        lang = lang if lang in _T else 'en'
        parsed = parse(transcript, devices, Limits(self.settings.max_cm, self.settings.max_deg))
        out = self._decide(parsed, lang, host_name, device_id, devices, caller, plan_only)
        out.update({'transcript': transcript, 'lang': lang, 'parsed': parsed.as_dict()})
        if parsed.intent == 'stop':
            out['listening'] = False      # the client closes the microphone whatever the device answered
        elif parsed.intent == 'abort':
            out['listening'] = True
        self._record(host_name, device_id, caller, out)
        return out

    def _record(self, host_name: str, device_id: str, caller: dict[str, Any], out: dict[str, Any]) -> None:
        # Transcript, parsed command, decision and the drone's reply; raw audio is never stored (rule 7).
        try:
            self._audit({'action': 'drone.voice', 'host_name': host_name, 'device_id': device_id,
                         'caller': {k: caller.get(k) for k in ('user_id', 'user_name')},
                         'transcript': out.get('transcript'), 'parsed': out.get('parsed'),
                         'decision': out.get('decision'), 'reason': out.get('reason'),
                         'drone_reply': (out.get('result') or {}).get('reply'),
                         'battery': out.get('battery')})
        except Exception as exc:  # noqa: BLE001 - the audit must never break a flight command
            print(f"[drone_voice] audit failed: {exc}")

    # ---- decision ---------------------------------------------------------------------------------------------

    def _refuse(self, lang: str, reason: str, **kw: Any) -> dict[str, Any]:
        return {'success': False, 'decision': 'refused', 'reason': reason, 'reply': self._say(lang, reason, **kw)}

    def _decide(self, parsed: Parsed, lang: str, host_name: str, device_id: str,
                devices: Sequence[dict[str, Any]], caller: dict[str, Any], plan_only: bool = False) -> dict[str, Any]:
        if not parsed.ok and parsed.reason in ('empty',):
            return self._refuse(lang, parsed.reason)
        if not device_id:
            return self._refuse(lang, 'no_device')
        if parsed.device_id and parsed.device_id != device_id:
            held = next((d.get('device_name') or d.get('name') for d in devices if str(d.get('device_id')) == device_id),
                        device_id)
            return self._refuse(lang, 'wrong_device', held=held)
        if not parsed.ok:
            return self._refuse(lang, parsed.reason, **parsed.detail)
        if not self._holds_lock(host_name, device_id, caller):
            return self._refuse(lang, 'no_lock')

        intent, params = parsed.intent, parsed.params

        # stop / abort / land / emergency win: no queue, no confirmation, no cooldown, no battery read.
        if intent in ('stop', 'abort'):
            with self._mutex:
                self._gen[(host_name, device_id)] = self._gen.get((host_name, device_id), 0) + 1
            return self._dispatch(lang, host_name, device_id, 'rc', STOP_RC, 'sent_' + intent)
        if intent in ('land', 'emergency'):
            if intent == 'emergency' and device_id not in self.settings.emergency_devices:
                return self._refuse(lang, 'emergency_off')
            return self._dispatch(lang, host_name, device_id, intent, {}, 'sent_' + intent)

        if intent == 'battery':
            bat = self._battery(host_name, device_id)
            if bat is None:
                return self._refuse(lang, 'no_reading')
            return {'success': True, 'decision': 'answered', 'battery': bat, 'reply': self._say(lang, 'battery', bat=bat)}

        with self._mutex:
            gen = self._gen.get((host_name, device_id), 0)
        if plan_only:
            return {'success': True, 'decision': 'plan', 'intent': intent, 'params': dict(params), 'gen': gen,
                    'label': self._label(lang, intent, params)}
        return self._run_checked(lang, host_name, device_id, intent, params, gen)

    def run(self, *, lang: str, host_name: str, device_id: str, intent: str, params: dict[str, Any], gen: int,
            caller: dict[str, Any]) -> dict[str, Any]:
        """Execute a plan returned by ``handle(plan_only=True)``. The lock is checked again and an abort / stop that
        arrived since the plan was made (``gen`` moved) drops it."""
        lang = lang if lang in _T else 'en'
        if intent not in ('takeoff', 'move', 'rotate'):
            out = self._refuse(lang, 'not_understood')
        elif not self._holds_lock(host_name, device_id, caller):
            out = self._refuse(lang, 'no_lock')
        else:
            out = self._run_checked(lang, host_name, device_id, intent, dict(params), gen)
        out.update({'lang': lang, 'parsed': {'intent': intent, 'params': params}})
        self._record(host_name, device_id, caller, out)
        return out

    def _label(self, lang: str, intent: str, params: dict[str, Any]) -> str:
        """The short phrase read back to the speaker before the command runs."""
        fr = lang == 'fr'
        if intent == 'takeoff':
            return 'Décoller' if fr else 'Take off'
        d = self._say(lang, 'dir_' + params['direction'])
        if intent == 'move':
            return f"Déplacer {d} de {params['cm']} cm" if fr else f"Move {d} {params['cm']} cm"
        return f"Tourner {d} de {params['deg']} degrés" if fr else f"Turn {d} {params['deg']} degrees"

    # ---- sending ----------------------------------------------------------------------------------------------

    def _battery(self, host_name: str, device_id: str) -> int | None:
        try:
            res = self._send(host_name, device_id, 'get_telemetry', {}) or {}
        except Exception:  # noqa: BLE001 - a dropped link is "no reading"
            return None
        tel = res.get('telemetry') or (res.get('output_data') or {}).get('telemetry') or res
        bat = tel.get('bat') if isinstance(tel, dict) else None
        try:
            return int(bat) if bat is not None else None
        except (TypeError, ValueError):
            return None

    def _run_checked(self, lang: str, host_name: str, device_id: str, intent: str,
                     params: dict[str, Any], gen: int) -> dict[str, Any]:
        """takeoff / move / rotate: battery first (a missing reading refuses), then the controller."""
        floor = BAT_TAKEOFF_MIN if intent == 'takeoff' else BAT_MOVE_MIN
        bat = self._battery(host_name, device_id)
        if bat is None:
            return self._refuse(lang, 'no_reading')
        if bat < floor:
            out = self._refuse(lang, 'battery_low', bat=bat, min=floor)
            out['battery'] = bat
            return out
        with self._mutex:
            aborted = self._gen.get((host_name, device_id), 0) != gen
        if aborted:                      # an abort / stop arrived while this command was being processed
            return self._refuse(lang, 'aborted')
        if intent == 'takeoff':
            out = self._dispatch(lang, host_name, device_id, 'takeoff', {}, 'sent_takeoff')
        elif intent == 'move':
            out = self._dispatch(lang, host_name, device_id, 'move', dict(params), 'sent_move',
                                 direction=self._say(lang, 'dir_' + params['direction']), cm=params['cm'])
        else:
            out = self._dispatch(lang, host_name, device_id, 'rotate', dict(params), 'sent_rotate',
                                 direction=self._say(lang, 'dir_' + params['direction']), deg=params['deg'])
        out['battery'] = bat
        return out

    def _dispatch(self, lang: str, host_name: str, device_id: str, command: str, params: dict[str, Any],
                  ok_key: str, **fmt: Any) -> dict[str, Any]:
        try:
            res = self._send(host_name, device_id, command, params) or {}
        except Exception as exc:  # noqa: BLE001 - reported to the speaker, never raised
            return {'success': False, 'decision': 'failed', 'reason': 'failed',
                    'reply': self._say(lang, 'failed', error=str(exc)[:120])}
        if res.get('success'):
            return {'success': True, 'decision': 'sent', 'command': command, 'result': res,
                    'reply': self._say(lang, ok_key, **fmt)}
        error = str(res.get('error') or res.get('reason') or 'unknown')
        key = 'refused_by_drone' if res.get('blocked') else 'failed'
        return {'success': False, 'decision': 'refused' if res.get('blocked') else 'failed', 'reason': key,
                'command': command, 'result': res, 'reply': self._say(lang, key, error=error)}


# ---------------------------------------------------------------------------------------------------------------
# lock rule (task doc rule 5)


def holds_lock(lock_info: dict[str, Any] | None, caller: dict[str, Any]) -> bool:
    """True only when a lock exists and it is the caller's own (session or verified user). A free device is NOT ok."""
    if not lock_info:
        return False
    sessions = {s for s in (caller.get('session_ids') or []) if s}
    if lock_info.get('owner_session_id') in sessions:
        return True
    from backend_server.src.lib.utils.lock_utils import _shared_user_ids
    user = caller.get('user_id')
    # the built-in default id is shared by every API-key / anonymous caller: not "the same person"
    return bool(user) and str(user) not in _shared_user_ids() and lock_info.get('owner_user_id') == user


def is_drone_phrase(parsed: Parsed) -> bool:
    """Should the Atlas voice path hand this phrase to the drone executor instead of the model?

    A drone command or a drone-shaped refusal (too far, negated, flip...) belongs to the executor and is answered on
    the spot; anything else stays Atlas's.
    """
    if parsed.ok:
        return True
    return parsed.reason not in ('not_understood', 'empty', 'unknown_device')
