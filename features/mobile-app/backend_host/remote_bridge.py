"""
features/mobile-app/backend_host/remote_bridge.py — the PhoneBridge stand-in for a
process that is NOT the host's Flask app.

`PhoneBridge` owns the Socket.IO session to the phone, so it only exists inside
vpt-host. Scripts do not run there: `ScriptExecutor._execute_script_subprocess`
launches every script as its own Python process, which builds its own Host and its
own controllers (`controller_manager.create_host_from_environment`). That process
has no app, no socketio and no bridge — so before this module a `phone_agent`
device came up with `remote` missing and the first navigation action failed with
"Remote controller not available" (TASK-17 §6 step 5 was never actually reachable).

`RemoteBridgeClient` gives `PhoneAgentRemoteController` the only two things it asks
of a bridge — `rpc()` and `get_slot()` — by calling back into the host process over
its own REST API. The controller itself is unchanged and cannot tell the difference.

Frames are the exception: the subprocess runs on the same machine as the host, so
`_SlotView.frame_path` is read straight off disk rather than pulled through HTTP.
"""
import os
from typing import Any, Dict, Optional

import requests

from ..lib import protocol

_LOG = '[@mobile-app:remote_bridge]'
# The host answers from its own process; allow for the phone round-trip it makes on
# our behalf plus a little slack, so the HTTP call never expires before the RPC does.
_HTTP_SLACK_S = 5.0


class _SlotView:
    """The handful of slot fields PhoneAgentRemoteController reads, from /host/phone/slots."""

    def __init__(self, summary: Dict[str, Any]):
        self.device_id = summary.get('device_id')
        self.device_name = summary.get('device_name')
        self.state = summary.get('state', 'free')
        self.phone = summary.get('phone')
        self.last_seen = summary.get('last_seen')
        self.fps = summary.get('fps') or 0.0
        self.frame_path = summary.get('frame_path') or ''
        self.capture_path = summary.get('capture_path') or ''


class RemoteBridgeClient:
    """Talks to the PhoneBridge living in this host's vpt-host process over /host/phone."""

    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = (base_url or _host_api_url()).rstrip('/')
        self.api_key = api_key or os.getenv('API_KEY', '')

    # ---- the bridge surface PhoneAgentRemoteController uses -----------------

    def rpc(self, device_id: str, name: str, params: Optional[Dict[str, Any]] = None,
            timeout: Optional[float] = None) -> Dict[str, Any]:
        rpc_timeout = timeout or (protocol.CMD_TIMEOUT_SLOW_S if protocol.is_slow_command(name)
                                  else protocol.CMD_TIMEOUT_S)
        try:
            resp = self._post('/host/phone/rpc', {
                'device_id': device_id,
                'name': name,
                'params': params or {},
                'timeout': rpc_timeout,
            }, timeout=rpc_timeout + _HTTP_SLACK_S)
        except Exception as e:
            print(f"{_LOG} {device_id}: cmd '{name}' could not reach the host: {e}")
            return {'ok': False, 'error': f'host unreachable: {e}'}
        if not isinstance(resp, dict):
            return {'ok': False, 'error': f"malformed ack for '{name}': {resp!r}"}
        return resp

    def get_slot(self, device_id: str) -> Optional[_SlotView]:
        try:
            resp = self._get(f'/host/phone/slots/{device_id}')
        except Exception as e:
            print(f"{_LOG} {device_id}: slot lookup failed: {e}")
            return None
        slot = (resp or {}).get('slot')
        return _SlotView(slot) if isinstance(slot, dict) else None

    # ---- http ---------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {'X-API-Key': self.api_key, 'Content-Type': 'application/json'}

    def _get(self, path: str, timeout: float = 10.0) -> Dict[str, Any]:
        resp = requests.get(f'{self.base_url}{path}', headers=self._headers(), timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        resp = requests.post(f'{self.base_url}{path}', json=payload,
                             headers=self._headers(), timeout=timeout)
        # A refused command answers 200 with ok:false; only transport/auth failures
        # raise, and rpc() turns those into the same {'ok': False} shape.
        resp.raise_for_status()
        return resp.json()


def _host_api_url() -> str:
    """Where this host's own API listens. HOST_API_URL is what the host advertises to
    phones and is what it actually binds (backend_host/src/app.py parse_host_api_url),
    so 127.0.0.1 is NOT a safe fallback — the host binds one interface, not loopback."""
    url = os.getenv('HOST_API_URL', '').strip()
    if url:
        return url
    return f"http://{os.getenv('HOST_IP', '127.0.0.1')}:{os.getenv('HOST_PORT', '6109')}"
