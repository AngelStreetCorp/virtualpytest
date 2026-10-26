#!/usr/bin/env python3
"""Make every Grafana dashboard end with a collapsed "Details" section.

The house rule, taken from the "Script Results" dashboard: a dashboard opens on
its overview, and the detail tables live in a row at the bottom that is
collapsed by default. The same shape is used by Campaign Results, DNS Lookup,
KPI Measurement, Ookla Speedtest and Superping.

What this does to a dashboard JSON:

* **It already has rows** - the last row becomes the collapsed section: the
  panels that follow it are moved inside the row, the row is set to
  `collapsed: true` and it is renamed to "Details" (its previous title is kept
  in the row's `description`, so nothing is lost).
* **It is flat** - it is split in two: the leading panels become the "Overview"
  row, the rest become the collapsed "Details" row. The split is at the first
  table panel, because a table is what a dashboard reader wants to open on
  demand; a dashboard whose very first panel is a table keeps that panel as the
  overview.

A collapsed row holds its panels inside its own `panels` list (Grafana does
that itself when you collapse a row), and the panel positions are re-laid out
so the row and its panels do not overlap.

Idempotent: a dashboard that already ends with a collapsed "Details" section
is left alone.

Usage:  python3 _apply_details_row.py [dashboard.json ...]
        (default: every *.json next to this script except template.json)
Check:  python3 _check_details_row.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP = {"template.json"}
DETAIL_ROW_TITLE = "Details"
OVERVIEW_ROW_TITLE = "Overview"


def groups(panels):
    """Group panels by their original y, keeping the order they were drawn in."""
    out = []
    for panel in panels:
        y = (panel.get("gridPos") or {}).get("y", 0)
        if out and out[-1][0] == y:
            out[-1][1].append(panel)
        else:
            out.append((y, [panel]))
    return out


def layout(panels, start_y):
    """Re-stack panels in rows, preserving each panel's x and width."""
    y = start_y
    for _, row_panels in groups(panels):
        height = max((p.get("gridPos") or {}).get("h", 6) for p in row_panels)
        for p in row_panels:
            gp = p.setdefault("gridPos", {})
            gp["y"] = y
            gp.setdefault("x", 0)
            gp.setdefault("w", 24)
            gp.setdefault("h", 6)
        y += height
    return y


def next_id(panels, start=100):
    used = {p.get("id") for p in panels if p.get("id") is not None}
    for p in panels:
        for sp in p.get("panels") or []:
            if sp.get("id") is not None:
                used.add(sp.get("id"))
    i = start
    while i in used:
        i += 1
    return i


def make_row(title, collapsed, panels, y, row_id):
    return {"type": "row", "title": title, "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
            "id": row_id, "collapsed": collapsed, "panels": panels}


def rename_to_details(row):
    """Name the section "Details", keeping the old title in the description."""
    title = row.get("title")
    if title == DETAIL_ROW_TITLE:
        return False
    row["title"] = DETAIL_ROW_TITLE
    if title:
        row.setdefault("description", title)
    return True


def apply(dashboard):
    """Return True when the dashboard was changed."""
    panels = dashboard.get("panels", [])
    if not panels:
        return False
    rows = [p for p in panels if p.get("type") == "row"]

    # Case 1: the dashboard already has rows. Collapse the last one.
    if rows:
        last = rows[-1]
        idx = panels.index(last)
        trailing = [p for p in panels[idx + 1:] if p.get("type") != "row"]
        nested = list(last.get("panels") or []) + trailing
        if not nested:
            return False                      # nothing to move: it is already a section
        row_y = (last.get("gridPos") or {}).get("y", 0)
        changed = False
        if trailing:
            # The panels that follow the row belong to it: move them inside.
            last["panels"] = nested
            last["collapsed"] = True
            last["gridPos"] = {"h": 1, "w": 24, "x": 0, "y": row_y}
            layout(nested, row_y + 1)
            dashboard["panels"] = panels[:idx] + [last]
            changed = True
        if rename_to_details(last):
            changed = True
        return changed

    # Case 2: a flat dashboard. Split it into an overview and a details section.
    tables = [i for i, p in enumerate(panels) if p.get("type") == "table"]
    if not tables:
        return False                          # no detail table to put behind a section
    split = tables[0]
    if split == 0:
        split = 1                            # keep the first table as the overview
    overview = panels[:split]
    details = panels[split:]
    if not details:
        return False

    row_id = next_id(panels)
    ov_end = layout(overview, 1)
    ov_row = make_row(OVERVIEW_ROW_TITLE, False, [], 0, row_id)
    det_row = make_row(DETAIL_ROW_TITLE, True, [], ov_end, row_id + 1)
    layout(details, ov_end + 1)
    det_row["panels"] = details

    dashboard["panels"] = [ov_row] + overview + [det_row]
    return True


def transform(dashboard):
    """Apply the house shape; return the dashboard and whether it changed."""
    before = json.dumps(dashboard, sort_keys=True)
    changed = apply(dashboard)
    return dashboard, changed or json.dumps(dashboard, sort_keys=True) != before


def dashboard_files():
    """Every dashboard in the repo: this folder and each feature's grafana/ folder.

    template.json (the Atlas dashboard house style) is not a dashboard and is left out.
    """
    here = Path(__file__).resolve().parent
    root = here.parents[3]
    files = sorted(here.glob("*.json")) + sorted(root.glob("features/*/grafana/*.json"))
    return [f for f in files if not (f.parent == here and f.name == "template.json")]


def main():
    files = sys.argv[1:]
    if not files:
        files = [str(p) for p in dashboard_files()
                 if "panels" in json.loads(p.read_text(encoding="utf-8"))]
    changed = 0
    for path in files:
        p = Path(path)
        original = p.read_text(encoding="utf-8")
        dashboard = json.loads(original)
        dashboard, _ = transform(dashboard)
        # ensure_ascii=False: the dashboards keep their unicode (✓, ✗, emoji) as it is.
        rendered = json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n"
        if rendered != original:
            p.write_text(rendered, encoding="utf-8")
            print("changed", p.name)
            changed += 1
        else:
            print("ok     ", p.name)
    print("changed:", changed)


if __name__ == "__main__":
    main()
