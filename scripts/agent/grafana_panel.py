#!/usr/bin/env python3
"""Screenshot the Grafana dashboard page and report what it shows.

Usage:  T=<auto-sign token> python3 scripts/agent/grafana_panel.py <base-url> <out-png> [label]

Prints whether an iframe is embedded and which message the page shows. The token
is read from the environment and never printed.
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5087"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/grafana.png"
LABEL = sys.argv[3] if len(sys.argv) > 3 else "grafana"

TOKEN = os.environ.get("T", "")
if not TOKEN:
    sys.exit("T (auto-sign token) must be in the environment")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    page.goto(f"{BASE}/?auto_signed={TOKEN}", wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    page.goto(f"{BASE}/grafana-dashboard?auto_signed={TOKEN}", wait_until="domcontentloaded")
    page.wait_for_timeout(9000)

    state = page.evaluate(
        """() => {
            const iframe = document.querySelector('iframe');
            const text = document.body.innerText;
            return {
                hasIframe: Boolean(iframe),
                iframeSrc: iframe ? iframe.getAttribute('src') : null,
                iframeTitle: iframe ? iframe.getAttribute('title') : null,
                hasPicker: Boolean(document.querySelector('#dashboard-select')),
                signIn: text.includes('Grafana asks for a sign-in'),
                noAnswer: text.includes('Grafana did not answer'),
                body: text.slice(0, 400),
            };
        }"""
    )
    page.screenshot(path=OUT, full_page=False)
    browser.close()

print(f"[{LABEL}] iframe: {state['hasIframe']} ({state['iframeTitle']})")
print(f"[{LABEL}] picker: {state['hasPicker']} | sign-in panel: {state['signIn']} | no-answer panel: {state['noAnswer']}")
print(f"[{LABEL}] iframe src: {state['iframeSrc']}")
print(f"[{LABEL}] screenshot: {OUT}")
