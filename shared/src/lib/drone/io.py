"""
DroneIO: what a game needs from one drone (commands, frames, telemetry).

LocalDroneIO talks to a drone (or simulator) directly with TelloClient + FrameGrabber.
PlatformDroneIO (platform_io.py) goes through the host's action executor instead.
"""

import time
from typing import Optional, Protocol, Tuple

import numpy as np

from .tello import TelloClient, TelloError
from .video import FrameGrabber


class DroneIO(Protocol):
    name: str
    index: int

    def command(self, cmd: str, timeout_s: Optional[float] = None) -> Tuple[bool, str]: ...

    def frame(self, fresh: bool = False) -> Optional[np.ndarray]: ...

    def telemetry(self) -> dict: ...

    def close(self) -> None: ...


class LocalDroneIO:
    def __init__(self, client: TelloClient, grabber: FrameGrabber, name: str, index: int):
        self.client = client
        self.grabber = grabber
        self.name = name
        self.index = index

    def command(self, cmd: str, timeout_s: Optional[float] = None) -> Tuple[bool, str]:
        try:
            reply = self.client.send(cmd, timeout_s=timeout_s)
        except TelloError as e:
            return False, str(e)
        reply = reply.strip()
        return bool(reply) and not reply.lower().startswith("error"), reply

    def frame(self, fresh: bool = False) -> Optional[np.ndarray]: ...

    def telemetry(self) -> dict: ...

    def close(self) -> None: ...


class LocalDroneIO:
    def __init__(self, client: TelloClient, grabber: FrameGrabber, name: str, index: int):
        self.client = client
        self.grabber = grabber
        self.name = name
        self.index = index

    def command(self, cmd: str, timeout_s: Optional[float] = None) -> Tuple[bool, str]:
        try:
            reply = self.client.send(cmd, timeout_s=timeout_s)
        except TelloError as e:
            return False, str(e)
        return reply.strip().lower() == "ok" or (reply != "" and not reply.lower().startswith("error")
                                                  and cmd.endswith("?")), reply

    def frame(self, fresh: bool = False) -> Optional[np.ndarray]:
        if fresh:
            return self.grabber.wait_frame(time.time(), timeout_s=3.0)
        return self.grabber.latest()[0]

    def telemetry(self) -> dict:
        return self.client.state()

    def start_keepalive(self, period_s: float = 5.0) -> None:
        self.client.start_keepalive(period_s)

    def stop_keepalive(self) -> None:
        self.client.stop_keepalive()

    def close(self) -> None:
        for fn in (self.client.stop_keepalive, self.grabber.stop, self.client.close):
            try:
                fn()
            except Exception:
                pass
