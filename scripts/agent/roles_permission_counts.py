#!/usr/bin/env python3
"""Read the permission counts of the Roles page in a real browser.

Usage:  T=<auto-sign token> python3 scripts/agent/roles_permission_counts.py <base-url> <out-png> [label]

Prints the number in the Permissions column of every role row. The token is read
from the environment and never printed.
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5087"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/roles.png"
LABEL = sys.argv[3] if len(sys.argv) > 3 else "roles"

TOKEN = os.environ.get("T", "")
if not TOKEN:
    sys.exit("T (auto-sign token) must be in the environment")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_context(viewport={"width": 1440, "height": 1000}).new_page()
    page.goto(f"{BASE}/?auto_signed={TOKEN}", wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    page.goto(f"{BASE}/roles?auto_signed={TOKEN}", wait_until="domcontentloaded")
    page.wait_for_timeout(9000)

    rows = page.evaluate(
        """() => {
            const out = [];
            for (const tr of document.querySelectorAll('tr')) {
                const cells = [...tr.querySelectorAll('td')].map((td) => (td.innerText || '').trim());
                if (cells.length >= 3) out.push(cells.slice(0, 3));
            }
            return out;
        }"""
    )
    page.screenshot(path=OUT, full_page=False)
    browser.close()

print(f"[{LABEL}] roles table rows:")
for cells in rows:
    print(f"[{LABEL}]   {cells[0]!r} -> permissions {cells[2]!r}")
print(f"[{LABEL}] screenshot: {OUT}")
