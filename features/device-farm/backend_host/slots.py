"""Which device slots are farm-backed, and their FarmConfig — read from the host .env.

Both controllers need the same FarmConfig, and they are built at different moments
by different code paths (the remote one gets a rich device_config from the core
factory; the verification one only gets device_id + device_model). Rather than
make one depend on the other's creation order, each asks here and gets the same
answer.

Reading DEVICE{i}_* directly is the established pattern for a feature that owns
its own keys (features/mobile-app/backend_host/bridge.py does the same for
DEVICE{i}_VIDEO), and it keeps the core env block free of farm keys.
"""
import os
import threading
from typing import Dict, List, Mapping, Optional, Tuple

from ..lib import constants as C
from ..lib.config import explain_missing, from_device_config
from ..lib.types import FarmConfig

_LOG = '[@device-farm:slots]'

#: Device models this feature backs (core device_capabilities.py must agree).
CLOUD_MODELS = ('cloud_android_mobile', 'cloud_ios_mobile')

#: Same ceiling the core env scan uses (DEVICE1..DEVICE12).
MAX_SLOTS = 12

_CACHE: Dict[str, FarmConfig] = {}
_LOCK = threading.RLock()


def _slot_env(index: int) -> Dict[str, str]:
    """DEVICE{i}_* values this feature cares about, as a flat device_config dict."""
    def get(suffix: str) -> Optional[str]:
        return os.getenv(f'DEVICE{index}_{suffix}')

    model = (get('MODEL') or '').partition('-')[0]
    return {
        'device_id': f'device{index}',
        'device_name': get('NAME') or f'device{index}',
        'device_model': model,
        'video': get('VIDEO') or '',
        'appium_platform_name': get(C.ENV_PLATFORM_NAME) or '',
        'farm_provider': get(C.ENV_PROVIDER) or '',
        'farm_user': get(C.ENV_USER) or '',
        'farm_key': get(C.ENV_KEY) or '',
        'farm_region': get(C.ENV_REGION) or '',
        'farm_device': get(C.ENV_DEVICE_QUERY) or '',
        'farm_os_version': get(C.ENV_PLATFORM_VERSION) or '',
        'farm_app': get(C.ENV_APP) or '',
        'farm_build': get(C.ENV_BUILD) or '',
        'farm_idle_timeout': get(C.ENV_IDLE_TIMEOUT) or '',
        'farm_max_duration': get(C.ENV_MAX_DURATION) or '',
        'farm_screenshot_fps': get(C.ENV_SCREENSHOT_FPS) or '',
    }


def _index_of(device_id: str) -> Optional[int]:
    digits = ''.join(ch for ch in str(device_id) if ch.isdigit())
    return int(digits) if digits else None


def farm_slot_ids() -> List[str]:
    """Slot ids whose DEVICE{i}_MODEL is one of this feature's models."""
    found = []
    for i in range(1, MAX_SLOTS + 1):
        if not os.getenv(f'DEVICE{i}_NAME'):
            continue
        if (os.getenv(f'DEVICE{i}_MODEL') or '').partition('-')[0] in CLOUD_MODELS:
            found.append(f'device{i}')
    return found


def farm_config_for(device_id: str,
                    device_config: Optional[Mapping] = None
                    ) -> Tuple[Optional[FarmConfig], List[str]]:
    """(FarmConfig, []) for a slot, or (None, missing DEVICE{i}_* keys).

    `device_config` is the core factory's dict when the caller has one: it carries
    the authoritative device_name, and merging it means a slot renamed in one place
    is not stale in the other.
    """
    index = _index_of(device_id)
    if index is None:
        return None, [f'unparseable device id {device_id!r}']

    merged = _slot_env(index)
    if device_config:
        for key in ('device_name', 'device_model', 'video', 'appium_platform_name',
                    'appium_device_id'):
            value = device_config.get(key)
            if value:
                merged[key] = value

    cfg, missing = from_device_config(merged)
    if cfg is None:
        return None, missing

    with _LOCK:
        _CACHE[device_id] = cfg
    return cfg, []


def cached_config(device_id: str) -> Optional[FarmConfig]:
    with _LOCK:
        return _CACHE.get(device_id)


def frame_path_for(device_id: str, device_config: Optional[Mapping] = None) -> str:
    """The slot's DEVICE{i}_VIDEO image file — what the ffmpeg imagefile grabber reads.

    Empty when the slot has no image path, or when it points at something that is not
    an image: run_ffmpeg.sh only treats .png/.jpg/.jpeg as an `imagefile` source, so
    anything else would be a frame pump writing where nothing reads.
    """
    path = ''
    if device_config and device_config.get('video'):
        path = str(device_config['video'])
    else:
        index = _index_of(device_id)
        if index is not None:
            path = os.getenv(f'DEVICE{index}_VIDEO') or ''
    if path and os.path.splitext(path)[1].lower() not in ('.jpg', '.jpeg', '.png'):
        print(f"{_LOG} {device_id}: DEVICE*_VIDEO={path!r} is not an image file - "
              f"no stream for this slot")
        return ''
    return path


def report_unconfigured(device_id: str, device_config: Optional[Mapping], missing: List[str]) -> None:
    print(explain_missing(device_config or {'device_id': device_id}, missing))
