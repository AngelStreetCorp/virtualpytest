"""
Remote-controller implementation registry.

Optional features (features/<name>/backend_host/__init__.py::register(app)) add a
remote implementation here so the core factory can instantiate it without core
ever importing the feature by name (docs/technical/FEATURES.md). backend_host
registers feature blueprints (app.py step 3) *before* it builds the devices
(step 2.5, get_host()), so a registration made in register(app) is visible when
controller_manager creates the controllers.

Usage from a feature:

    from backend_host.src.controllers.controller_registry import register_remote_implementation
    register_remote_implementation(
        'phone_agent',
        factory=lambda **params: PhoneAgentRemoteController(**params),
        params_builder=lambda device_config: {'device_id': device_config['device_id'], ...},
    )

The implementation name is the value listed under DEVICE_CONTROLLER_MAP[<model>]['remote']
in shared/src/lib/config/device_capabilities.py.
"""
from typing import Any, Callable, Dict, Optional

_REMOTE_IMPLEMENTATIONS: Dict[str, Dict[str, Any]] = {}


def register_remote_implementation(
    name: str,
    factory: Callable[..., Any],
    params_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> None:
    """Register (or replace) a remote implementation.

    factory(**params) -> controller instance (a RemoteControllerInterface subclass).
    params_builder(device_config) -> kwargs for the factory; when None the factory is
    called with no arguments. device_config is the flat dict built by
    controller_manager._get_devices_config_from_environment (device_id, device_name,
    video, video_capture_path, ...).
    """
    if not name or not callable(factory):
        raise ValueError('register_remote_implementation needs a name and a callable factory')
    _REMOTE_IMPLEMENTATIONS[name] = {'factory': factory, 'params_builder': params_builder}
    print(f"[@controller_registry] Registered remote implementation '{name}'")


def get_remote_implementation(name: str) -> Optional[Dict[str, Any]]:
    """{'factory', 'params_builder'} for a registered implementation, else None."""
    return _REMOTE_IMPLEMENTATIONS.get(name)


def registered_remote_implementations() -> list:
    return sorted(_REMOTE_IMPLEMENTATIONS)


# ---- verification implementations ---------------------------------------------------------
#
# Keyed by (device_model, implementation) rather than implementation alone, because unlike the
# remote ones these names are shared: 'adb' means the real ADB UI dump on an android_mobile
# device and the phone's own accessibility tree on a paired phone_agent one. The device model is
# already in every verification controller's params (controller_manager sets it), so the factory
# can be picked per device.
_VERIFICATION_IMPLEMENTATIONS: Dict[str, Dict[str, Any]] = {}


def _verification_key(device_model: Optional[str], name: str) -> str:
    return f'{device_model or ""}::{name}'


def register_verification_implementation(
    device_model: str,
    name: str,
    factory: Callable[..., Any],
) -> None:
    """Register (or replace) a verification implementation for one device model.

    `name` is the verification type as trees record it ('adb', 'image', ...), so a feature can
    supply its own backing for a type core already knows, without core importing the feature.
    factory(**params) -> controller instance; params are what controller_manager built,
    including device_id and device_model.
    """
    if not name or not callable(factory):
        raise ValueError('register_verification_implementation needs a name and a callable factory')
    _VERIFICATION_IMPLEMENTATIONS[_verification_key(device_model, name)] = {'factory': factory}
    print(f"[@controller_registry] Registered verification '{name}' for device model '{device_model}'")


def get_verification_implementation(device_model: Optional[str], name: str) -> Optional[Dict[str, Any]]:
    return _VERIFICATION_IMPLEMENTATIONS.get(_verification_key(device_model, name))
