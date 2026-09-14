#!/usr/bin/env python3
"""Revert the `enriched_results` CTE from the materialized view back to a live
base-table LATERAL gw_info as-of join. Inverse of _migrate_enriched_cte.py.

With the supporting index `script_results(script_name, host_name, started_at DESC)`
the live LATERAL is fast (no MV, no refresh, always fresh). The CTE name is
preserved so downstream panel SELECTs (incl. the empty-IN fix) are untouched.

Usage: python3 _revert_enriched_cte.py --dry-run|--apply <file.json> [...]
"""
import json, re, sys

# Canonical 5-column gw enrichment (superset; dashboards that use only 4 ignore gw_mac).
LATERAL = """SELECT
    sr.*,
    COALESCE(gw.metadata->>'technology', 'Unknown') as gw_technology,
    COALESCE(gw.metadata->>'network_type', 'Unknown') as gw_network_type,
    COALESCE(gw.metadata->>'modem_name', 'Unknown') as gw_model,
    COALESCE(gw.metadata->>'firmware_version', 'Unknown') as gw_firmware,
    COALESCE(NULLIF(gw.metadata->>'cable_mac_address', 'Unknown'), NULLIF(gw.metadata->>'pon_mac_address', 'Unknown'), 'Unknown') as gw_mac
  FROM script_results sr
  LEFT JOIN LATERAL (
    SELECT metadata
    FROM script_results gw
    WHERE gw.script_name = 'gw_info' AND gw.success = true AND gw.host_name = sr.host_name AND gw.started_at <= sr.started_at
    ORDER BY gw.started_at DESC
    LIMIT 1
  ) gw ON true
  WHERE sr.script_name = '{sn}'"""

PAT = re.compile(r"SELECT \* FROM script_results_enriched WHERE script_name = '([^']+)'")

def revert(sql):
    if not sql:
        return sql, 0
    n = [0]
    def repl(m):
        n[0] += 1
        return LATERAL.format(sn=m.group(1))
    return PAT.sub(repl, sql), n[0]

def walk(panels):
    for p in panels:
        if 'panels' in p:
            yield from walk(p['panels'])
        for t in p.get('targets', []):
            if t.get('rawSql'):
                yield t

if __name__ == '__main__':
    apply = sys.argv[1] == '--apply'
    for path in sys.argv[2:]:
        d = json.load(open(path))
        total = 0
        for t in walk(d.get('panels', [])):
            new, c = revert(t['rawSql'])
            if c:
                t['rawSql'] = new
                total += c
        if apply and total:
            with open(path, 'w') as f:
                json.dump(d, f, indent=2); f.write('\n')
        print(f"{'APPLIED' if apply and total else 'would change' if total else 'no-op '} {total:>4}  {path}")
