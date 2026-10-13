#!/usr/bin/env python3
"""One try of the TASK-36 loop: run every saved test prompt of one interface in Explore mode on
one device and print the pass rate as `metric=<0..1>` on the last line.

Reads the repo's `.env` (then `backend_server/.env`) for SERVER_URL and AUTO_SIGN_TOKEN, like the
services do; a value already in the environment wins. The team is the platform's default team
(shared/src/lib/utils/app_utils.py). USER_ID is optional (the control lock's owner).
Usage: task36_explore.py --host host-clone-1 --device device1 --ui sauce-demo [--limit N] [--per-prompt-timeout 300]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def load_env_files() -> None:
    """The services' convention (shared/src/lib/utils/app_utils.py): project .env, then the service's, OS wins."""
    for path in (os.path.join(ROOT, '.env'), os.path.join(ROOT, 'backend_server', '.env')):
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k = k.strip().removeprefix('export ').strip()
                v = v.split(' #')[0].strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v


load_env_files()
SERVER = os.environ.get('SERVER_URL', 'http://localhost:5109').rstrip('/')
TEAM = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'  # the platform's default team, as app_utils.DEFAULT_TEAM_ID
TOKEN = os.environ.get('AUTO_SIGN_TOKEN', '')
USER = os.environ.get('USER_ID', 'research-loop')
SESSION = 'research-loop'


def call(method: str, path: str, body: dict | None = None, timeout: int = 60) -> tuple[int, dict]:
    q = {'team_id': TEAM}
    if TOKEN:
        q['auto_signed'] = TOKEN
    url = f'{SERVER}{path}{"&" if "?" in path else "?"}{urllib.parse.urlencode(q)}'
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={'Content-Type': 'application/json', 'X-User-ID': USER})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except json.JSONDecodeError:
            return e.code, {}


def heartbeat(host: str, device: str, stop: threading.Event) -> None:
    while not stop.wait(30):
        call('POST', '/server/control/heartbeat', {'host_name': host, 'device_id': device, 'session_id': SESSION})


def prompts_for(ui: str, limit: int) -> list[dict]:
    code, out = call('GET', '/server/testprompt/list')
    if code != 200:
        raise SystemExit(f'list failed: {code} {out}')
    found = [p for p in out.get('test_prompts', []) if ui.lower() in json.dumps(p).lower()]
    found.sort(key=lambda p: p.get('name') or p.get('id', ''))
    return found[:limit] if limit else found


def wait_execution(prompt_id: str, execution_id: str, timeout_s: int) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(5)
        code, out = call('GET', f'/server/testprompt/{prompt_id}/executions')
        for row in out.get('executions', []) if code == 200 else []:
            if row.get('id') == execution_id and row.get('status') not in (None, 'running'):
                return row['status']
    return 'timeout'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', required=True)
    ap.add_argument('--device', required=True)
    ap.add_argument('--ui', required=True, help='interface name the prompts belong to')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--per-prompt-timeout', type=int, default=300)
    a = ap.parse_args()
    if not TOKEN:
        raise SystemExit('AUTO_SIGN_TOKEN not found: put it in .env (see .env.example) or the environment')

    prompts = prompts_for(a.ui, a.limit)
    if not prompts:
        raise SystemExit(f'no saved test prompts match {a.ui!r}')
    code, out = call('POST', '/server/control/takeControl', {'host_name': a.host, 'device_id': a.device, 'session_id': SESSION, 'user_id': USER})
    if code != 200:
        raise SystemExit(f'take control failed: {code} {out}')
    stop = threading.Event()
    threading.Thread(target=heartbeat, args=(a.host, a.device, stop), daemon=True).start()
    passed = 0
    results = []
    try:
        for p in prompts:
            pid = p['id']
            code, out = call('POST', '/server/testprompt/execute',
                             {'test_prompt_id': pid, 'host_name': a.host, 'device_id': a.device, 'mode': 'explore',
                              'session_id': SESSION, 'user_id': USER}, timeout=120)
            if code != 200 or not out.get('execution_id'):
                results.append((p.get('name', pid), 'error', f'{code} {str(out)[:80]}'))
                continue
            status = wait_execution(pid, out['execution_id'], a.per_prompt_timeout)
            passed += status == 'passed'
            results.append((p.get('name', pid), status, out['execution_id']))
            print(f'{p.get("name", pid)}: {status}', flush=True)
    finally:
        stop.set()
        call('POST', '/server/control/releaseControl', {'host_name': a.host, 'device_id': a.device, 'session_id': SESSION})
    for name, status, ref in results:
        print(f'  {status:8} {name} ({ref})')
    print(f'passed={passed} total={len(results)}')
    print(f'metric={passed / len(results):.3f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
