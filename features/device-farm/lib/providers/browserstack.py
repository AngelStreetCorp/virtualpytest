"""BrowserStack — session half implemented, REST half deliberately not.

The session shape is public and stable, so it is written down and unit-tested
here: that is what proves the seam holds without a second account. The REST half
(app upload, device pool, artifacts) raises UnsupportedOperation, because those
responses cannot be guessed from docs with enough confidence to be worth shipping
— they get written when an account exists (TASK-20 §7).

    hub    https://hub-cloud.browserstack.com/wd/hub
    auth   userName + accessKey inside `bstack:options`
    app    `appium:app: bs://<hash>`, uploaded to
           https://api-cloud.browserstack.com/app-automate/upload
"""
from typing import Any, Dict, List

from .. import constants as C
from ..types import FarmConfig, FarmDevice, SessionArtifacts
from .base import FarmProvider, UnsupportedOperation


class BrowserStackProvider(FarmProvider):

    name = 'browserstack'
    app_prefix = C.BROWSERSTACK_APP_PREFIX

    def endpoint_url(self, cfg: FarmConfig) -> str:
        return C.BROWSERSTACK_HUB_URL

    def session_caps(self, cfg: FarmConfig) -> Dict[str, Any]:
        self._require(cfg, 'username', 'access_key', 'platform_name')
        caps = self.base_caps(cfg)
        bstack: Dict[str, Any] = {
            'userName': cfg.username,
            'accessKey': cfg.access_key,
            'sessionName': self.session_name(cfg),
            'idleTimeout': cfg.idle_timeout,
        }
        if cfg.build:
            bstack['buildName'] = cfg.build
        # BrowserStack reads the device and OS version from its own options block,
        # not from the appium: keys — the clearest example of why this seam exists.
        if cfg.device_query:
            bstack['deviceName'] = cfg.device_query
        if cfg.platform_version:
            bstack['osVersion'] = str(cfg.platform_version)
        caps[C.BROWSERSTACK_OPTIONS_KEY] = bstack
        return caps

    def upload_app(self, cfg: FarmConfig, app_path: str) -> str:
        raise UnsupportedOperation(
            'browserstack: app upload is not implemented yet (TASK-20 §7) — '
            f'POST the build to {C.BROWSERSTACK_API_URL}/upload and set '
            f'DEVICEn_FARM_APP to the returned {self.app_prefix}<hash>')

    def available_devices(self, cfg: FarmConfig) -> List[FarmDevice]:
        raise UnsupportedOperation('browserstack: device listing is not implemented yet')

    def session_artifacts(self, cfg: FarmConfig, session_id: str) -> SessionArtifacts:
        raise UnsupportedOperation('browserstack: artifact lookup is not implemented yet')
