"""features/device-farm/backend_host — registers the farm controllers (TASK-20).

Two entry points, because a host builds controllers twice:

* `register(app)` — called by shared/src/lib/utils/features.py from
  backend_host/src/app.py's register_host_routes(), which runs *before* devices are
  created, so the registration is visible when controller_manager builds them.
* `register_controllers()` — the no-Flask sibling, called from
  controller_manager.create_host_from_environment() for script subprocesses.

Unlike features/mobile-app, these two do the same thing: a farm session lives in
the process that opens it (there is no host-local hardware or socket to proxy to),
so a script subprocess holds its own lease and needs no bridge back to vpt-host.

No blueprint is registered: everything a farm device does reaches it through the
ordinary /host/<control> routes, which resolve controllers by type.
"""
from functools import partial
from typing import Any, Dict, Optional

_LOG = '[@device-farm:register]'

REMOTE_IMPLEMENTATION = 'appium_cloud'
# 'appium' is the farm device's own verification type. 'adb' is registered against the
# same controller because a cloud Android phone is in the same model family as a local
# one (MODEL_FAMILIES in shared/src/lib/config/device_capabilities.py), and an
# `android_mobile` navigation tree writes its screen checks as `verification_type: 'adb'`.
# Without this the tree would be offered for a farm phone and then find no implementation.
# Same move features/mobile-app makes for a paired phone, for the same reason.
VERIFICATION_TYPES = ('appium', 'adb')


def register(app) -> None:
    _register_implementations()


def register_controllers() -> None:
    _register_implementations()


def _register_implementations() -> None:
    from backend_host.src.controllers.controller_registry import (
        get_remote_implementation,
        register_remote_implementation,
        register_verification_implementation,
    )
    from .slots import CLOUD_MODELS

    if get_remote_implementation(REMOTE_IMPLEMENTATION) is not None:
        return  # already registered in this process (register(app) then the subprocess hook)

    register_remote_implementation(
        REMOTE_IMPLEMENTATION,
        factory=_remote_factory,
        params_builder=_remote_params,
    )

    for model in CLOUD_MODELS:
        for verification_type in VERIFICATION_TYPES:
            register_verification_implementation(
                model,
                verification_type,
                # Bound per type so the controller reports the type it was built for;
                # both share the one lease, because get_session() is keyed by slot.
                factory=partial(_verification_factory, verification_type=verification_type),
            )

    print(f"{_LOG} remote '{REMOTE_IMPLEMENTATION}' + "
          f"{'/'.join(VERIFICATION_TYPES)} verification "
          f"registered for {', '.join(CLOUD_MODELS)}")


# ---- remote -----------------------------------------------------------------
def _remote_params(device_config: Dict[str, Any]) -> Dict[str, Any]:
    """Build the controller's kwargs, or tell core to skip this slot.

    A slot missing its credentials is skipped with the exact .env keys named, the
    same way core handles a half-configured IR or BLE remote — the host keeps
    serving its other devices.
    """
    from .slots import farm_config_for, frame_path_for, report_unconfigured

    device_id = device_config.get('device_id', 'device1')
    cfg, missing = farm_config_for(device_id, device_config)
    if cfg is None:
        report_unconfigured(device_id, device_config, missing)
        return {'_skip_controller': True,
                'reason': f'device-farm slot not configured ({", ".join(missing)})'}

    return {'cfg': cfg, 'frame_path': frame_path_for(device_id, device_config)}


def _remote_factory(**params):
    from .cloud_appium_remote import CloudAppiumRemoteController
    return CloudAppiumRemoteController(**params)


# ---- verification -----------------------------------------------------------
def _verification_factory(verification_type: str = 'appium', **params) -> Optional[Any]:
    """Core passes device_id + device_model (+ the local appium_* keys, unused here).

    The FarmConfig is read from the slot rather than from these params so this does
    not depend on the remote controller having been built first.
    """
    from .cloud_appium_verification import CloudAppiumVerificationController
    from .slots import farm_config_for, report_unconfigured

    device_id = params.get('device_id', 'device1')
    cfg, missing = farm_config_for(device_id)
    if cfg is None:
        report_unconfigured(device_id, {'device_id': device_id}, missing)
        return None
    return CloudAppiumVerificationController(cfg=cfg, verification_type=verification_type)
