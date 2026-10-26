#!/usr/bin/env python3
"""Call one MCP tool and print its text (Localize audit helper, docs/agent/navigation/LOCALIZE_AUDIT.md).

    MCP_SECRET_KEY=... python3 scripts/localize/mcp_call.py localize '{"host_name":"vpt-pi1","device_id":"device1","userinterface_name":"phone_home"}'

MCP_URL defaults to http://localhost:5109/server/mcp (node1's server VM); on vpt-pi1 use
https://localhost/server/mcp (self-signed: certificate not checked). Prints the text blocks,
`[image]` for an image block, and the `localize` / `verdict` field as JSON.
"""
import json
import os
import sys

import requests
import urllib3

urllib3.disable_warnings()


def main() -> int:
    url = os.environ.get('MCP_URL', 'http://localhost:5109/server/mcp')
    name, args = sys.argv[1], json.loads(sys.argv[2] if len(sys.argv) > 2 else '{}')
    r = requests.post(url, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                 'params': {'name': name, 'arguments': args}},
                      headers={'Authorization': 'Bearer ' + os.environ['MCP_SECRET_KEY']}, timeout=600, verify=False)
    res = r.json().get('result') or r.json()
    for c in res.get('content', []):
        print(c.get('text') if c.get('type') == 'text' else f"[{c.get('type')}]")
    for k in ('localize', 'verdict'):
        if k in res:
            print(k, json.dumps(res[k]))
    return 1 if res.get('isError') else 0


if __name__ == '__main__':
    sys.exit(main())
