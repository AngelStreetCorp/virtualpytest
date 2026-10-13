"""
Read an async execution's status, optionally waiting a bounded time for it to end.

Shared by the MCP testcase and script status tools.
"""

import time
from typing import Any, Callable, Dict

from .execution_status_constants import (
    STATUS_READ_INTERVAL_S,
    STATUS_WAIT_DEFAULT_S,
    STATUS_WAIT_MAX_S,
)


def is_transient_read_failure(response: Dict[str, Any]) -> bool:
    """A status read that timed out, failed on the network or got a 5xx says nothing about the run."""
    if response.get('success'):
        return False
    return bool(response.get('timeout') or response.get('network_error')
                or int(response.get('status_code') or 0) >= 500)


def clamp_wait_seconds(value: Any) -> int:
    """wait_seconds from the caller, defaulted and capped so a status call stays short."""
    if value is None or value == '':
        return STATUS_WAIT_DEFAULT_S
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return STATUS_WAIT_DEFAULT_S
    return max(0, min(seconds, STATUS_WAIT_MAX_S))


def read_until_done(read: Callable[[], Dict[str, Any]],
                    is_done: Callable[[Dict[str, Any]], bool],
                    wait_seconds: int) -> Dict[str, Any]:
    """
    Call read() until is_done(response) is true, a non-transient error comes back, or
    wait_seconds of wall time pass. Returns the last response read.
    """
    started = time.time()
    while True:
        response = read()
        if response.get('success') and is_done(response):
            return response
        if not response.get('success') and not is_transient_read_failure(response):
            return response
        if time.time() - started + STATUS_READ_INTERVAL_S > wait_seconds:
            return response
        time.sleep(STATUS_READ_INTERVAL_S)
