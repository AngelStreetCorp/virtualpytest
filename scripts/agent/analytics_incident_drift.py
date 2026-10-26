#!/usr/bin/env python3
"""Sample the open-incident figure on the Analytics Overview and Incidents tabs.

Usage:  T=<auto-sign token> python3 scripts/agent/analytics_incident_drift.py [base-url] [samples] [interval]

Prints one line per sample: the Overview tile's "Open incidents", the Incidents tab's
"still open", the age of each cached section, and whether the two agree. The token is
read from the environment and never printed.
"""
import os
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://virtualpytest.angelstreet.io"
SAMPLES = int(sys.argv[2]) if len(sys.argv) > 2 else 15
INTERVAL = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0

TOKEN = os.environ.get("T", "")
if not TOKEN:
    sys.exit("T (auto-sign token) must be in the environment")


def get(path: str):
    request = urllib.request.Request(
        f"{BASE}{path}",
        headers={"X-Auto-Sign": TOKEN, "User-Agent": "Mozilla/5.0 (vpt-agent-drift-sampler)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


import json  # noqa: E402  (after the helper, so the error message stays readable)


def team_id() -> str:
    """The frontend asks for a section without a team_id, so the sampler does too."""
    return ""


def section_age(section: str, team: str) -> float:
    stats = get("/server/analytics/_cache")
    ages = [e["age_seconds"] for e in stats.get("entries", [])
            if e["section"] == section and (e.get("team_id") or "") == team]
    return ages[0] if ages else float("nan")


TEAM = team_id()
print(f"  t(s) overview_open  incidents_open  age_ov  age_inc  match")

for index in range(SAMPLES):
    overview = get(f"/server/analytics/overview?team_id={TEAM}")
    incidents = get(f"/server/analytics/incidents?team_id={TEAM}")
    open_overview = (overview.get("data") or {}).get("tiles", {}).get("incidents_open")
    open_incidents = (incidents.get("data") or {}).get("open")
    age_overview = section_age("overview", TEAM)
    age_incidents = section_age("incidents", TEAM)
    match = "OK" if open_overview == open_incidents else "*** MISMATCH ***"
    print(f"  {index * int(INTERVAL):<5} {open_overview!s:<15} {open_incidents!s:<15} "
          f"{age_overview:<7} {age_incidents:<8} {match}")
    if index < SAMPLES - 1:
        time.sleep(INTERVAL)
