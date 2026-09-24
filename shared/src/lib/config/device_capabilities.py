"""
Device Capabilities Configuration

Device model to controller mappings and capabilities.
This module is in shared/ so it can be used by both backend_host and backend_server.
"""

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
        'remote': ['android_tv'],
        'desktop': [],
        'web': [],
        'power': ['tapo'],
        'network': []
    },
    'android_tablet': {
        'av': ['hdmi_stream'],
        'remote': ['android_mobile'],
        'desktop': [],
        'web': [],
        'power': ['tapo'],
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
     'fire_tv': {
        'av': ['hdmi_stream'], 
        'remote': ['android_tv', 'ir_remote'],
        'desktop': [],
        'web': [],
        'power': ['tapo'],
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
        'remote': ['ir_remote', 'bluetooth_remote', 'irtrans_remote'],
        'desktop': [],
        'web': [],
        'power': ['tapo', 'api_power'],
        'network': []
    },
    'apple_tv': {
        'av': ['hdmi_stream'], 
        'remote': ['ir_remote'],
        'desktop': [],
        'web': [],
        'power': ['tapo'],
        'network': []
    },
    'tizen': {
        'av': ['camera_stream'], 
        'remote': ['ir_remote'],
        'desktop': [],
        'web': [],
        'power': [],
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
        'verification': list(set(verification_types))  # Remove duplicates
    }
    
    return capabilities



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
        'fire_tv',
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
