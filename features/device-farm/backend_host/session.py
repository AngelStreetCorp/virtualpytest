"""The lease: one leased WebDriver session per farm-backed device slot.

A cloud session is not a device that is simply there. It is metered per minute,
the farm reaps it when idle, and it is killed outright at max duration — so the
rules here are:

* **Nothing opens a session at startup.** A host with four farm slots that boots
  four sessions bills for four devices nobody asked for. The session opens on the
  first command (`utils()`), which is what the controllers' lazy `appium_utils`
  property calls.
* **The frame pump never opens one.** It uses `driver_if_open()`, so screenshots
  flow while a session exists and stop when it does not. A pump that could open a
  session would keep every configured slot streaming — and billing — forever.
* **Expiry is anticipated, not discovered.** The lease treats a session as gone
  SESSION_EXPIRY_MARGIN seconds before the farm's own idle/duration limits, so a
  command is never sent into a session the farm has just reaped. The next command
  transparently opens a fresh one.
* **A cap, because concurrency is contractual.** FARM_MAX_SESSIONS bounds open
  sessions per host; exceeding an account's parallel limit fails the *other*
  people's runs too, which is the kind of failure nobody debugs quickly.

The driver is handed to a core `AppiumUtils` instance (its `drivers` dict is the
public seam), so every inherited Appium behaviour — element dump, click, key,
text, screenshot — runs against the farm session unchanged.
"""
import os
import threading
import time
from typing import Any, Dict, Optional

from ..lib import constants as C
from ..lib.config import redact
from ..lib.providers import get_provider
from ..lib.types import FarmConfig

_LOG = '[@device-farm:session]'

_SESSIONS: Dict[str, 'FarmSession'] = {}
_REGISTRY_LOCK = threading.RLock()


def max_sessions() -> int:
    try:
        return max(1, int(os.getenv(C.ENV_HOST_MAX_SESSIONS, C.DEFAULT_MAX_SESSIONS)))
    except (TypeError, ValueError):
        return C.DEFAULT_MAX_SESSIONS


def open_session_count() -> int:
    with _REGISTRY_LOCK:
        return sum(1 for s in _SESSIONS.values() if s.is_open)


