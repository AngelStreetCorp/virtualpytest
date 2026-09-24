"""Verification types 'appium' and 'adb', re-backed for farm devices so they share one session.

The core Appium verification controller builds its own `AppiumUtils` and connects
it itself. On a local phone that is merely a second connection to the same USB
device; on a farm it is a **second allocated device**, billed and counted against
the account's parallel-session limit — while the element tree it reads belongs to
a different phone than the one the remote controller is driving.

So for the cloud models this controller is registered in core's per-model
verification registry and reuses the remote controller's lease. Everything
inherited (getElementLists, smart search, waitForElementToAppear/Disappear,
execute_verification) then runs against the one session.
"""
from typing import Any, Dict, Optional

from backend_host.src.controllers.base_controller import VerificationControllerInterface
from backend_host.src.controllers.verification.appium import AppiumVerificationController

from ..lib.types import FarmConfig
from .session import get_session

_LOG = '[@device-farm:verification]'


class CloudAppiumVerificationController(AppiumVerificationController):
    """Appium verification against the farm session already leased for this slot."""

    def __init__(self, cfg: FarmConfig, verification_type: str = 'appium', **kwargs):
        # Skips AppiumVerificationController.__init__, which would create a second
        # AppiumUtils (and therefore a second farm device) for this slot.
        VerificationControllerInterface.__init__(
            self, 'Cloud Appium Verification', verification_type)

        self.cfg = cfg
        self.session = get_session(cfg)

        self.platform_name = cfg.platform_name
        self.appium_device_id = cfg.device_id   # the session key, see session.py
        self.appium_server_url = self.session.provider.endpoint_url(cfg)
        # 'appium' or 'adb' — the same controller backs both for the cloud models, so an
        # android_mobile tree's adb screen checks run against the one leased session.
        self.verification_type = verification_type
        self.is_connected = True

        print(f"{_LOG} {cfg.device_id}: '{verification_type}' sharing the {cfg.provider} session lease")

    @property
    def appium_utils(self):
        """The shared lease. None (never an exception) — inherited methods guard on it."""
        utils = self.session.utils()
        if utils is None:
            print(f"{_LOG} {self.cfg.device_id}: no session - {self.session.last_error}")
        return utils

    @appium_utils.setter
    def appium_utils(self, value):
        if value is None:
            return  # a verification never owns the lease, so it never drops it
        raise AttributeError(
            'appium_utils is owned by the farm session lease and cannot be assigned')

    def _connect_device(self) -> bool:
        """Inherited methods call this before dumping; the lease already did it.

        Returns whether a session is actually available, so a farm outage surfaces
        as a failed verification with a reason rather than an empty element list.
        """
        return self.session.utils() is not None

    def get_status(self) -> Dict[str, Any]:
        status = self.session.status()
        if status.get('last_error'):
            return {'success': False, 'error': status['last_error'], 'farm': status}
        return {'success': True, 'farm': status}
