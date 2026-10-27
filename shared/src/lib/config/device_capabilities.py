"""
Device Capabilities Configuration

Device model to controller mappings and capabilities.
This module is in shared/ so it can be used by both backend_host and backend_server.
"""

import difflib
from typing import Optional, Tuple

# Remotes that drive the device from outside: an IR transmitter (lirc / a USB IR Toy
# over serial / a networked IRTrans box) or an emulated BLE remote. Any device we
# capture over HDMI or a camera can be wired to one, so every such model accepts all of
# them, and the host's .env decides: DEVICE{i}_IR_PATH → ir_remote, DEVICE{i}_IR_SERIAL →
# irtoy_remote, DEVICE{i}_IR_IP → irtrans_remote, DEVICE{i}_BLE_TYPE → bluetooth_remote.
# One that is not configured is skipped, so listing it costs nothing.
EXTERNAL_REMOTES = ['ir_remote', 'irtoy_remote', 'irtrans_remote', 'bluetooth_remote']

# Power the same way: a smart plug (Tapo), the client's power API or Wake-on-LAN can sit in
# front of any box we capture, so every such model accepts all three and the .env picks:
# DEVICE{i}_POWER_NAME tapo* + POWER_IP → tapo, DEVICE{i}_POWER_API_URL → api_power,
# DEVICE{i}_POWER_MAC → wol. One that is not configured is skipped.
EXTERNAL_POWER = ['tapo', 'api_power', 'wol']

