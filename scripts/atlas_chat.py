#!/usr/bin/env python3
"""
atlas_chat.py — headless one-shot CLI for the Atlas QA agent over Socket.IO.

Use this to test the AI agent end-to-end (skill loading, MCP tool calls,
reasoning) from a terminal — no browser required. Companion to
docs/agent/ai/AGENT_API_TESTING.md.

USAGE
    python3 scripts/atlas_chat.py "your message" [options]

EXAMPLES
    # Default: hits production via auto_signed bypass
    python3 scripts/atlas_chat.py "list available devices"

    # Override server + auth
    SERVER_URL=http://localhost:5109 \
    AUTO_SIGN_TOKEN=<token> \
        python3 scripts/atlas_chat.py "explore sauce-demo"

    # Pin device context (sets host_name / device_id in session, like the UI does)
    python3 scripts/atlas_chat.py "navigate to settings" \
        --host host1 --device device3

    # Filter event types (default: print everything)
    python3 scripts/atlas_chat.py "..." --types message,tool_call,error

EXIT CODES
    0  session_ended cleanly
    1  error event received before session_ended
    2  CLI / connection error
    3  the device is in use: under someone else's vpt-lease (or the lease could not be
       checked), or locked by another session in the product (take-control refused)

DEVICE LEASES
    --host/--device takes control of a real device, so the run first asks vpt-lease whether
    another agent holds it (`VPT_LEASE_CHECK`, default: ssh proxmox ~/bin/vpt-lease check).
    A held device is refused. Where proxmox is unreachable (e.g. on the server VM), check
    the lease yourself and pass --lease-checked. The run then takes control the way the web
    UI does and stops if another session holds the device — it never takes over.

REQUIREMENTS
    pip install python-socketio[client]==5.* requests
    (Already installed in the project venv on the backend server.)
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Set

try:
    import requests
    import socketio
except ImportError as e:
    print(f"missing dep: {e}. install with: pip install 'python-socketio[client]' requests", file=sys.stderr)
    sys.exit(2)


DEFAULT_SERVER = os.environ.get('SERVER_URL', 'https://virtualpytest.angelstreet.io')
DEFAULT_TEAM   = os.environ.get('TEAM_ID',   '7fdeb4bb-3639-4ec3-959f-b54769a219ce')
AUTO_SIGN      = os.environ.get('AUTO_SIGN_TOKEN')
API_KEY        = os.environ.get('API_KEY')
LEASE_CHECK    = os.environ.get('VPT_LEASE_CHECK',
                                'ssh -o BatchMode=yes -o ConnectTimeout=5 proxmox ~/bin/vpt-lease check node1-vpt')


def _redact(text: object) -> str:
    """Error text without the auto-sign token: requests puts the full URL (?auto_signed=...) in HTTPError."""
    out = str(text)
    for secret in (AUTO_SIGN, os.environ.get('ATLAS_BEARER')):
        if secret:
            out = out.replace(secret, '<redacted>')
    return re.sub(r'(auto_signed=)[^&\s]+', r'\1<redacted>', out)


def _service_headers() -> dict:
    """Service credential for /server/*. This script is a non-browser caller, so it
    authenticates with the shared X-API-Key when one is exported — auto-sign alone
    only works on deployments that enable it (docs/agent/platform/SERVER_AUTH.md)."""
    return {'X-API-Key': API_KEY} if API_KEY else {}


def create_session(server: str, verify: bool, auto_sign: str | None) -> str:
    """POST /server/agent/sessions → returns session_id."""
    url = f"{server.rstrip('/')}/server/agent/sessions"
    params = {'auto_signed': auto_sign} if auto_sign else None
    r = requests.post(url, params=params, json={}, headers=_service_headers(),
                      verify=verify, timeout=15)
    r.raise_for_status()
    body = r.json()
    if not body.get('success'):
        raise RuntimeError(f"session create failed: {body}")
    return body['session']['id']


class DeviceBusy(Exception):
    """The device is under someone else's product lock (the server answered 423)."""


def take_device_control(server: str, verify: bool, auto_sign: str | None,
                        host_name: str, device_id: str, session_id: str) -> None:
    """POST /server/control/takeControl — the same lock the web UI takes — so the first
    execute_device_action finds the device ready. A device another session holds is
    refused (DeviceBusy), never taken over: this used /server/control/takeover, which
    preempts any manual lock and stops a running script (BUG-0402)."""
    url = f"{server.rstrip('/')}/server/control/takeControl"
    params = {'team_id': DEFAULT_TEAM, **({'auto_signed': auto_sign} if auto_sign else {})}
    payload = {
        'host_name': host_name,
        'device_id': device_id,
        'session_id': session_id,
        'user_name': 'atlas_chat',
    }
    r = requests.post(url, params=params, json=payload, headers=_service_headers(),
                      verify=verify, timeout=15)
    body = r.json() if r.content else {}
    if r.status_code == 423 or body.get('errorType') == 'device_locked':
        who = body.get('owner_user_name') or body.get('owner_user_id') or body.get('owner_session_id')
        raise DeviceBusy(f"locked by {body.get('owner_type') or 'another session'}"
                         + (f" ({who})" if who else ''))
    r.raise_for_status()
    if not body.get('success', True):  # some builds omit 'success' on happy path
        raise RuntimeError(f"takeControl failed: {body}")


def release_device_control(server: str, verify: bool, auto_sign: str | None,
                           host_name: str, device_id: str, session_id: str) -> None:
    """POST /server/control/releaseControl for the lock take_device_control took."""
    url = f"{server.rstrip('/')}/server/control/releaseControl"
    params = {'auto_signed': auto_sign} if auto_sign else None
    payload = {'host_name': host_name, 'device_id': device_id, 'session_id': session_id}
    r = requests.post(url, params=params, json=payload, headers=_service_headers(),
                      verify=verify, timeout=15)
    r.raise_for_status()


def lease_holder(host: str, device: str) -> str | None:
    """None when no other agent leases host/device; otherwise who holds it (or why we can't tell).

    A test chat once took a phone mid-recording under another session's lease (2026-10-04):
    taking control is never safe without asking vpt-lease first.
    """
    try:
        out = subprocess.run(shlex.split(LEASE_CHECK) + [f'{host}/{device}'],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f'vpt-lease could not be checked ({e})'
    if out.returncode == 0:
        return None
    detail = (out.stdout + out.stderr).strip()
    if out.returncode == 3:
        return detail or 'busy'
    return f'vpt-lease could not be checked (exit {out.returncode}): {detail[-300:]}'


def run(args) -> int:
    server = args.server.rstrip('/')
    verify = not args.insecure

    if args.host and args.device and not args.lease_checked:
        holder = lease_holder(args.host, args.device)
        if holder:
            print(f"[atlas_chat] refusing to take {args.host}/{args.device}: {holder}\n"
                  "  wait for the lease, pick another device, or check it yourself and pass --lease-checked",
                  file=sys.stderr)
            return 3

    # 1) Create the session via REST.
    try:
        session_id = create_session(server, verify, args.auto_sign)
    except Exception as e:
        print(f"[ERROR] could not create session: {_redact(e)}", file=sys.stderr)
        return 2
    print(f"[atlas_chat] session_id={session_id}", file=sys.stderr)

    # 1b) Acquire device control BEFORE the agent runs. Otherwise the first
    # execute_device_action races the implicit lease acquisition and returns
    # 404 "could not find the requested resource" — Atlas retries after ~5s
    # but we waste time and emit a spurious ERROR event.
    took_control = False
    if args.host and args.device:
        try:
            take_device_control(server, verify, args.auto_sign,
                                args.host, args.device, session_id)
            took_control = True
            print(f"[atlas_chat] took control of {args.host}/{args.device}", file=sys.stderr)
        except DeviceBusy as e:
            # Someone else is using the device. Do not chat against it: Atlas's device tools
            # would drive it under the other session's lock.
            print(f"[atlas_chat] refusing to use {args.host}/{args.device}: {e}", file=sys.stderr)
            return 3
        except Exception as e:
            # Non-fatal: some deployments don't require take-control; fall back to
            # the old behavior (Atlas retries on first action) rather than
            # failing the whole run.
            print(f"[atlas_chat] take-control warning (continuing): {_redact(e)}", file=sys.stderr)

    # The device lock outlives this process unless it is released: a one-shot chat used to
    # leave the device under manual_control for everyone else. `timeout` stops us with
    # SIGTERM, so turn that into a normal exit and release in `finally`.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
    try:
        return _chat(args, server, verify, session_id)
    finally:
        if took_control:
            try:
                release_device_control(server, verify, args.auto_sign, args.host, args.device, session_id)
                print(f"[atlas_chat] released control of {args.host}/{args.device}", file=sys.stderr)
            except Exception as e:
                print(f"[atlas_chat] WARNING: could not release {args.host}/{args.device}: {_redact(e)}", file=sys.stderr)


def _chat(args, server: str, verify: bool, session_id: str) -> int:
    # 2) Connect to /agent namespace and send the message.
    sio = socketio.Client(ssl_verify=verify, reconnection=False, logger=False, engineio_logger=False)
    done = threading.Event()
    exit_code = {'rc': 1}  # default to "ended without success"
    type_filter: Set[str] | None = set(args.types.split(',')) if args.types else None

    def emit_user_msg() -> None:
        payload: Dict[str, Any] = {
            'session_id': session_id,
            'message':    args.message,
            'team_id':    args.team_id,
            'agent_id':   args.agent_id,
            'allow_auto_navigation': args.allow_auto_navigation,
            'current_page':       args.current_page,
            'host_name':          args.host or '',
            'device_id':          args.device or '',
            'userinterface_name': args.userinterface or '',
        }
        sio.emit('send_message', payload, namespace='/agent')

    @sio.on('connect', namespace='/agent')
    def _on_connect() -> None:
        print('[atlas_chat] connected', file=sys.stderr)
        sio.emit('join_session', {'session_id': session_id}, namespace='/agent')
        emit_user_msg()

    @sio.on('joined', namespace='/agent')
    def _on_joined(data: Dict[str, Any]) -> None:
        print(f"[atlas_chat] joined session room {data}", file=sys.stderr)

    # Catch-all: log every socketio event we receive on /agent, BEFORE any
    # filtering. This is the only way to distinguish "server never emitted"
    # from "server emitted but our handler dropped it silently".
    @sio.on('*', namespace='/agent')
    def _on_any(event_name, *data) -> None:
        try:
            preview = json.dumps(data[0] if data else None, default=str)[:200]
        except Exception:
            preview = repr(data)[:200]
        print(f"[recv] {event_name} {preview}", file=sys.stderr)

    @sio.on('agent_event', namespace='/agent')
    def _on_event(event: Dict[str, Any]) -> None:
        etype = event.get('type', '?')
        agent = event.get('agent', '?')
        # Compact line for known noisy types
        if type_filter is not None and etype not in type_filter:
            return
        if args.json:
            print(json.dumps(event, default=str))
        else:
            content = event.get('content', '')
            if isinstance(content, (dict, list)):
                content = json.dumps(content, default=str)[:400]
            else:
                content = str(content)[:400]
            print(f"[{etype:14}] {agent:8} | {content}")
        if etype == 'error':
            exit_code['rc'] = 1
        if etype == 'session_ended':
            exit_code['rc'] = 0 if exit_code['rc'] != 1 else 0
            done.set()

    @sio.on('error', namespace='/agent')
    def _on_err(data: Dict[str, Any]) -> None:
        print(f"[atlas_chat] socket error: {data}", file=sys.stderr)
        exit_code['rc'] = 1
        done.set()

    @sio.on('disconnect', namespace='/agent')
    def _on_disconnect() -> None:
        print('[atlas_chat] disconnected', file=sys.stderr)
        done.set()

    try:
        # The /agent namespace authenticates its handshake now (BUG-0156). This script's
        # REST calls already carry the service key or the auto-sign token; the socket has to
        # present the same, or the connect is refused. python-socketio can set headers, so
        # the header form works here even though a browser has to use the auth payload.
        sio.connect(
            server, namespaces=['/agent'], wait_timeout=20,
            headers=_service_headers(),
            auth={'auto_sign': args.auto_sign} if args.auto_sign else None,
        )
    except Exception as e:
        print(f"[ERROR] socket connect failed: {e}", file=sys.stderr)
        return 2

    # 3) Wait for session_ended (or timeout)
    if not done.wait(timeout=args.timeout):
        print(f"[atlas_chat] timed out after {args.timeout}s", file=sys.stderr)
        exit_code['rc'] = 2
    try:
        sio.disconnect()
    except Exception:
        pass
    return exit_code['rc']


def main() -> int:
    ap = argparse.ArgumentParser(
        description='Headless Atlas chat over Socket.IO (one-shot).',
    )
    ap.add_argument('message', help='User message to send to the agent')
    ap.add_argument('--server', default=DEFAULT_SERVER,
                    help=f'Backend URL (default: {DEFAULT_SERVER}; or env SERVER_URL)')
    ap.add_argument('--auto-sign', default=AUTO_SIGN, dest='auto_sign',
                    help='AUTO_SIGN_TOKEN for auth bypass (or env AUTO_SIGN_TOKEN)')
    ap.add_argument('--team-id', default=DEFAULT_TEAM, dest='team_id',
                    help=f'Team UUID (default: {DEFAULT_TEAM}; or env TEAM_ID)')
    ap.add_argument('--agent-id', default='assistant', dest='agent_id',
                    help='assistant | monitor | analyzer (default: assistant = Atlas)')
    ap.add_argument('--host',          default=None, help='host_name context')
    ap.add_argument('--device',        default=None, help='device_id context')
    ap.add_argument('--userinterface', default=None, help='userinterface_name context')
    ap.add_argument('--current-page',  default='/', dest='current_page')
    ap.add_argument('--allow-auto-navigation', action='store_true',
                    dest='allow_auto_navigation')
    ap.add_argument('--types', default=None,
                    help='Comma-separated agent_event types to print (default: all)')
    ap.add_argument('--json',  action='store_true', help='Emit raw JSON for each event')
    ap.add_argument('--timeout', type=int, default=600,
                    help='Hard timeout in seconds (default: 600)')
    ap.add_argument('--lease-checked', action='store_true', dest='lease_checked',
                    help='Skip the vpt-lease check for --host/--device (you checked it yourself)')
    ap.add_argument('--insecure', action='store_true',
                    help='Skip TLS verification (self-signed certs)')
    args = ap.parse_args()

    if not AUTO_SIGN and not args.auto_sign and args.server.startswith('https://'):
        # Heuristic warning, not fatal
        print('[atlas_chat] WARN: no AUTO_SIGN_TOKEN — request may be 401 unless auth is otherwise configured', file=sys.stderr)

    return run(args)


if __name__ == '__main__':
    sys.exit(main())
