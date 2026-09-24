"""Sauce Labs — the implemented provider.

Session shape (their real-device cloud):
    hub    https://ondemand.<region>.saucelabs.com/wd/hub
    auth   username + accessKey inside `sauce:options`, not in the URL
    device `appium:deviceName` (an exact name or a regex for dynamic allocation)
           + `appium:platformVersion`
    app    `appium:app: storage:<file id>`, uploaded to the account's app storage

The hub, app-storage and session-page URLs were exercised against a live account
on 2026-09-17 (eu-central-1, real device): a session opens, an upload returns
`item.id`, and the session page resolves. If one ever needs changing, it is wrong
here and in constants.py only, not in any controller.
"""
from typing import Any, Dict, List

from .. import constants as C
from ..types import FarmConfig, FarmDevice, SessionArtifacts
from .base import FarmProvider, UnsupportedOperation

_LOG = '[@device-farm:saucelabs]'


class SauceLabsProvider(FarmProvider):

    name = 'saucelabs'
    app_prefix = C.SAUCE_APP_PREFIX

    def _region(self, cfg: FarmConfig) -> str:
        return (cfg.region or C.SAUCE_DEFAULT_REGION).strip()

    # ---- session ------------------------------------------------------------
    def endpoint_url(self, cfg: FarmConfig) -> str:
        return C.SAUCE_HUB_URL.format(region=self._region(cfg))

    def session_caps(self, cfg: FarmConfig) -> Dict[str, Any]:
        self._require(cfg, 'username', 'access_key', 'platform_name')
        caps = self.base_caps(cfg)
        sauce: Dict[str, Any] = {
            'username': cfg.username,
            'accessKey': cfg.access_key,
            'name': self.session_name(cfg),
            # Both timeouts are the farm's, and the farm enforces them; VPT's lease
            # only has to notice them first (SESSION_EXPIRY_MARGIN).
            'idleTimeout': cfg.idle_timeout,
            'maxDuration': cfg.max_duration,
            # Not optional: without it Sauce rejects Android 14+ outright (see constant).
            'appiumVersion': C.SAUCE_APPIUM_VERSION,
        }
        if cfg.build:
            sauce['build'] = cfg.build
        caps[C.SAUCE_OPTIONS_KEY] = sauce
        return caps

    # ---- REST ---------------------------------------------------------------
    def _api(self, cfg: FarmConfig, path: str) -> str:
        return f"{C.SAUCE_API_URL.format(region=self._region(cfg))}{path}"

    def upload_app(self, cfg: FarmConfig, app_path: str) -> str:
        """POST the build to app storage and return `storage:<id>` for `appium:app`."""
        import os
        import requests

        self._require(cfg, 'username', 'access_key')
        if not os.path.isfile(app_path):
            raise FileNotFoundError(f'{self.name}: no app at {app_path}')

        url = self._api(cfg, '/v1/storage/upload')
        with open(app_path, 'rb') as fh:
            response = requests.post(
                url,
                files={'payload': (os.path.basename(app_path), fh)},
                data={'name': os.path.basename(app_path)},
                auth=self.auth(cfg),
                timeout=C.UPLOAD_TIMEOUT,
            )
        response.raise_for_status()
        body = response.json() or {}
        item = (body.get('item') or {})
        file_id = item.get('id')
        if not file_id:
            raise ValueError(f'{self.name}: upload response carried no item id: {body}')
        print(f"{_LOG} uploaded {os.path.basename(app_path)} -> {file_id}")
        return f'{self.app_prefix}{file_id}'

    @staticmethod
    def _raise_for_plan(response) -> None:
        """Turn a plan restriction into a message that says what to do instead.

        Without this, a trial account gets a bare 403 out of raise_for_status() and
        the reader goes looking for a credential problem that isn't there.
        """
        if response.status_code != 403:
            return
        body = (response.text or '')[:200]
        raise UnsupportedOperation(
            'saucelabs: the real-device (Access) API is not available on this plan '
            f'({body.strip() or "403"}). Only the listing is refused — sessions are '
            'unaffected, so name the device you want directly in DEVICE{i}_FARM_DEVICE '
            'with DEVICE{i}_FARM_OS_VERSION and open one anyway.')

    def available_devices(self, cfg: FarmConfig) -> List[FarmDevice]:
        """Real devices this account can allocate right now.

        Two calls, because the availability endpoint returns names only: the
        descriptor list gives each device's OS and version.

        These are **real-device cloud** endpoints. Whether an account may call them is
        a plan question, and the answer is not "trial means no": the trial account used
        on 2026-09-17 listed the full pool, including the devices Sauce marks `_free`
        that a trial may actually allocate (`Samsung_Galaxy_S23_FE_free`,
        `iPhone_15_free`). Some plans do refuse with 403 "Access API is not available
        for free trial accounts", which `_raise_for_plan` turns into an instruction —
        that refusal is about the *listing* only and never stops a session, so a device
        named directly in DEVICE{i}_FARM_DEVICE still works.
        """
        import requests

        self._require(cfg, 'username', 'access_key')
        auth, timeout = self.auth(cfg), C.HTTP_TIMEOUT

        free = requests.get(self._api(cfg, '/v1/rdc/devices/available'),
                            auth=auth, timeout=timeout)
        self._raise_for_plan(free)
        free.raise_for_status()
        free_names = set(free.json() or [])

        described = requests.get(self._api(cfg, '/v1/rdc/devices'),
                                 auth=auth, timeout=timeout)
        self._raise_for_plan(described)
        described.raise_for_status()

        devices: List[FarmDevice] = []
        for entry in (described.json() or []):
            name = entry.get('name') or entry.get('descriptor') or ''
            if not name:
                continue
            devices.append(FarmDevice(
                name=name,
                platform_name=self.normalized_platform(entry.get('os', '')),
                platform_version=str(entry.get('osVersion') or ''),
                available=name in free_names,
                raw=entry,
            ))
        return devices

    def session_artifacts(self, cfg: FarmConfig, session_id: str) -> SessionArtifacts:
        """The session's page, plus its recording when the job already exposes one.

        The page URL is built, not fetched, so a report always has a link even when
        the jobs API is slow or the job is still running.
        """
        import requests

        url = C.SAUCE_APP_URL.format(region=self._region(cfg), session_id=session_id)
        video_url = None
        try:
            response = requests.get(self._api(cfg, f'/v1/rdc/jobs/{session_id}'),
                                    auth=self.auth(cfg), timeout=C.HTTP_TIMEOUT)
            if response.ok:
                video_url = (response.json() or {}).get('video_url')
        except Exception as e:  # a missing video never fails a test run
            print(f"{_LOG} could not read job {session_id}: {e}")
        return SessionArtifacts(session_id=session_id, session_url=url, video_url=video_url)
