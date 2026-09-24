"""device_config (flat dict from controller_manager) -> FarmConfig, plus redaction.

One place decides what a farm slot needs and what is missing, so a half-configured
slot is refused with a message naming the exact DEVICE{i}_* keys rather than dying
later inside a WebDriver handshake.
"""
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import constants as C
from .types import FarmConfig

_LOG = '[@device-farm:config]'


def redact(caps: Mapping[str, Any]) -> Dict[str, Any]:
    """Copy of a capabilities dict with every credential value masked, recursively.

    Capability dicts are printed all over the Appium path, and a farm's caps carry
    the account's access key — so nothing prints a caps dict that did not come
    through here first. Core has its own twin for its own log lines
    (appium_utils.redact_capabilities); this one exists so lib/ stays importable
    without backend_host, which is what lets the providers be unit-tested alone.
    """
    out: Dict[str, Any] = {}
    for key, value in caps.items():
        if isinstance(value, Mapping):
            out[key] = redact(value)
        elif key in C.SECRET_CAP_KEYS and value:
            out[key] = '***'
        else:
            out[key] = value
    return out


def _env_key(device_id: str, suffix: str) -> str:
    """'device1' + 'FARM_USER' -> 'DEVICE1_FARM_USER' (for error messages only)."""
    num = device_id.replace('device', '').upper() or '1'
    return f'DEVICE{num}_{suffix}'


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def missing_keys(device_config: Mapping[str, Any]) -> List[str]:
    """DEVICE{i}_* keys a farm slot needs and does not have, in .env spelling."""
    device_id = device_config.get('device_id', 'device1')
    required = [
        ('farm_user', C.ENV_USER),
        ('farm_key', C.ENV_KEY),
        ('appium_platform_name', C.ENV_PLATFORM_NAME),
    ]
    return [_env_key(device_id, suffix)
            for field, suffix in required if not device_config.get(field)]


def from_device_config(device_config: Mapping[str, Any]) -> Tuple[Optional[FarmConfig], List[str]]:
    """(FarmConfig, []) when the slot is complete, else (None, missing keys).

    Never raises: a misconfigured slot must leave the rest of the host's devices
    alive, exactly like the IR/BLE branches of the core config factory.
    """
    missing = missing_keys(device_config)
    if missing:
        return None, missing

    device_id = device_config.get('device_id', 'device1')
    platform_name = str(device_config.get('appium_platform_name', '')).strip()
    fps = min(_float(device_config.get('farm_screenshot_fps'), C.DEFAULT_SCREENSHOT_FPS),
              C.MAX_SCREENSHOT_FPS)

    cfg = FarmConfig(
        device_id=device_id,
        device_name=device_config.get('device_name', device_id),
        provider=(device_config.get('farm_provider') or C.DEFAULT_PROVIDER).strip().lower(),
        username=device_config['farm_user'],
        access_key=device_config['farm_key'],
        platform_name=platform_name,
        region=device_config.get('farm_region') or None,
        # A farm allocates from a pool, so the device is a *request*. The local
        # Appium UDID key is accepted as a fallback spelling for slots converted
        # from a wired device.
        device_query=(device_config.get('farm_device')
                      or device_config.get('appium_device_id') or None),
        platform_version=device_config.get('farm_os_version') or None,
        app_ref=device_config.get('farm_app') or None,
        build=device_config.get('farm_build') or None,
        idle_timeout=_int(device_config.get('farm_idle_timeout'), C.DEFAULT_IDLE_TIMEOUT),
        max_duration=_int(device_config.get('farm_max_duration'), C.DEFAULT_MAX_DURATION),
        screenshot_fps=fps if fps > 0 else C.DEFAULT_SCREENSHOT_FPS,
    )
    return cfg, []


def explain_missing(device_config: Mapping[str, Any], missing: List[str]) -> str:
    """One line an operator can act on, in the same shape as the core IR/BLE warnings."""
    device_id = device_config.get('device_id', 'device1')
    return (f"{_LOG} {device_id}: cloud farm slot is not configured - missing "
            f"{', '.join(missing)}. Set them in the host .env "
            f"(see features/device-farm/README.md).")
