"""Voice grammar for the Tello (TASK-160): transcript text -> one allow-listed command, or a refusal.

Pure: no I/O, no model. English and French. The output is never SDK text: only an intent from ``INTENTS`` and
validated parameters, which the server executor maps to the controller's high-level commands.

Safety (task doc "Safety rules" 1-3):
- anything not understood is a refusal with a reason, never a guess;
- a drone named in the transcript is matched exactly (full name, SSID tail such as ``C5B142``); two matches = ambiguous;
- ``emergency`` needs the explicit phrase ("emergency stop", "arret d'urgence"); "stop" alone is a hover;
- stop > land > emergency > the rest when several commands are spoken; two flight commands at once are refused;
- a negated verb ("don't take off", "ne decolle pas") is refused, never executed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

MIN_MOVE_CM = 20
MAX_ROTATE_DEG = 360

# Defaults when the speaker gives no amount ("go up").
DEFAULT_CM = {'up': 30, 'down': 30, 'forward': 50, 'back': 50, 'left': 50, 'right': 50}
DEFAULT_DEG = 30


@dataclass
class Limits:
    max_cm: int = 100
    max_deg: int = 90


@dataclass
class Parsed:
    ok: bool
    intent: str = 'unknown'            # takeoff land stop abort emergency move rotate battery
    params: dict[str, Any] = field(default_factory=dict)
    device_id: str | None = None    # the drone named in the transcript, if any
    reason: str = ''                   # machine key of a refusal, see REASONS
    detail: dict[str, Any] = field(default_factory=dict)
    text: str = ''                     # normalised transcript

    def as_dict(self) -> dict[str, Any]:
        return {'ok': self.ok, 'intent': self.intent, 'params': self.params, 'device_id': self.device_id,
                'reason': self.reason, 'detail': self.detail}


# ---------------------------------------------------------------------------------------------------------------
# normalisation

def normalize(text: str) -> str:
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace('°', ' degrees ')
    text = re.sub(r"[’']", ' ', text)
    text = re.sub(r'(?<=\d)[.,](?=\d)', '\x00', text)          # keep decimal separators between digits
    text = re.sub(r'[^a-z0-9\x00]+', ' ', text)
    text = text.replace('\x00', '.')
    return re.sub(r'\s+', ' ', text).strip()


# ---------------------------------------------------------------------------------------------------------------
# numbers (English and French words, digits)

_EN_UNITS = {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8,
             'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
             'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20, 'thirty': 30,
             'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90}
_FR_UNITS = {'zero': 0, 'un': 1, 'une': 1, 'deux': 2, 'trois': 3, 'quatre': 4, 'cinq': 5, 'six': 6, 'sept': 7,
             'huit': 8, 'neuf': 9, 'dix': 10, 'onze': 11, 'douze': 12, 'treize': 13, 'quatorze': 14, 'quinze': 15,
             'seize': 16, 'vingt': 20, 'vingts': 20, 'trente': 30, 'quarante': 40, 'cinquante': 50, 'soixante': 60}
_NUMBER_WORDS = {**_EN_UNITS, **_FR_UNITS}
_SKIP_IN_NUMBER = {'and', 'et'}
_HUNDREDS = ('hundred', 'cent', 'cents')


def _number_at(tokens: Sequence[str], i: int) -> tuple[float | None, int]:
    """Parse a number starting at ``tokens[i]``; (value, tokens used) or (None, 0)."""
    tok = tokens[i]
    if re.fullmatch(r'\d+(\.\d+)?', tok):
        return float(tok), 1
    current, used, j = 0, 0, i
    seen = False
    while j < len(tokens):
        t = tokens[j]
        if t in _SKIP_IN_NUMBER and seen and j + 1 < len(tokens) and (
                tokens[j + 1] in _NUMBER_WORDS or tokens[j + 1] in _HUNDREDS):
            j += 1
            continue
        if t in _HUNDREDS:
            current = (current or 1) * 100
        elif t in _NUMBER_WORDS:
            if t in ('vingt', 'vingts') and current == 4:
                current = 80                                   # quatre-vingt
            else:
                current += _NUMBER_WORDS[t]
        else:
            break
        seen = True
        used = j - i + 1
        j += 1
    if not seen:
        return None, 0
    return float(current), used


# unit words -> (kind, cm per unit) / degrees
_CM_UNITS = {'cm': 1, 'centimetre': 1, 'centimetres': 1, 'centimeter': 1, 'centimeters': 1}
_M_UNITS = {'m': 100, 'metre': 100, 'metres': 100, 'meter': 100, 'meters': 100}
_DEG_UNITS = {'degree', 'degrees', 'deg', 'degre', 'degres'}


def _amounts(tokens: list[str]) -> dict[str, Any]:
    """First amount in the transcript: {'cm': n} / {'deg': n} / {'bare': n} / {} ; 'bad' on an unreadable one."""
    i = 0
    while i < len(tokens):
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ''
        # fractions of a metre / turn
        if t in ('half', 'demi', 'demie') and (nxt in _M_UNITS or (nxt == 'a' and i + 2 < len(tokens)
                                                                    and tokens[i + 2] in _M_UNITS)):
            return {'cm': 50.0}
        if t == 'un' and nxt == 'demi' and i + 2 < len(tokens) and tokens[i + 2] in _M_UNITS:
            return {'cm': 50.0}
        if t in ('quarter', 'quart') and nxt in ('turn', 'de'):
            return {'deg': 90.0}
        if t in ('half', 'demi') and nxt == 'turn' or t == 'demi' and nxt == 'tour':
            return {'deg': 180.0}
        if t == 'a' and nxt in _M_UNITS:
            return {'cm': 100.0}
        value, used = _number_at(tokens, i)
        if value is not None:
            unit = tokens[i + used] if i + used < len(tokens) else ''
            if unit in _CM_UNITS:
                return {'cm': value * _CM_UNITS[unit]}
            if unit in _M_UNITS:
                return {'cm': value * _M_UNITS[unit]}
            if unit in _DEG_UNITS:
                return {'deg': value}
            return {'bare': value}
        i += 1
    return {}


# ---------------------------------------------------------------------------------------------------------------
# vocabulary

_TAKEOFF = {'takeoff', 'decolle', 'decoller', 'decollez', 'decollage', 'liftoff'}
_LAND = {'land', 'landing', 'atterris', 'atterrir', 'atterrissez', 'atterrissage', 'atterri'}
_STOP = {'stop', 'hover', 'halt', 'freeze', 'arrete', 'arreter', 'arretez', 'stoppe', 'stoppez', 'arret'}
_BATTERY = {'battery', 'batterie', 'batteries'}
_FLIP = {'flip', 'flips', 'backflip', 'frontflip', 'salto'}
_UNSUPPORTED = {'photo', 'picture', 'video', 'record', 'selfie', 'filme', 'filmer', 'enregistre'}

_DIRECTIONS = {
    'up': 'up', 'rise': 'up', 'ascend': 'up', 'monte': 'up', 'monter': 'up', 'montez': 'up', 'higher': 'up',
    'down': 'down', 'descend': 'down', 'descends': 'down', 'descendre': 'down', 'descendez': 'down',
    'lower': 'down', 'baisse': 'down',
    'forward': 'forward', 'forwards': 'forward', 'ahead': 'forward', 'avance': 'forward', 'avancer': 'forward',
    'avancez': 'forward',
    'back': 'back', 'backward': 'back', 'backwards': 'back', 'reverse': 'back', 'recule': 'back', 'reculer': 'back',
    'reculez': 'back',
    'left': 'left', 'gauche': 'left',
    'right': 'right', 'droite': 'right',
}
_ROTATE_VERBS = {'turn', 'rotate', 'spin', 'pivot', 'pivote', 'pivoter', 'tourne', 'tourner', 'tournez', 'orient'}
_CLOCKWISE = {'clockwise': 'cw', 'horaire': 'cw'}
_COUNTER = {'counterclockwise': 'ccw', 'anticlockwise': 'ccw', 'antihoraire': 'ccw'}
_NEGATIONS = {'not', 'dont', 'don', 'never', 'no', 'pas', 'jamais', 'ne', 'n', 'without', 'sans', 'surtout'}
_ABORT_WORDS = {'abort', 'cancel', 'annule', 'annuler', 'annulation'}
REASONS = (
    'empty', 'not_understood', 'negated', 'several_commands', 'ambiguous_device', 'unknown_device',
    'emergency_phrase', 'too_far', 'too_small', 'too_much_rotation', 'unit_needed', 'flip_off', 'unsupported',
)


def _phrase(tokens: Sequence[str], *words: str) -> list[int]:
    n = len(words)
    return [i for i in range(len(tokens) - n + 1) if tuple(tokens[i:i + n]) == words]


def _negated(tokens: Sequence[str], i: int) -> bool:
    before = tokens[max(0, i - 2):i]
    after = tokens[i + 1:i + 3]
    return any(t in _NEGATIONS for t in before) or any(t in ('pas', 'jamais', 'not') for t in after)


# ---------------------------------------------------------------------------------------------------------------
# device naming

def match_devices(text: str, devices: Sequence[dict[str, Any]]) -> list[str]:
    """Ids of the devices whose name or SSID tail appears in the transcript (spelled letters are joined)."""
    squashed = text.replace(' ', '')
    found: list[str] = []
    for d in devices:
        names = {str(d.get('name') or d.get('device_name') or ''), str(d.get('ssid') or '')}
        aliases = set()
        for name in names:
            n = re.sub(r'[^a-z0-9]', '', normalize(name))
            if len(n) >= 6:
                aliases.add(n)
                aliases.add(n[-6:])
        if any(a and a in squashed for a in aliases):
            found.append(str(d.get('device_id')))
    return found


# ---------------------------------------------------------------------------------------------------------------
# the parser

def parse(transcript: str, devices: Sequence[dict[str, Any]] = (), limits: Limits | None = None) -> Parsed:
    limits = limits or Limits()
    text = normalize(transcript)
    if not text:
        return Parsed(False, reason='empty', text=text)
    tokens = text.split()
    result = Parsed(False, text=text)

    named = match_devices(text, devices)
    if len(named) > 1:
        return Parsed(False, reason='ambiguous_device', detail={'devices': named}, text=text)
    # A name-shaped word ("tello c5b142" spelt differently) that matches nothing is not substituted by another drone.
    squashed = text.replace(' ', '')
    if devices and not named and re.search(r'tello[a-z0-9]{6}', squashed) is not None:
        return Parsed(False, reason='unknown_device', text=text)
    device_id = named[0] if named else None

    # the abort word, as the whole utterance: stops whatever is being processed, listening stays on
    content = [t for t in tokens if t not in ('please', 'tello', 'drone', 'sil', 'vous', 'plait', 'stp', 'svp', 'it',
                                              'do', 'is', 'go', 'ahead', 'and', 'everything', 'tout')]
    if content and len(content) <= 2 and all(t in _ABORT_WORDS for t in content):
        return Parsed(True, 'abort', device_id=device_id, text=text)

    intents: dict[str, int] = {}                 # intent -> token index
    emergency_phrase = bool(_phrase(tokens, 'emergency', 'stop') or _phrase(tokens, 'arret', 'urgence')
                            or _phrase(tokens, 'arret', 'durgence') or _phrase(tokens, 'arret', 'd', 'urgence')
                            or _phrase(tokens, 'stop', 'urgence') or _phrase(tokens, 'emergency', 'land'))
    emergency_word = 'emergency' in tokens or 'urgence' in tokens or 'durgence' in tokens
    if emergency_phrase:
        idx = (_phrase(tokens, 'emergency', 'stop') or _phrase(tokens, 'emergency', 'land')
               or _phrase(tokens, 'arret', 'urgence') or _phrase(tokens, 'arret', 'durgence')
               or _phrase(tokens, 'arret', 'd', 'urgence') or _phrase(tokens, 'stop', 'urgence'))[0]
        if _negated(tokens, idx):
            return Parsed(False, reason='negated', text=text)
        intents['emergency'] = idx
    elif emergency_word:
        return Parsed(False, reason='emergency_phrase', text=text)

    for i, t in enumerate(tokens):
        if emergency_phrase and t in ('stop', 'arret', 'land'):
            continue
        if t in _TAKEOFF:
            intents.setdefault('takeoff', i)
        elif t in _LAND:
            intents.setdefault('land', i)
        elif t in _STOP:
            intents.setdefault('stop', i)
        elif t in _BATTERY:
            intents.setdefault('battery', i)
        elif t in _FLIP:
            intents.setdefault('flip', i)
        elif t in _UNSUPPORTED:
            intents.setdefault('unsupported', i)
    for i in _phrase(tokens, 'take', 'off') + _phrase(tokens, 'lift', 'off'):
        intents.setdefault('takeoff', i)

    direction_hits = [(i, _DIRECTIONS[t]) for i, t in enumerate(tokens) if t in _DIRECTIONS]
    # "en arriere" / "en avant"
    for i in _phrase(tokens, 'en', 'arriere'):
        direction_hits.append((i, 'back'))
    for i in _phrase(tokens, 'en', 'avant'):
        direction_hits.append((i, 'forward'))
    for i in _phrase(tokens, 'sens', 'horaire'):
        direction_hits.append((i, 'cw'))
    for i in _phrase(tokens, 'turn', 'around') + _phrase(tokens, 'demi', 'tour') + _phrase(tokens, 'half', 'turn'):
        direction_hits.append((i, 'around'))
    for i, t in enumerate(tokens):
        if t in _CLOCKWISE:
            direction_hits.append((i, 'cw'))
        if t in _COUNTER:
            direction_hits.append((i, 'ccw'))
    # 'back' after "come": "come back" is not a command we know -> still a move back; keep simple.
    amounts = _amounts(tokens)
    rotate_verb = any(t in _ROTATE_VERBS for t in tokens)
    wants_rotate = rotate_verb or 'deg' in amounts or any(d in ('cw', 'ccw', 'around') for _, d in direction_hits)

    if direction_hits:
        dirs = [d for _, d in direction_hits]
        if wants_rotate:
            rot = [d for d in dirs if d in ('left', 'right', 'cw', 'ccw', 'around')]
            if len(set(rot)) != 1:
                return Parsed(False, reason='not_understood' if not rot else 'several_commands', text=text)
            intents['rotate'] = direction_hits[0][0]
            d = rot[0]
            result.params['direction'] = {'left': 'ccw', 'right': 'cw', 'cw': 'cw', 'ccw': 'ccw', 'around': 'cw'}[d]
            if d == 'around':
                amounts = {'deg': 180.0}
        else:
            if len(set(dirs)) != 1:
                return Parsed(False, reason='several_commands', text=text)
            intents['move'] = direction_hits[0][0]
            result.params['direction'] = dirs[0]

    # which concrete phrase gave "flip"/"unsupported" matters only when nothing safer was said
    # priority: stop and land win over everything (task doc rule 3), then emergency
    for winner in ('stop', 'land'):
        if winner in intents:
            if _negated(tokens, intents[winner]):
                return Parsed(False, reason='negated', text=text)
            if 'emergency' in intents:
                continue
            return Parsed(True, winner, device_id=device_id, text=text)
    if 'emergency' in intents:
        return Parsed(True, 'emergency', device_id=device_id, text=text)

    if not intents:
        return Parsed(False, reason='not_understood', text=text)
    if len(intents) > 1:
        return Parsed(False, reason='several_commands', detail={'intents': sorted(intents)}, text=text)

    intent, idx = next(iter(intents.items()))
    if intent in ('takeoff', 'move', 'rotate', 'battery', 'flip', 'unsupported') and _negated(tokens, idx):
        return Parsed(False, reason='negated', text=text)

    if intent == 'flip':
        return Parsed(False, intent='flip', reason='flip_off', text=text)
    if intent == 'unsupported':
        return Parsed(False, intent='unsupported', reason='unsupported', text=text)
    if intent in ('takeoff', 'battery'):
        return Parsed(True, intent, device_id=device_id, text=text)

    if intent == 'move':
        direction = result.params['direction']
        cm = amounts.get('cm')
        if cm is None and 'bare' in amounts:
            bare = amounts['bare']
            if bare < MIN_MOVE_CM:
                return Parsed(False, intent, reason='unit_needed', detail={'direction': direction}, text=text)
            cm = bare
        if cm is None:
            if 'deg' in amounts:
                return Parsed(False, reason='not_understood', text=text)
            cm = float(DEFAULT_CM[direction])
        if cm < MIN_MOVE_CM:
            return Parsed(False, intent, reason='too_small', detail={'cm': round(cm), 'min': MIN_MOVE_CM}, text=text)
        if cm > limits.max_cm:
            return Parsed(False, intent, reason='too_far', detail={'cm': round(cm), 'max': limits.max_cm}, text=text)
        return Parsed(True, 'move', {'direction': direction, 'cm': round(cm)}, device_id, text=text)

    # rotate
    deg = amounts.get('deg')
    if deg is None and 'bare' in amounts:
        deg = amounts['bare']
    if deg is None:
        deg = float(DEFAULT_DEG)
    if deg < 1:
        return Parsed(False, intent, reason='too_small', detail={'deg': deg, 'min': 1}, text=text)
    if deg > limits.max_deg:
        return Parsed(False, intent, reason='too_much_rotation', detail={'deg': round(deg), 'max': limits.max_deg},
                      text=text)
    return Parsed(True, 'rotate', {'direction': result.params['direction'], 'deg': round(deg)}, device_id,
                  text=text)
