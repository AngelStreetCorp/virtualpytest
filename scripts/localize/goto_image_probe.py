#!/usr/bin/env python3
"""What an agent's goto exploration sends to the model (TASK-107 goal 5 measurement).

Drives one fixed exploration through the MCP endpoint — the same navigate_to_node calls an Atlas
agent makes — and counts what each tool result carries: images (and their model tokens) and
whether a Localize verdict came back. Run it once on the old code (every goto attaches a
screenshot) and once on the new code (Localize verdict; a screenshot only when it does not
confirm the target).

    python3 scripts/localize/goto_image_probe.py --server https://localhost --host vpt-pi1 \
        --device device3 --ui stb_tv --targets home_tvguide,live,home_tvguide,home --insecure

Image tokens use the Claude vision rule (width x height / 750, after the API's resize to at most
1568 px on the long side): the cost of the image in the call that receives it and in every later
call of the conversation that keeps it.
"""
import argparse
import base64
import json
import os
import struct
import sys
import time

import requests


def png_size(b64: str):
    raw = base64.b64decode(b64[:200] + '=' * (-len(b64[:200]) % 4))
    if raw[:8] == b'\x89PNG\r\n\x1a\n':
        return struct.unpack('>II', raw[16:24])
    # JPEG: scan for SOF0/2
    raw = base64.b64decode(b64)
    i = 2
    while i < len(raw):
        if raw[i] != 0xFF:
            i += 1
            continue
        marker, seg = raw[i + 1], struct.unpack('>H', raw[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC2):
            h, w = struct.unpack('>HH', raw[i + 5:i + 9])
            return w, h
        i += 2 + seg
    return 0, 0


def image_tokens(w: int, h: int) -> int:
    scale = min(1.0, 1568.0 / max(w, h, 1))
    return int((w * scale) * (h * scale) / 750)


def call(server, token, name, args, verify):
    body = {'jsonrpc': '2.0', 'id': int(time.time() * 1000), 'method': 'tools/call',
            'params': {'name': name, 'arguments': args}}
    r = requests.post(f"{server}/server/mcp", json=body, timeout=300, verify=verify,
                      headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    r.raise_for_status()
    return r.json().get('result') or r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server', default='https://localhost')
    ap.add_argument('--host', required=True)
    ap.add_argument('--device', required=True)
    ap.add_argument('--ui', required=True)
    ap.add_argument('--targets', required=True)
    ap.add_argument('--team', default=os.environ.get('TEAM_ID', '7fdeb4bb-3639-4ec3-959f-b54769a219ce'))
    ap.add_argument('--insecure', action='store_true')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    token = os.environ['MCP_SECRET_KEY']
    steps, started = [], time.time()
    for target in a.targets.split(','):
        t0 = time.time()
        res = call(a.server, token, 'navigate_to_node',
                   {'host_name': a.host, 'device_id': a.device, 'userinterface_name': a.ui,
                    'target_node_label': target, 'team_id': a.team}, not a.insecure)
        content = res.get('content') or []
        images = [c for c in content if c.get('type') == 'image']
        sizes = [png_size(c['data']) for c in images]
        text = ' '.join(c.get('text', '') for c in content if c.get('type') == 'text')
        loc = next((line for line in text.split('\n') if 'Localize:' in line), None)
        step = {'target': target, 'ok': not res.get('isError'), 'images': len(images),
                'image_tokens': sum(image_tokens(w, h) for w, h in sizes), 'image_px': sizes,
                'text_chars': len(text), 'localize': loc, 'seconds': round(time.time() - t0, 1)}
        steps.append(step)
        print(json.dumps(step))
    total = {'steps': len(steps), 'images': sum(s['images'] for s in steps),
             'image_tokens': sum(s['image_tokens'] for s in steps),
             'text_chars': sum(s['text_chars'] for s in steps), 'seconds': round(time.time() - started, 1)}
    print('TOTAL', json.dumps(total))
    if a.out:
        json.dump({'steps': steps, 'total': total}, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    sys.exit(main())
