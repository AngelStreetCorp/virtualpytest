#!/usr/bin/env python3
"""Repoint the `enriched_results` CTE in SRI dashboards from the expensive
per-panel `LEFT JOIN LATERAL` to the precomputed `script_results_enriched`
materialized view.

The CTE name is preserved, so every downstream panel SELECT is untouched — only
the CTE body changes. Idempotent: skips bodies already pointing at the MV.

Usage:
  python3 _migrate_enriched_cte.py --dry-run <file.json> [...]
  python3 _migrate_enriched_cte.py --apply   <file.json> [...]
"""
import json, re, sys

def find_cte_bodies(sql):
    """Yield (start, end, body) for each `enriched_results AS ( ... )` via balanced parens."""
    out = []
    for m in re.finditer(r'enriched_results\s+AS\s*\(', sql, re.I):
        i = m.end(); depth = 1; start = i
        while i < len(sql) and depth > 0:
            if sql[i] == '(': depth += 1
            elif sql[i] == ')': depth -= 1
            i += 1
        out.append((start, i - 1, sql[start:i - 1]))
    return out

def transform_sql(sql):
    bodies = find_cte_bodies(sql)
    if not bodies:
        return sql, 0
    changed = 0
    # rebuild right-to-left so indices stay valid
    for start, end, body in reversed(bodies):
        if 'script_results_enriched' in body:
            continue  # already migrated
        sn = re.findall(r"sr\.script_name\s*=\s*'([^']+)'", body)
        if not sn:
            raise ValueError(f"no sr.script_name in CTE body: {body[:120]!r}")
        new_body = f"\n  SELECT * FROM script_results_enriched WHERE script_name = '{sn[0]}'\n"
        sql = sql[:start] + new_body + sql[end:]
        changed += 1
    return sql, changed

def walk_targets(panels):
    for p in panels:
        if 'panels' in p:
            yield from walk_targets(p['panels'])
        for t in p.get('targets', []):
            if t.get('rawSql'):
                yield t

def process(path, apply):
    d = json.load(open(path))
    total = 0
    for t in walk_targets(d.get('panels', [])):
        new_sql, n = transform_sql(t['rawSql'])
        if n:
            t['rawSql'] = new_sql
            total += n
    if apply and total:
        with open(path, 'w') as f:
            json.dump(d, f, indent=2)
            f.write('\n')
    return total

if __name__ == '__main__':
    mode = sys.argv[1]
    apply = (mode == '--apply')
    for path in sys.argv[2:]:
        try:
            n = process(path, apply)
            print(f"{'APPLIED' if apply and n else 'would change' if n else 'no-op '} {n:>3}  {path}")
        except Exception as e:
            print(f"ERROR  {path}: {e}")
