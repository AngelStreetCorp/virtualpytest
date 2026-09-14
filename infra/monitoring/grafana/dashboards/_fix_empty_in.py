#!/usr/bin/env python3
"""Make multi-value template-variable filters empty-safe.

`<col> IN ($var)` breaks (SQL `IN ()`) when the variable has no options
(e.g. the gw_* variables, because no gw_info row has success=true). Replace the
` IN ($var)` operator with the SQL-equivalent ` = ANY(string_to_array('${var:csv}', ','))`,
which is valid even when the variable expands to empty. The left operand is left
untouched, so complex columns like COALESCE(...) are preserved.

Usage: python3 _fix_empty_in.py --dry-run|--apply <file.json> [...]
"""
import json, re, sys

PAT = re.compile(r"IN \(\$(\w+)\)")
def fix(sql):
    if not sql:
        return sql, 0
    n = [0]
    def repl(m):
        n[0] += 1
        var = m.group(1)
        return f"= ANY(string_to_array('${{{var}:csv}}', ','))"
    return PAT.sub(repl, sql), n  # n filled by closure

def fix_sql(sql):
    if not sql:
        return sql, 0
    cnt = [0]
    def repl(m):
        cnt[0] += 1
        return f"= ANY(string_to_array('${{{m.group(1)}:csv}}', ','))"
    return PAT.sub(repl, sql), cnt[0]

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
            new, n = fix_sql(t['rawSql'])
            if n:
                t['rawSql'] = new
                total += n
        if apply and total:
            with open(path, 'w') as f:
                json.dump(d, f, indent=2); f.write('\n')
        print(f"{'APPLIED' if apply and total else 'would change' if total else 'no-op '} {total:>4}  {path}")
