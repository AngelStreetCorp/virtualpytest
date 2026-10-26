#!/usr/bin/env python3
"""Check every panel SQL of a Grafana dashboard against the datasource.

Run it before pushing a dashboard: the panel SQL uses Grafana variables and
macros, so they are substituted here the way Grafana substitutes them
(`$var` -> 'a','b', `$__timeFilter(col)` -> a time range, `$__timeGroupAlias(col,'1d')`
-> a time column). A panel that does not run shows up as ERROR.

    GRAFANA_URL=https://<host>/grafana GRAFANA_USER=admin GRAFANA_PASS=... \
      python3 _check_panel_sql.py <dashboard.json> [<values.json>]

`values.json` holds the values the dashboard variables are set to while checking
(a stand-in for "every host / device / interface"):

    {"hosts": ["vpt-pi1"], "devices": ["stb4"], "interfaces": ["stb_tv"]}

Without it, no host / device / interface filter is applied.
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

DATASOURCE = {"uid": "supabase-postgres", "type": "grafana-postgresql-datasource"}


def load_env():
    base = (os.environ.get("GRAFANA_URL") or "https://virtualpytest.angelstreet.io/grafana").rstrip("/")
    if base.endswith("/grafana"):
        base = base[: -len("/grafana")]
    user = os.environ.get("GRAFANA_USER", "admin")
    password = os.environ.get("GRAFANA_PASS", "")
    if not password:
        sys.exit("GRAFANA_PASS is required (or set it in the environment)")
    auth = base64.b64encode(("%s:%s" % (user, password)).encode()).decode()
    return base, auth


def subst(sql, values):
    s = sql
    s = s.replace("$__timeGroupAlias(started_at, '1d')",
                  "floor(extract(epoch from started_at)/86400)*86400 AS \"time\"")
    s = s.replace("$__timeFilter(started_at)",
                  "started_at >= now() - interval '30 days' AND started_at <= now()")
    s = s.replace("${allowed_devices:sqlstring}", "'*'")
    s = s.replace("${flag:csv}", "__ALL__")
    s = s.replace("${flag}", "__ALL__")
    s = re.sub(r"\$\{workspace:sqlstring\}", "'none'", s)
    for name, key in (("host", "hosts"), ("device_name", "devices"),
                      ("user_interface", "interfaces")):
        items = values.get(key) or []
        if not items:
            continue
        # Grafana expands a multi-value variable as 'a','b' (no parentheses), and
        # the house SQL already has the parentheses: host_name IN ($host).
        expanded = ",".join("'%s'" % v for v in items)
        s = s.replace("${%s}" % name, expanded)
        s = re.sub(r"\$%s\b" % name, expanded, s)
    return s


def query(base, auth, sql):
    q = {"queries": [{"refId": "A", "datasource": DATASOURCE, "rawSql": sql, "format": "table"}],
         "from": "now-30d", "to": "now"}
    req = urllib.request.Request(
        base + "/api/ds/query", data=json.dumps(q).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Basic " + auth})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        return "HTTP %s: %s" % (e.code, e.read().decode()[:200])
    a = res.get("results", {}).get("A", {})
    if a.get("error"):
        return "ERROR: " + str(a["error"])[:200]
    rows = 0
    for f in a.get("frames", []):
        v = f.get("data", {}).get("values", [])
        rows = len(v[0]) if v else 0
    return "OK (%d rows)" % rows


def panels_of(dashboard):
    """Every panel that carries a query - the ones inside a collapsed row too.

    A collapsed row holds its panels in its own `panels` list, so a dashboard
    whose detail tables live in the "Details" row would otherwise be checked
    with nothing but its overview.
    """
    out = []

    def walk(panels):
        for p in panels or []:
            if p.get("type") == "row":
                walk(p.get("panels"))
            else:
                out.append(p)

    walk(dashboard.get("panels", []))
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    base, auth = load_env()
    values = {}
    if len(sys.argv) > 2:
        values = json.load(open(sys.argv[2]))
    dash = json.load(open(sys.argv[1]))
    bad = 0
    for p in panels_of(dash):
        for t in p.get("targets", []):
            sql = t.get("rawSql")
            if not sql:
                continue
            res = query(base, auth, subst(sql, values))
            if not res.startswith("OK"):
                bad += 1
                s = subst(sql, values)
                spots = ["..." + s[max(0, i - 50):i + 50] + "..." for i, ch in enumerate(s) if ch == "$"]
                res += "\n      DOLLARS: " + (" | ".join(spots) if spots else "none")
            print("%-26s %s" % (p.get("title"), res))
    print("FAILED PANELS:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