# Device Model → Controllers Mapping
DEVICE_CONTROLLER_MAP = {
    'android_mobile': {
        'av': ['hdmi_stream'], 
        'remote': ['android_mobile'],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    'android_tv': {
        'av': ['hdmi_stream'],
        'remote': ['android_tv', *EXTERNAL_REMOTES],
        'desktop': [],
        'web': [],
        'power': EXTERNAL_POWER,
        'network': []
    },
    'android_tablet': {
        'av': ['hdmi_stream'],
        'remote': ['android_mobile', *EXTERNAL_REMOTES],
        'desktop': [],
        'web': [],
        'power': EXTERNAL_POWER,
        'network': []
    },
    # A paired phone running the VirtualPyTest app (features/mobile-app): frames arrive
    # over Socket.IO and are written to the slot's image file, so the AV side is the
    # ordinary ffmpeg capture folder; input goes through the phone's AccessibilityService.
    'phone_agent': {
        'av': ['hdmi_stream'],
        'remote': ['phone_agent'],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    # Fire TV running Fire OS (Amazon's Android): the Android TV adb remote and the android_tv family.
    'fire_tv_fireos': {
        'av': ['hdmi_stream'], 
        'remote': ['android_tv', *EXTERNAL_REMOTES],
        'desktop': [],
        'web': [],
        'power': EXTERNAL_POWER,
        'network': []
    },
    # Fire TV on Vega OS (Amazon's Linux TV OS, TASK-57): reached by the stock adb client
    # like a Fire OS stick, but there is no Android behind it, so the remote is the
    # Vega one (inputd-cli / vmsgr / vlcm) and there is no adb UI dump. Not in the
    # android_tv family: its apps and screens are not the Android TV ones.
    'fire_tv_vega': {
        'av': ['hdmi_stream'],
        'remote': ['vega', *EXTERNAL_REMOTES],
        'desktop': [],
        'web': [],
        'power': EXTERNAL_POWER,
        'network': []
    },
    'ios_mobile': {
        'av': ['hdmi_stream'], 
        'remote': ['appium'],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    # A phone in a cloud device farm (features/device-farm, TASK-20). The device is
    # allocated by the farm, so there is no capture card and no UDID: the feature's
    # frame pump writes WebDriver screenshots to the slot's DEVICE{i}_VIDEO image
    # file and the host's ffmpeg imagefile grabber makes HLS + captures from it —
    # which is why the AV controller is the ordinary hdmi_stream one, exactly as for
    # a paired phone. Model names use underscores only: controller_manager splits
    # DEVICE{i}_MODEL on the first dash to read a platform tag.
    'cloud_android_mobile': {
        'av': ['hdmi_stream'],
        'remote': ['appium_cloud'],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    'cloud_ios_mobile': {
        'av': ['hdmi_stream'],
        'remote': ['appium_cloud'],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    'stb': {
        'av': ['hdmi_stream'],
        'remote': EXTERNAL_REMOTES,
        'desktop': [],
        'web': [],
        'power': EXTERNAL_POWER,
        'network': []
    },
    'apple_tv': {
        'av': ['hdmi_stream'], 
        'remote': EXTERNAL_REMOTES,
        'desktop': [],
        'web': [],
        'power': EXTERNAL_POWER,
        'network': []
    },
    # TASK-71: an FX voice modem (Conexant CX93001, 0572:1349) on the host.
    # It is a telephone line, not a screen, so there is no `av` at all — the
    # whole device is its remote: pick up, hang up, dial, DTMF. The port comes
    # from DEVICE{i}_FX_PORT (/dev/fx1..fx4, named by udev).
    #
    # It deliberately reuses the `remote` slot rather than a new `telephony`
    # capability: that slot already carries the button panel,
    # /host/remote/executeCommand, execute_sequence's retry/failure actions and
    # the action executor's remote branch, so all of it works unchanged. A new
    # slot would need plumbing through each of those AND an edit to the
    # seven-slot builder in get_device_capabilities() below.
    'fx_dongle': {
        'av': [],
        'remote': ['fx'],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    'tizen': {
        'av': ['camera_stream'],
        # samsung_tizen = network websocket remote (samsungtvws). Listed first so a host
        # with DEVICE<N>_TIZEN_IP set uses it; the IR/BLE remotes stay as fallbacks for
        # hosts that drive the TV by hardware instead.
        'remote': ['samsung_tizen', *EXTERNAL_REMOTES],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    # Generic camera-captured device: anything filmed by a camera instead of tapped
    # over HDMI (a TV panel with no HDMI out, a kiosk, a phone in a rig). Use this
    # rather than 'tizen' unless the device under test really does run Tizen —
    # 'tizen' was the only camera_stream model for a long time, so it got used as a
    # stand-in for "camera", which is confusing and not what the name means.
    # Power is the STB set because the filmed device is usually a box on a socket.
    'camera': {
        'av': ['camera_stream'],
        'remote': EXTERNAL_REMOTES,
        'desktop': [],
        'web': [],
        'power': EXTERNAL_POWER,
        'network': []
    },
    'host_vnc': {
        'av': ['vnc_stream'],
        'remote': [],
        'desktop': ['bash', 'pyautogui'],
        'web': ['playwright'],
        'power': [],
        'network': []
    },
    # TASK-31: a non-device AV source that plays an RTSP / HLS / MJPEG feed
    # (IP camera, public test stream, IPTV). Loop + on-demand. Audio is
    # carried when the source has it, so 'audio' verification is exposed.
    # No remote / power / desktop / web — there is nothing to drive.
    'rtsp_video': {
        'av': ['rtsp_stream'],
        'remote': [],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    # TASK-31: a non-device AV source that plays a local .mp4 / .mkv / etc.
    # file or an HTTP(S) URL. Loop + on-demand. No audio by default
    # (the source codec may carry it, but we do not promise to capture it).
    'local_video': {
        'av': ['video_stream'],
        'remote': [],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    # TASK-32: a Ryze/DJI Tello. Its H.264 video is pushed over UDP to the host
    # (DEVICE{i}_VIDEO=udp://0.0.0.0:<video_port>), which vpt-stream ingests like any live
    # network feed (rtsp_stream, source type rtsp); flight commands go through the `tello`
    # remote (plain UDP SDK, every move guarded). No power, no IR/BLE.
    'tello': {
        'av': ['rtsp_stream'],
        'remote': ['tello'],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    # TASK-31: a Nintendo Switch. HDMI out of the dock -> MS2109 grabber (same
    # AV capture as `android_tv` / `host_vnc`); input through the `switch`
    # slot.
    'nintendo_switch': {
        'av': ['hdmi_stream'],
        'remote': [],
        'desktop': [],
        'web': [],
        'power': [],
        'network': [],
        # `bluetooth_procon`: the host emulates a Bluetooth Pro Controller
        # (vpt-procon daemon, nxbt). Works on a stock Switch, no custom
        # firmware. See docs/agent/devices/NINTENDO_SWITCH.md.
        'switch': ['bluetooth_procon'],
    },
    'web': {
        'av': [],
        'remote': [],
        'desktop': ['bash', 'pyautogui'],
        'web': ['playwright'],
        'power': [],
        'network': []
    },
    'runner_host': {
        'av': [],
        'remote': [],
        'desktop': ['bash'],
        'web': ['playwright'],
        'power': [],
        'network': []
    },
    'runner_android_mobile': {
        'av': [],
        'remote': ['android_mobile'],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    'runner_android_tablet': {
        'av': [],
        'remote': ['android_mobile'],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    },
    'runner_android_tv': {
        'av': [],
        'remote': ['android_tv'],
        'desktop': [],
        'web': [],
        'power': [],
        'network': []
    }
}

# Controller → Verification Capabilities
CONTROLLER_VERIFICATION_MAP = {
    'hdmi_stream': ['image', 'text', 'color', 'video', 'audio'],
    'camera_stream': ['image', 'text', 'color', 'video', 'audio'],
    'vnc_stream': ['image', 'text', 'color', 'video'],
    # TASK-31 — same surface as hdmi_stream when the source carries audio,
    # otherwise text/image/color/video. Loop and on-demand both work.
    'rtsp_stream': ['image', 'text', 'color', 'video', 'audio'],
    'video_stream': ['image', 'text', 'color', 'video'],
    # TASK-31: switch controllers only send input; image/text verifications
    # on a Nintendo Switch come from its hdmi_stream AV controller.
    'hdmi_switch': [],
    'bluetooth_procon': [],
    # TASK-32: the Tello remote only flies the drone; the picture is verified from rtsp_stream.
    'tello': [],
    # TASK-57: Vega has no UI dump reachable without Amazon's automation server; screens
    # are checked from the hdmi_stream capture.
    'vega': [],
    'playwright': ['web', 'image', 'text', 'color'],
    'android_mobile': ['adb'],
    'android_tv': ['adb'],
    'appium': ['appium'],
    # Same verification surface as a local Appium device; features/device-farm
    # re-backs the 'appium' type for the cloud models so it shares the one leased
    # farm session instead of allocating a second (billed) device. 'adb' is backed by
    # that same session so an `android_mobile` navigation tree — whose screen checks
    # are `verification_type: 'adb'` — runs against a farm phone unchanged, which is
    # what makes the android_phone family in MODEL_FAMILIES true rather than aspirational.
    'appium_cloud': ['appium', 'adb'],
    # A paired phone has no adb, but it has the same information: its AccessibilityService
    # node tree. features/mobile-app backs the 'adb' verification type with that for
    # phone_agent devices, so android_mobile navigation trees (whose screen checks are
    # `verification_type: 'adb'`) run against a phone unchanged. image/text/video/colour
    # come from hdmi_stream as for any other device.
    'phone_agent': ['adb'],
    'bash': []
}

def get_device_capabilities(device_model: str) -> dict:
    """
    Get detailed capabilities for a device model.
    
    Args:
        device_model: Device model name (e.g., 'android_mobile', 'host_vnc')
        
    Returns:
        Dictionary with capabilities for each controller type
    """
    if device_model not in DEVICE_CONTROLLER_MAP:
        return {
            'av': None,
            'remote': None,
            'desktop': None,
            'web': None,
            'power': None,
            'switch': None,
            'verification': []
        }
    
    mapping = DEVICE_CONTROLLER_MAP[device_model]
    
    # Get verification types from all controllers
    verification_types = []
    for controller_list in mapping.values():
        for controller_impl in controller_list:
            verification_types.extend(CONTROLLER_VERIFICATION_MAP.get(controller_impl, []))
    
    capabilities = {
        'av': mapping['av'][0] if mapping['av'] else None,
        'remote': mapping['remote'][0] if mapping['remote'] else None,
        'desktop': mapping['desktop'][0] if mapping['desktop'] else None,
        'web': mapping['web'][0] if mapping['web'] else None,
        'power': mapping['power'][0] if mapping['power'] else None,
        'switch': mapping.get('switch', [None])[0] if mapping.get('switch') else None,
        'verification': list(set(verification_types))  # Remove duplicates
    }
    
    return capabilities


# =====================================================
# MODEL SPELLING TOLERANCE
# =====================================================
#
# DEVICE{i}_MODEL is typed by hand in a host .env, and the canonical names are
# awkward to remember: `android_tv` or `androidtv`, `apple_tv` or `appletv`,
# `fire_tv_vega` or `firetv_vega`. A misspelling used to be fatal rather than
# cosmetic. Every consumer looked the raw string up in DEVICE_CONTROLLER_MAP,
# missed, and the factory returned {} -- the device registered with NO controllers
# at all, so Take Control answered "Unsupported device" and no remote ever
# appeared, with nothing in the log but a model name nobody could spell.
#
# So a spelling is resolved to the model it obviously means at every entry point
# that reads one (.env parsing, the controller factory, the model routes), instead
# of asking the operator to memorise a table. Three passes, cheapest first, and all
# derived from the map keys so a model added later needs no entry here:
#
#   1. exact            `android_tv`
#   2. separator-free   `androidtv`, `ANDROID_TV`, `Android TV`, `android-mobile`
#   3. near miss        `andoridtv`, `firetv_ios`   (difflib, above the cutoff)
#
# Pass 3 fires only when the best match also beats the runner-up, so two names that
# are genuinely different models are never collapsed into one.
#
# An unrecognised value comes back lowercased and trimmed rather than replaced by a
# guess. The factory then still reports "Unknown device model" and lists the real
# names: a device built out of the wrong model is worse than no device, because it
# looks alive and answers to controls that cannot work.

_MODEL_SEPARATORS = (' ', '_', '-', '.', '/')

# Spellings that string similarity cannot resolve, because they name a family and
# not a model. A bare `fire_tv` is the classic Fire TV (Fire OS): it is the common
# case, Vega is the rarer one with its own model name, and the correction is logged
# at every entry point so the choice is visible rather than silent. A Vega-only
# fleet changes this one line, not its .env files.
MODEL_ALIASES = {
    'firetv': 'fire_tv_fireos',
}

# How close a typo has to be, as a difflib ratio. `andoridtv` -> `android_tv` scores
# 0.889 and `firetv_ios` -> `fire_tv_fireos` 0.857, while a bare `fire_tv` ->
# `fire_tv_vega` is only 0.75 -- that gap is why the cutoff sits just under the
# typos, and why `fire_tv` needs an explicit alias above instead of a guess.
MODEL_FUZZY_CUTOFF = 0.85

# How much better the winner must be than the runner-up, so a near miss is only
# taken when there is no real competitor (`stb` must not drift towards `tizen`).
MODEL_FUZZY_MARGIN = 0.05


def _fold_model(value: str) -> str:
    """Lowercase a model spelling and drop the separators people skip or mistype."""
    folded = value.lower()
    for separator in _MODEL_SEPARATORS:
        folded = folded.replace(separator, '')
    return folded


# separator-free spelling -> canonical model. setdefault because a collision would
# mean two models differing only in separators, and the first one must win rather
# than the dict entry silently overwriting it.
_MODELS_BY_FOLDED = {}
for _model in DEVICE_CONTROLLER_MAP:
    _MODELS_BY_FOLDED.setdefault(_fold_model(_model), _model)


def _is_ambiguous_prefix_pair(probe: str, candidate: str) -> bool:
    """
    True when a near miss is an unfinished name or a numbered variant, not a typo.

    Two shapes are guesses rather than misspellings, so they are never resolved:

    - `android` -> `android_tv`: the spelling stops early, and the android family has
      four possible completions, so any of them would be a coin flip.
    - `rtsp_video` -> `rtsp_video2`: the extra characters are a trailing variant
      number, which is a different model naming convention, not a slipped letter.

    A candidate that is a prefix of the probe followed by anything else (`stb` ->
    `stbb`) IS a typo, and is deliberately left matchable.
    """
    if candidate.startswith(probe):
        return True  # `android` is unfinished
    if probe.startswith(candidate):
        return probe[len(candidate):].isdigit()  # `rtsp_video2` is a variant
    return False


def _near_miss_model(folded: str) -> Optional[str]:
    """The canonical model closest to a folded spelling, when one is close AND clear."""
    best_model, best_score, runner_up = None, 0.0, 0.0
    for candidate, model in _MODELS_BY_FOLDED.items():
        if _is_ambiguous_prefix_pair(folded, candidate):
            continue
        score = difflib.SequenceMatcher(None, folded, candidate).ratio()
        if score > best_score:
            runner_up, best_score, best_model = best_score, score, model
        elif score > runner_up:
            runner_up = score
    if (best_model and best_score >= MODEL_FUZZY_CUTOFF
            and best_score - runner_up >= MODEL_FUZZY_MARGIN):
        return best_model
    return None


def normalize_device_model(value, allow_fuzzy: bool = True) -> str:
    """
    Resolve a device model spelling to its canonical DEVICE_CONTROLLER_MAP key.

    Args:
        value: The model as written — a canonical name, an alternative spelling, a
            near miss, or something that is not a model at all.
        allow_fuzzy: Set False to stop at the exact and separator-free passes. Used
            where a *whole* value is tested as a model, because a fuzzy match there
            would swallow a platform tag (`android_tv-v2` must not become
            `android_tv` with the tag dropped).

    Returns:
        The canonical model name, or `value` trimmed and lowercased when no model
        matches -- unknown in, unknown out, so the caller still reports it.
    """
    if not isinstance(value, str):
        return value
    cleaned = value.strip().lower()
    if not cleaned:
        return 'unknown'
    if cleaned in DEVICE_CONTROLLER_MAP:
        return cleaned

    folded = _fold_model(cleaned)
    alias = MODEL_ALIASES.get(folded)
    if alias:
        return alias
    exact = _MODELS_BY_FOLDED.get(folded)
    if exact:
        return exact
    if not allow_fuzzy:
        return cleaned
    return _near_miss_model(folded) or cleaned


def parse_device_model(value) -> Tuple[str, Optional[str]]:
    """
    Split a DEVICE{i}_MODEL value into (canonical model, platform tag).

    The value may be a bare model (`stb`, `android_tv`) or carry a platform tag
    after the first dash (`stb-example-v2`). The broad model is everything before
    that dash and is resolved through normalize_device_model(); the tag is free
    form, so it is passed through untouched -- it is a label, not a model name.
    A bare value yields (model, None).

    The whole value is tried as a model FIRST (without fuzzy matching), so that a
    spelling which only differs in separators -- `android-mobile` -- is read as the
    model `android_mobile` rather than as the unknown model `android` carrying the
    platform tag `mobile`.
    """
    if not isinstance(value, str):
        return normalize_device_model(value), None

    as_one_model = normalize_device_model(value, allow_fuzzy=False)
    if as_one_model in DEVICE_CONTROLLER_MAP:
        return as_one_model, None

    model_part, _separator, platform = value.partition('-')
    return normalize_device_model(model_part), (platform.strip() or None)


def model_spelling_note(raw, canonical) -> Optional[str]:
    """
    One line telling the operator how a spelling was read, or None when it was exact.

    The correction is logged rather than applied silently: a device that silently
    became `fire_tv_fireos` from a bare `fire_tv` is the one case where the
    operator may have meant the other Fire TV platform, and they can only notice if
    the log says so. Only the model part is compared, so `stb-example-v2` — which
    is spelled exactly right — stays quiet.
    """
    if not isinstance(raw, str) or not isinstance(canonical, str):
        return None
    written = raw.partition('-')[0].strip().lower()
    if written == canonical:
        return None
    return f"'{raw.strip()}' read as '{canonical}'"


# =====================================================
# DEVICE MODEL FAMILIES
# =====================================================
#
# Several model names describe the same *thing* reached a different way. An Android
# phone is an Android phone whether adb is plugged into it (`android_mobile`), the
# VirtualPyTest app is paired with it (`phone_agent`, features/mobile-app), it lives
# in a cloud farm (`cloud_android_mobile`, features/device-farm) or a CI runner is
# standing in for it (`runner_android_mobile`). They run the same navigation trees,
# the same action blocks and the same scripts.
#
# Without this table every matcher compared model strings exactly, so a userinterface
# built for `android_mobile` was invisible to a paired phone and to a farm phone —
# which is why near-duplicate userinterfaces (`phone_home`, `cloud_farm_demo`) had to
# be created per transport. This is the single source of truth; the TypeScript mirror
# is `frontend/src/config/deviceModelFamilies.ts` and the two must stay in step.
#
# A model that is not listed here is its own family — adding a model is only needed
# when it is genuinely interchangeable with another one.
MODEL_FAMILIES = {
    'android_phone': [
        'android_mobile',
        'phone_agent',
        'cloud_android_mobile',
        'runner_android_mobile',
    ],
    'android_tablet': [
        'android_tablet',
        'runner_android_tablet',
    ],
    'android_tv': [
        'android_tv',
        'fire_tv_fireos',
        'fire_tv_vega',  # TASK-80: Fire TV on Vega OS shares the Fire TV remote picture with FireOS.
        'runner_android_tv',
    ],
    'ios_phone': [
        'ios_mobile',
        'cloud_ios_mobile',
    ],
    'desktop_host': [
        'host_vnc',
        'runner_host',
    ],
}

# One-directional extras, for pairs that are *not* twins.
#
# A `host_vnc` device can run a web or desktop userinterface, because it has a browser
# and a desktop on it — this rule pre-dates the family table and lives on. The reverse
# is not true: a `web` device is Playwright only, so offering it a `host_vnc`
# userinterface would offer a tree full of desktop actions it cannot execute. That
# asymmetry is why these are not a family.
MODEL_EXTRA_MATCHES = {
    'host_vnc': ['web', 'desktop'],
    'runner_host': ['web', 'desktop'],
}

# model name → family name, built once. A model may only belong to one family.
_MODEL_TO_FAMILY = {
    model: family
    for family, models in MODEL_FAMILIES.items()
    for model in models
}


def get_model_family(device_model: str) -> str:
    """Family name for a model, or the model itself when it is in no family."""
    return _MODEL_TO_FAMILY.get(device_model, device_model)


def get_compatible_models(device_model: str) -> list:
    """Every model name a device of `device_model` should be matched against.

    Used wherever a device model is compared with a userinterface's `models[]` or a
    script's `_target_rules.device_model`. Always contains `device_model` itself, so
    an unknown or feature-specific model degrades to exact matching.
    """
    if not device_model:
        return []
    family = _MODEL_TO_FAMILY.get(device_model)
    models = list(MODEL_FAMILIES[family]) if family else [device_model]
    for extra in MODEL_EXTRA_MATCHES.get(device_model, []):
        if extra not in models:
            models.append(extra)
    return models


def models_are_compatible(model_a: str, model_b: str) -> bool:
    """True when two model names describe the same kind of device."""
    if not model_a or not model_b:
        return False
    return get_model_family(model_a) == get_model_family(model_b)


def model_matches_any(device_model: str, models: list) -> bool:
    """True when `device_model` is compatible with any entry of `models`.

    `models` is typically a userinterface's `models[]` column.
    """
    if not device_model or not models:
        return False
    compatible = set(get_compatible_models(device_model))
    return any(model in compatible for model in models)


def expand_models(models: list) -> list:
    """Expand a userinterface's `models[]` into every model name that should be accepted.

    The reverse direction of `model_matches_any`, for filtering a device or host list by
    an already-chosen userinterface.
    """
    if not models:
        return []
    expanded = []
    for model in models:
        for compatible in get_compatible_models(model):
            if compatible not in expanded:
                expanded.append(compatible)
        # Reverse of MODEL_EXTRA_MATCHES: a `web` userinterface is runnable by a
        # `host_vnc` device, even though a `web` device cannot run a `host_vnc` one.
        for device_model, extras in MODEL_EXTRA_MATCHES.items():
            if model in extras and device_model not in expanded:
                expanded.append(device_model)
    return expanded