class FarmSession:
    """Lease for one device slot. Thread-safe: the pump and request threads share it."""

    def __init__(self, cfg: FarmConfig):
        self.cfg = cfg
        self.provider = get_provider(cfg.provider)
        self.last_error: Optional[str] = None
        self.session_id: Optional[str] = None

        self._lock = threading.RLock()
        self._driver = None
        self._utils = None
        self._opened_at = 0.0
        self._last_used = 0.0

    # ---- state --------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._driver is not None and not self._expired()

    def _expired(self) -> bool:
        """True once the farm is about to reap this session (or already has)."""
        if self._driver is None:
            return True
        now = time.time()
        idle_limit = max(0, self.cfg.idle_timeout - C.SESSION_EXPIRY_MARGIN)
        duration_limit = max(0, self.cfg.max_duration - C.SESSION_EXPIRY_MARGIN)
        return (now - self._last_used) >= idle_limit or (now - self._opened_at) >= duration_limit

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'device_id': self.cfg.device_id,
                'provider': self.cfg.provider,
                'open': self.is_open,
                'session_id': self.session_id,
                'age_seconds': round(time.time() - self._opened_at, 1) if self._driver else None,
                'idle_seconds': round(time.time() - self._last_used, 1) if self._driver else None,
                'last_error': self.last_error,
            }

    # ---- access -------------------------------------------------------------
    def utils(self):
        """Core AppiumUtils bound to a live session, or None with `last_error` set.

        None rather than an exception on purpose: every inherited controller method
        guards with `if not self.appium_utils`, so a farm that is down degrades into
        an ordinary failed command with a reason attached, not a traceback out of a
        property access.
        """
        with self._lock:
            if self._driver is not None and self._expired():
                print(f"{_LOG} {self.cfg.device_id}: session expired - reopening")
                self._close_locked(quiet=True)
            if self._driver is None and not self._open_locked():
                return None
            self._last_used = time.time()
            return self._utils

    def driver_if_open(self):
        """Live driver, but only when a session already exists — never opens one."""
        with self._lock:
            if self._driver is None or self._expired():
                return None
            self._last_used = time.time()
            return self._driver

    def release(self) -> None:
        with self._lock:
            self._close_locked(quiet=False)

    # ---- internals ----------------------------------------------------------
    def _open_locked(self) -> bool:
        if open_session_count() >= max_sessions():
            self.last_error = (
                f'host session cap reached ({max_sessions()}): another farm device is '
                f'in use. Raise {C.ENV_HOST_MAX_SESSIONS} only up to the account\'s '
                f'parallel-session limit.')
            print(f"{_LOG} {self.cfg.device_id}: {self.last_error}")
            return False

        try:
            from appium import webdriver
            from appium.options.common import AppiumOptions
        except ImportError as e:
            self.last_error = f'Appium client not installed: {e}'
            print(f"{_LOG} {self.cfg.device_id}: {self.last_error}")
            return False

        endpoint = self.provider.endpoint_url(self.cfg)
        caps = self.provider.session_caps(self.cfg)
        # Plain AppiumOptions, not the platform-specific ones the local controller
        # uses: those inject extra local capabilities, and a farm rejects the session
        # outright on an unexpected key.
        options = AppiumOptions()
        options.load_capabilities(caps)

        print(f"{_LOG} {self.cfg.device_id}: opening {self.cfg.provider} session at {endpoint}")
        print(f"{_LOG} {self.cfg.device_id}: capabilities {redact(caps)}")
        try:
            driver = webdriver.Remote(command_executor=endpoint, options=options)
        except Exception as e:
            # Never echo the exception's request body: it carries the caps, and the
            # caps carry the access key.
            self.last_error = f'{type(e).__name__} while opening the session: {_first_line(e)}'
            print(f"{_LOG} {self.cfg.device_id}: {self.last_error}")
            return False

        from backend_host.src.lib.utils.appium_utils import AppiumUtils
        utils = AppiumUtils()
        # The session key is the host slot id, so every inherited method that passes
        # self.appium_device_id finds this driver.
        utils.drivers[self.cfg.device_id] = driver
        utils.device_platforms[self.cfg.device_id] = self.provider.normalized_platform(
            self.cfg.platform_name).lower()

        self._driver = driver
        self._utils = utils
        self._opened_at = self._last_used = time.time()
        self.session_id = getattr(driver, 'session_id', None)
        self.last_error = None
        print(f"{_LOG} {self.cfg.device_id}: session {self.session_id} open "
              f"({open_session_count()}/{max_sessions()} in use)")
        return True

    def _close_locked(self, quiet: bool) -> None:
        driver, self._driver, self._utils = self._driver, None, None
        if driver is None:
            return
        try:
            driver.quit()
        except Exception as e:
            if not quiet:
                print(f"{_LOG} {self.cfg.device_id}: quit failed (session already gone?): {e}")
        finally:
            print(f"{_LOG} {self.cfg.device_id}: released session {self.session_id}")
            self.session_id = None


def _first_line(error: Exception) -> str:
    """First line of an exception message — WebDriver errors paste whole payloads."""
    return str(error).strip().splitlines()[0][:300] if str(error).strip() else type(error).__name__


# ---- registry ---------------------------------------------------------------
def get_session(cfg: FarmConfig) -> FarmSession:
    """The one lease for this device slot, created on first use."""
    with _REGISTRY_LOCK:
        session = _SESSIONS.get(cfg.device_id)
        if session is None or session.cfg != cfg:
            if session is not None:
                session.release()
            session = FarmSession(cfg)
            _SESSIONS[cfg.device_id] = session
        return session


def peek_session(device_id: str) -> Optional[FarmSession]:
    with _REGISTRY_LOCK:
        return _SESSIONS.get(device_id)


def release_session(device_id: str) -> None:
    with _REGISTRY_LOCK:
        session = _SESSIONS.pop(device_id, None)
    if session is not None:
        session.release()


def release_all() -> None:
    with _REGISTRY_LOCK:
        device_ids = list(_SESSIONS)
    for device_id in device_ids:
        release_session(device_id)
