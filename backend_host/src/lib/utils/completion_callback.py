"""The host's completion callback to the server, with a bounded retry.

The callback is what closes the deployment_executions row and releases the device lock.
The host used to set "callback sent" as soon as the POST returned, before looking at the
status code: a callback the server rejected (or that timed out) was counted as sent, was
never retried, and the recovery callback in the `finally` was skipped. The row then stayed
in 'running' until the server's reaper - which was itself blocked by the per-device busy
check (E50).

True is returned only when the server answered 2xx: a rejected callback was never applied,
so the caller must keep the row open and try again. The retries are bounded, so a server
that keeps refusing does not become a loop.
"""

import time
from typing import Any, Dict, Optional

# How often a rejected callback is retried, and how long the host waits between two
# attempts.
CALLBACK_RETRY_ATTEMPTS = 3
CALLBACK_RETRY_DELAY_SECONDS = 2.0
CALLBACK_TIMEOUT_SECONDS = 30


def post_completion_callback(callback_url: str, payload: Dict[str, Any],
                             attempts: int = CALLBACK_RETRY_ATTEMPTS,
                             delay_seconds: float = CALLBACK_RETRY_DELAY_SECONDS) -> bool:
    """POST the completion callback, retrying while the server rejects it.

    True only when the server answered 2xx.
    """
    import requests
    from shared.src.lib.utils.build_url_utils import server_auth_headers

    total = max(1, int(attempts))
    for attempt in range(1, total + 1):
        try:
            response = requests.post(
                callback_url, json=payload,
                headers=server_auth_headers(), timeout=CALLBACK_TIMEOUT_SECONDS,
            )
            if response.ok:
                print(f"[@completion_callback] Callback sent successfully (status={response.status_code})")
                return True
            body_preview = (getattr(response, 'text', '') or '')[:500]
            print(f"[@completion_callback] Callback FAILED (attempt {attempt}/{total}): "
                  f"status={response.status_code} body={body_preview}")
        except Exception as exc:
            print(f"[@completion_callback] Callback attempt {attempt}/{total} raised: {exc}")
        if attempt < total:
            time.sleep(delay_seconds)
    return False
