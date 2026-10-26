#!/usr/bin/env python3
"""Check that every Grafana dashboard ends with a collapsed "Details" section.

The house rule: a dashboard opens on its overview and the detail tables live in
a collapsed row at the bottom, like the "Script Results" dashboard. This is the
gate for it - it fails on a dashboard that has no rows, whose last row is not
collapsed, or whose last row is not the "Details" section.

It also fails on a collapsed row whose panels are still trailing siblings
instead of nested inside the row: Grafana only renders them when they are
inside.

Usage:  python3 _check_details_row.py [dashboard.json ...]
        (default: every *.json next to this script except template.json)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DETAIL_ROW_TITLE = "Details"


def dashboard_files():
    """Every dashboard in the repo: this folder and each feature's grafana/ folder."""
    root = HERE.parents[3]
    files = sorted(HERE.glob("*.json")) + sorted(root.glob("features/*/grafana/*.json"))
    return [f for f in files if not (f.parent == HERE and f.name == "template.json")]


def problems(dashboard):
    """The reasons this dashboard does not follow the house shape."""
    panels = dashboard.get("panels", [])
    if not panels:
        return ["no panels"]
    rows = [p for p in panels if p.get("type") == "row"]
    if not rows:
        return ["no rows: the dashboard must end with a collapsed 'Details' section"]
    last = rows[-1]
    issues = []
    if last.get("title") != DETAIL_ROW_TITLE:
        issues.append(f"the last row is {last.get('title')!r}, not {DETAIL_ROW_TITLE!r}")
    if not last.get("collapsed"):
        issues.append("the last row is not collapsed")
    if rows[-1] is not panels[-1]:
        issues.append("the last row is not the last thing on the dashboard")
    trailing = [p for p in panels[panels.index(last) + 1:] if p.get("type") != "row"]
    if trailing:
        issues.append(f"{len(trailing)} panel(s) still trail the row instead of sitting inside it")
    if last.get("collapsed") and not (last.get("panels") or []):
        issues.append("the collapsed row holds no panel")
    return issues


def main():
    files = sys.argv[1:]
    if not files:
        files = [str(p) for p in dashboard_files()
                 if "panels" in json.loads(p.read_text(encoding="utf-8"))]
    failed = 0
    for path in files:
        p = Path(path)
        dashboard = json.loads(p.read_text(encoding="utf-8"))
        issues = problems(dashboard)
        if issues:
            failed += 1
            print(f"FAIL {p.name}: {'; '.join(issues)}")
        else:
            print(f"ok   {p.name}")
    print("failed:", failed)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
