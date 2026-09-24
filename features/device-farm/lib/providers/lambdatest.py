"""LambdaTest — session half implemented, REST half deliberately not.

Same posture as browserstack.py: the session shape is recorded and tested, the
REST responses wait for an account (TASK-20 §7).

    hub    https://mobile-hub.lambdatest.com/wd/hub
    auth   user + accessKey inside `lt:options`
    app    `appium:app: lt://APP…`, uploaded to
           https://manual-api.lambdatest.com/app/uploadFramework
"""
from typing import Any, Dict, List

from .. import constants as C
from ..types import FarmConfig, FarmDevice, SessionArtifacts
from .base import FarmProvider, UnsupportedOperation


class LambdaTestProvider(FarmProvider):

    name = 'lambdatest'
    app_prefix = C.LAMBDATEST_APP_PREFIX

    def endpoint_url(self, cfg: FarmConfig) -> str:
        return C.LAMBDATEST_HUB_URL

    def session_caps(self, cfg: FarmConfig) -> Dict[str, Any]:
        self._require(cfg, 'username', 'access_key', 'platform_name')
        caps = self.base_caps(cfg)
        lt: Dict[str, Any] = {
            'user': cfg.username,
            'accessKey': cfg.access_key,
            'name': self.session_name(cfg),
            'idleTimeout': cfg.idle_timeout,
            'isRealMobile': True,
        }
        if cfg.build:
            lt['build'] = cfg.build
        if cfg.device_query:
            lt['deviceName'] = cfg.device_query
        if cfg.platform_version:
            lt['platformVersion'] = str(cfg.platform_version)
        caps[C.LAMBDATEST_OPTIONS_KEY] = lt
        return caps

    def upload_app(self, cfg: FarmConfig, app_path: str) -> str:
        raise UnsupportedOperation(
            'lambdatest: app upload is not implemented yet (TASK-20 §7) — '
            f'POST the build to {C.LAMBDATEST_API_URL} and set DEVICEn_FARM_APP '
            f'to the returned {self.app_prefix}<id>')

    def available_devices(self, cfg: FarmConfig) -> List[FarmDevice]:
        raise UnsupportedOperation('lambdatest: device listing is not implemented yet')

    def session_artifacts(self, cfg: FarmConfig, session_id: str) -> SessionArtifacts:
        raise UnsupportedOperation('lambdatest: artifact lookup is not implemented yet')
