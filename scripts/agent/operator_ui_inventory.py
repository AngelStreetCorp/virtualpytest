#!/usr/bin/env python3
"""Inventory the operator's navigation trees per platform and language (UI inventory).

Reads the platform through its own REST API (never the database directly):
  GET /server/userinterface/getAllUserInterfaces      -> the interfaces
  GET /server/navigationTrees/getTreeByUserInterfaceId -> nodes + edges of the root tree
  GET /server/userinterface/<id>/variants              -> named variants
  GET /server/userinterface/<id>/publishes             -> promotion to prod
  GET /server/script-results/getAllScriptResults?script_name=validation -> last validation runs

The two backends share one database but scope script results by their own hosts,
so validation rows are read from both (a STB run lands on the rpitest server, a
web run on the main one).

Usage:
  python3 scripts/agent/operator_ui_inventory.py [--team-id ID] [--out file.json] [--only name ...]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

MAIN = "https://virtualpytest.angelstreet.io"
RPITEST = "https://rpitest.angelstreet.io"
DEFAULT_TEAM = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"


def token():
    """The auto-sign test token (a team-admin credential): read it, never print it."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    script = os.path.join(here, "scripts", "agent", "auto_sign_token.sh")
    out = subprocess.run([script], capture_output=True, text=True, check=True).stdout.strip()
    if not out:
        raise SystemExit("auto_sign_token.sh returned nothing")
    return out


