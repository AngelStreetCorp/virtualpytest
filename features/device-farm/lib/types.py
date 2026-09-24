"""Typed values passed between the config reader, the providers and the host side.

Deliberately plain dataclasses: they cross a feature boundary and end up in log
lines and test assertions, so they carry no behaviour beyond `redacted()`.
"""
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class FarmConfig:
    """Everything one device slot needs to open a session on one farm."""
    device_id: str                      # host slot id ('device1') — the session key
    device_name: str                    # slot label, used as the farm session name
    provider: str                       # 'saucelabs' | 'browserstack' | 'lambdatest'
    username: str
    access_key: str
    platform_name: str                  # 'Android' | 'iOS'
    region: Optional[str] = None        # provider datacenter; None = provider default
    device_query: Optional[str] = None  # device name or pattern for dynamic allocation
    platform_version: Optional[str] = None
    app_ref: Optional[str] = None       # provider app reference (storage:… / bs:// / lt://)
    build: Optional[str] = None
    idle_timeout: int = 180
    max_duration: int = 1800
    screenshot_fps: float = 1.0
    extra_caps: Dict[str, Any] = field(default_factory=dict)

    def redacted(self) -> 'FarmConfig':
        """Copy safe to print: the access key is the only secret this object holds."""
        return replace(self, access_key='***' if self.access_key else '')

    def __str__(self) -> str:  # pragma: no cover - trivial
        r = self.redacted()
        return (f"FarmConfig({r.device_id} {r.provider} {r.platform_name} "
                f"device={r.device_query!r} os={r.platform_version!r} user={r.username!r})")


@dataclass(frozen=True)
class FarmDevice:
    """One device the farm says it can allocate (provider device-list API)."""
    name: str
    platform_name: str
    platform_version: str
    available: bool = True
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionArtifacts:
    """Where a finished session can be looked at in the farm's own UI."""
    session_id: str
    session_url: Optional[str] = None
    video_url: Optional[str] = None
    logs: List[str] = field(default_factory=list)
