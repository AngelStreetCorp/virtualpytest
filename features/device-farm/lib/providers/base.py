"""The seam between VirtualPyTest and one cloud device farm.

Everything above this file is provider-agnostic: a farm session is plain W3C
Appium, so taps, keys, text, element dumps and screenshots are the same calls on
Sauce Labs, BrowserStack or LambdaTest. Exactly four things differ, and they are
the four methods below:

    endpoint_url()       where the WebDriver hub lives, and how the account
                         authenticates to it
    session_caps()       the vendor's options block ('sauce:options',
                         'bstack:options', 'lt:options') around otherwise
                         standard W3C + appium: capabilities
    upload_app()         the app-storage REST API, and the reference scheme its
                         id is used under ('storage:…', 'bs://…', 'lt://…')
    available_devices()  the device-pool REST API
    session_artifacts()  where a finished session's page and video live

A new provider is one module implementing this class plus a line in __init__.py —
no controller changes.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .. import constants as C
from ..types import FarmConfig, FarmDevice, SessionArtifacts


class FarmProvider(ABC):
    """One cloud farm. Instances are stateless — configuration arrives per call."""

    name: str = 'unknown'
    #: Reference prefix this provider's app-storage ids are used under.
    app_prefix: str = ''

    # ---- session ------------------------------------------------------------
    @abstractmethod
    def endpoint_url(self, cfg: FarmConfig) -> str:
        """WebDriver hub URL for this account/region.

        Credentials belong in the capabilities, never in this URL: it is printed,
        logged and stored, and a URL-embedded access key leaks everywhere at once.
        """

    @abstractmethod
    def session_caps(self, cfg: FarmConfig) -> Dict[str, Any]:
        """Full W3C capabilities for one session, vendor options block included."""

    # ---- REST ---------------------------------------------------------------
    @abstractmethod
    def upload_app(self, cfg: FarmConfig, app_path: str) -> str:
        """Upload a build and return the reference to use as `appium:app`."""

    @abstractmethod
    def available_devices(self, cfg: FarmConfig) -> List[FarmDevice]:
        """Devices this account may allocate right now."""

    @abstractmethod
    def session_artifacts(self, cfg: FarmConfig, session_id: str) -> SessionArtifacts:
        """Where to look at a finished session in the farm's own UI."""

    # ---- shared helpers -----------------------------------------------------
    def automation_name(self, platform_name: str) -> str:
        return (C.AUTOMATION_IOS if str(platform_name).strip().lower() == 'ios'
                else C.AUTOMATION_ANDROID)

    def normalized_platform(self, platform_name: str) -> str:
        """'android' / 'ANDROID' -> 'Android'; 'ios' -> 'iOS'. W3C matches exactly."""
        return 'iOS' if str(platform_name).strip().lower() == 'ios' else 'Android'

    def base_caps(self, cfg: FarmConfig) -> Dict[str, Any]:
        """The provider-independent half of the capabilities.

        Note what is *absent* versus the local Appium controller: no `udid` (the farm
        allocates from a pool), no `usePrebuiltWDA`/`useNewWDA`/singleton-manager keys
        (the farm manages WebDriverAgent itself and rejects several of them).
        """
        caps: Dict[str, Any] = {
            C.CAP_PLATFORM_NAME: self.normalized_platform(cfg.platform_name),
            C.CAP_AUTOMATION_NAME: self.automation_name(cfg.platform_name),
            # Keep the farm's own idle reaper the single authority on session life:
            # a local newCommandTimeout longer than it only hides the reaping.
            C.CAP_NEW_COMMAND_TIMEOUT: cfg.idle_timeout,
        }
        if cfg.device_query:
            caps[C.CAP_DEVICE_NAME] = cfg.device_query
        if cfg.platform_version:
            caps[C.CAP_PLATFORM_VERSION] = str(cfg.platform_version)
        if cfg.app_ref:
            caps[C.CAP_APP] = cfg.app_ref
        caps.update(cfg.extra_caps or {})
        return caps

    def auth(self, cfg: FarmConfig):
        """requests-style (user, key) tuple for this provider's REST API."""
        return (cfg.username, cfg.access_key)

    def session_name(self, cfg: FarmConfig) -> str:
        return f'VirtualPyTest {cfg.device_name}'

    def _require(self, cfg: FarmConfig, *fields: str) -> None:
        missing = [f for f in fields if not getattr(cfg, f, None)]
        if missing:
            raise ValueError(
                f'{self.name}: FarmConfig is missing {", ".join(missing)}')


class UnsupportedOperation(NotImplementedError):
    """Raised by a provider whose REST half is not implemented yet.

    Distinct from a bare NotImplementedError so a caller can tell "this provider
    cannot do it yet" from "this code path was never finished".
    """