class Api:
    def __init__(self, base, tok):
        self.base, self.tok = base, tok

    def get(self, path, **params):
        params = {k: v for k, v in params.items() if v is not None}
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        # a User-Agent is required: the default python-urllib one is refused with 403
        req = urllib.request.Request(url, headers={"X-Auto-Sign": self.tok, "User-Agent": "vpt-agent/1.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            body = r.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except ValueError:
            return {"_raw": body[:400]}


def count_nodes_edges(tree):
    meta = (tree or {}).get("metadata") or {}
    return len(meta.get("nodes") or []), len(meta.get("edges") or [])


# The word "version", and a version value such as 3.11.5.3 (or V3.11.5.3). A localized row
# label is NOT here on purpose: it is the app's own language, and a check that guessed it
# would report a tree as broken because it reads a different word.
VERSION_WORD = re.compile(r"versions?", re.I)
VERSION_VALUE = re.compile(r"\bv?\d+\.\d+(?:\.\d+)+\b")


def _strings(value):
    """Every string in a params blob, at any depth."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def tree_rule(tree):
    """The rule from AGENTS.md: every tree has a `settings` node and an `info` node that
    reads the software version.

    What the platform can decide on its own is the presence of the two nodes, and that is
    what the verdict is about. Whether the `info` node reaches the version *row* is
    app-specific — the row is labelled in the app's own language, and the model tree holds
    the row without ever saying "version" — so the assertions the `info` node waits for are
    reported next to the verdict and the judgement is left to whoever owns the tree.
    """
    meta = (tree or {}).get("metadata") or {}
    nodes = meta.get("nodes") or []
    edges = meta.get("edges") or []
    labels = {(n.get("label") or "").strip().lower() for n in nodes}
    settings, info = "settings" in labels, "info" in labels

    info_node = next((n for n in nodes if (n.get("label") or "").strip().lower() == "info"), None)
    assertions = []
    for v in (info_node or {}).get("verifications") or []:
        params = v.get("params") or {}
        # the text the node waits for, not the name of the reference image it looks at
        waits = next((params[k] for k in ("text", "search_term", "url_pattern", "element_id")
                      if isinstance(params.get(k), str) and params[k].strip()), "")
        if not waits:
            waits = next((s for s in _strings(params) if s.strip()), "")
        assertions.append({"command": v.get("command"), "waits_for": waits})

    held = []
    for n in nodes:
        for v in n.get("verifications") or []:
            held.extend(_strings(v.get("params") or {}))
    for e in edges:
        for aset in e.get("action_sets") or []:
            for a in aset.get("actions") or []:
                held.extend(_strings(a.get("params") or {}))

    versions = []
    for s in held:
        if (VERSION_WORD.search(s) or VERSION_VALUE.search(s)) and s not in versions:
            versions.append(s)

    if not settings and not info:
        verdict = "no settings node"
    elif settings and info:
        verdict = "settings and info"
    elif settings:
        verdict = "missing info node"
    else:
        verdict = "missing settings node"

    return {
        "settings_node": settings,
        "info_node": info,
        "verdict": verdict,
        "info_assertions": assertions,
        "version_strings": versions[:10],
    }


def validation_rows(api, team):
    """Validation runs known to this backend (it only sees rows for its own hosts)."""
    rows = api.get("/server/script-results/getAllScriptResults",
                   team_id=team, script_name="validation", limit=500)
    if isinstance(rows, dict):
        return []
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--team-id", default=DEFAULT_TEAM)
    ap.add_argument("--out", default="/tmp/operator_ui_inventory.json")
    ap.add_argument("--only", nargs="*", default=None, help="only these interface names")
    a = ap.parse_args()

    tok = token()
    main_api = Api(MAIN, tok)
    rpi_api = Api(RPITEST, tok)

    interfaces = main_api.get("/server/userinterface/getAllUserInterfaces",
                              team_id=a.team_id, force_refresh="true")
    if isinstance(interfaces, dict):
        raise SystemExit(f"getAllUserInterfaces failed: {interfaces}")

    # validation runs, from both backends, grouped by interface name
    runs = {}
    for api, label in ((main_api, "main"), (rpi_api, "rpitest")):
        for row in validation_rows(api, a.team_id):
            name = row.get("userinterface_name")
            if not name:
                continue
            runs.setdefault(name, []).append({
                "backend": label,
                "host": row.get("host_name"),
                "device": (row.get("metadata") or {}).get("device_id"),
                "variant": (row.get("metadata") or {}).get("variant"),
                "started_at": row.get("started_at"),
                "completed_at": row.get("completed_at"),
                "success": row.get("success"),
                "report": row.get("html_report_r2_url"),
                "parameters": (row.get("metadata") or {}).get("parameters"),
                "code_version": (row.get("metadata") or {}).get("code_version"),
                "id": row.get("id"),
            })

    out = []
    for i in sorted(interfaces, key=lambda x: x.get("name") or ""):
        name = i.get("name")
        if a.only and name not in a.only:
            continue
        uid = i.get("id")
        tree = main_api.get(f"/server/navigationTrees/getTreeByUserInterfaceId/{uid}",
                            team_id=a.team_id).get("tree")
        nodes, edges = count_nodes_edges(tree)
        rule = tree_rule(tree)
        variants = main_api.get(f"/server/userinterface/{uid}/variants", team_id=a.team_id).get("variants") or []
        publishes = main_api.get(f"/server/userinterface/{uid}/publishes", team_id=a.team_id).get("publishes") or []
        mine = sorted(runs.get(name, []), key=lambda r: r.get("started_at") or "", reverse=True)
        out.append({
            "name": name,
            "id": uid,
            "models": i.get("models"),
            "mode": i.get("mode"),
            "company": i.get("company"),
            "root_tree": (tree or {}).get("id"),
            "nodes": nodes,
            "edges": edges,
            "rule": rule,
            "updated_at": i.get("updated_at"),
            "created_at": i.get("created_at"),
            "published_version": i.get("published_version"),
            "published_at": i.get("published_at"),
            "variants": [{"name": v.get("name"), "created_at": v.get("created_at"),
                          "description": v.get("description")} for v in variants],
            "publishes": publishes,
            "validations": mine,
        })

    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {a.out}: {len(out)} interfaces")
    for e in out:
        last = e["validations"][0] if e["validations"] else None
        rule = e.get("rule") or {}
        mark = "-" if rule.get("verdict") == "no settings node" else rule.get("verdict")
        print(f"{e['name']:<42} {e['nodes']:>3}n/{e['edges']:>3}e  vars={len(e['variants'])} "
              f"pub={e['published_version']}  last_val={last['started_at'] if last else '-'}"
              f"{'' if not last else (' OK' if last['success'] else ' FAIL')}"
              f"  rule={mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
