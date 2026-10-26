#!/usr/bin/env python3
"""Read the dashboard's "AI usage" card value in a real browser.

Usage:  T=<auto-sign token> python3 scripts/agent/dashboard_ai_usage.py <base-url> <out-png> [label]

Clicks the System tab and prints the money the "AI usage" card shows. The token
is read from the environment and never printed.
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5087"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dashboard.png"
LABEL = sys.argv[3] if len(sys.argv) > 3 else "dashboard"

TOKEN = os.environ.get("T", "")
if not TOKEN:
    sys.exit("T (auto-sign token) must be in the environment")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_context(viewport={"width": 1440, "height": 1000}).new_page()
    page.goto(f"{BASE}/?auto_signed={TOKEN}", wait_until="domcontentloaded")
    page.wait_for_timeout(7000)

    # The dashboard opens on the favourite tab; the System tab holds the AI usage card.
    for label in ("System", "Système", "System"):
        try:
            page.get_by_role("tab", name=label).first.click(timeout=3000)
            break
        except Exception:
            try:
                page.get_by_text(label, exact=True).first.click(timeout=3000)
                break
            except Exception:
                continue
    page.wait_for_timeout(9000)

    value = page.evaluate(
        """() => {
            // The card carries data-testid="dash-card-ai-usage".
            const card = document.querySelector('[data-testid="dash-card-ai-usage"]');
            const el = card ? card.querySelector('.stat-value') : null;
            return { value: el ? el.textContent : null, found: Boolean(el) };
        }"""
    )
    page.screenshot(path=OUT, full_page=False)
    browser.close()

print(f"[{LABEL}] AI usage card value: {value['value']} (found: {value['found']})")
print(f"[{LABEL}] screenshot: {OUT}")
