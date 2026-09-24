"""Remote implementation 'appium_cloud' — a farm device driven like any other.

This subclasses the core Appium remote controller rather than reimplementing it,
because a farm session *is* a W3C Appium session: keys, text, taps, element dumps,
clicks, app launch and screenshots are the core methods, unchanged. Every one of
them is shaped `if not self.is_connected or not self.appium_utils: return ...`
followed by `self.appium_utils.<op>(self.appium_device_id, ...)`, so this class
only has to change what `appium_utils` *is* — a lazily leased farm session instead
of an eagerly opened local one — and the whole inherited surface follows.

Three deliberate differences from the local controller:

1. **`__init__` does not connect.** The core constructor ends with `self.connect()`,
   which for a farm would allocate (and bill for) a device at host startup, for
   every configured slot. Here construction only validates config; the session
   opens on the first command.
2. **`appium_utils` is a property**, so *any* inherited method opening its guard is
   the thing that takes the lease. There is no second place to remember.
3. **`get_status()` does not curl `<endpoint>/status`.** A farm hub answers that
   path only to an authenticated caller, so the core check would report a healthy
   device as unreachable.
"""
from typing import Any, Dict, Optional

from backend_host.src.controllers.base_controller import RemoteControllerInterface
from backend_host.src.controllers.remote.appium_remote import AppiumRemoteController

from ..lib.types import FarmConfig
from .frame_pump import FramePump
from .session import FarmSession, get_session, release_session

_LOG = '[@device-farm:remote]'


class CloudAppiumRemoteController(AppiumRemoteController):
    """Farm-backed Appium remote. `device_type` stays 'appium': same panel, same commands."""

    def __init__(self, cfg: FarmConfig, frame_path: Optional[str] = None):
        # Deliberately skips AppiumRemoteController.__init__: it validates local-only
        # fields and calls connect() at the end. Its grandparent initialiser is the
        # one that actually sets up a controller.
        RemoteControllerInterface.__init__(self, 'Cloud Appium Remote', 'appium')

        self.cfg = cfg
        self.session: FarmSession = get_session(cfg)

        # Attribute contract the inherited methods rely on. appium_device_id is the
        # host slot id, not a UDID — the farm allocates the device, and the slot id
        # is what the session is keyed by (session.py).
        self.platform_name = cfg.platform_name
        self.appium_device_id = cfg.device_id
        self.appium_server_url = self.session.provider.endpoint_url(cfg)
        self.driver = None
        self.device_resolution = None
        self.detected_platform = self.session.provider.normalized_platform(cfg.platform_name)
        self.last_ui_elements = []
        self.last_dump_time = 0

        # 'Connected' for a farm slot means *leasable*, not *leased*: the inherited
        # guards read this flag, and a slot that is correctly configured must let a
        # command through so the command itself can take the lease.
        self.is_connected = True

        self.frame_pump = FramePump(cfg, self.session, frame_path) if frame_path else None
        if self.frame_pump:
            self.frame_pump.start()

        print(f"{_LOG} {cfg.device_id}: ready on {cfg.provider} "
              f"({self.detected_platform}, device={cfg.device_query!r}) - "
              f"no session opened until the first command")

    # ---- the lease ----------------------------------------------------------
    @property
    def appium_utils(self):
        """Core AppiumUtils bound to the live farm session, or None with a reason.

        None (not an exception) because every inherited method guards on it: a farm
        that refuses a session becomes a failed command with `last_session_error`
        set, instead of a traceback from an attribute access.
        """
        utils = self.session.utils()
        if utils is None:
            print(f"{_LOG} {self.cfg.device_id}: no session - {self.session.last_error}")
        return utils

    @appium_utils.setter
    def appium_utils(self, value):
        """Core's disconnect() assigns None here; that means 'drop the lease'."""
        if value is None:
            self.session.release()
            return
        raise AttributeError(
            'appium_utils is owned by the farm session lease and cannot be assigned')

    @property
    def last_session_error(self) -> Optional[str]:
        return self.session.last_error

    # ---- lifecycle ----------------------------------------------------------
    def connect(self) -> bool:
        """Validate only. Opening a session here would bill for every idle slot."""
        self.is_connected = True
        return True

    def disconnect(self) -> bool:
        if self.frame_pump:
            self.frame_pump.stop()
        release_session(self.cfg.device_id)
        self.is_connected = False
        return True

    # ---- status -------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        """What we actually know, without a billable round-trip.

        Reporting 'reachable' would need a real call to the farm; this reports the
        slot's configuration and the outcome of the last attempt, which is the
        honest answer and the one that debugs a broken slot.
        """
        status = self.session.status()
        if status.get('last_error'):
            return {'success': False, 'error': status['last_error'], 'farm': status}
        return {'success': True, 'farm': status}

    def get_session_artifacts(self) -> Optional[Dict[str, Any]]:
        """Farm session page / recording for the report, when a session has run."""
        session_id = self.session.session_id
        if not session_id:
            return None
        try:
            artifacts = self.session.provider.session_artifacts(self.cfg, session_id)
        except NotImplementedError as e:
            print(f"{_LOG} {self.cfg.device_id}: {e}")
            return None
        except Exception as e:
            print(f"{_LOG} {self.cfg.device_id}: artifact lookup failed: {e}")
            return None
        return {
            'session_id': artifacts.session_id,
            'session_url': artifacts.session_url,
            'video_url': artifacts.video_url,
        }
