#!/usr/bin/env python3
"""TASK-159 G7: report and soft-merge the duplicate rows of screen_fingerprints.

Rows of one scope (device) whose fingerprints match within ``screen_memory.match_screen`` tolerance are one screen,
whatever their ``incident_type`` (freeze, localize_abstain, screen). The row kept per group: a person's label, else a
real (AI) name, else an ``unknown_N`` / unlabelled row; ties go to the most sightings, then the oldest.

Nothing is deleted. The duplicate gets ``merged_into = <kept id>``, the kept row gets the summed ``seen_count`` and, when
it has none, a duplicate's data-URI thumbnail. Readers skip merged rows (``merged_into IS NULL``).

  --rows rows.json   rows as exported by the SELECT in --print-select (read-only)
  --report           print the groups (counts, kept row, per scope); default
  --sql out.sql      write the exact UPDATE statements (one transaction) for the soft merge
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from typing import Any, Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from shared.src.lib import screen_memory  # noqa: E402

UNNAMED = re.compile(r'^unknown_[0-9]+$')
SELECT = ("select coalesce(json_agg(r),'[]') from (select id,team_id,scope,incident_type,dhash,region_center,label,"
          "verdict,source,seen_count,first_seen,last_seen,(left(coalesce(sample_image_path,''),11)='data:image/') "
          "as has_thumb from screen_fingerprints where merged_into is null and dhash is not null "
          "and region_center is not null) r;")


def keep_rank(row: Dict[str, Any]):
    """Sort key, best first: human label > any real name > unnamed; then more sightings; then older."""
    label = row.get('label') or ''
    named = 0 if (not label or UNNAMED.match(label)) else 1
    human = 1 if (named and row.get('source') == 'human') else 0
    return (-human, -named, -int(row.get('seen_count') or 0), str(row.get('first_seen') or ''))


def is_decided(row: Dict[str, Any]) -> bool:
    """A real name (not unknown_N) or a person's verdict: a second such row in one group is a conflict, not a duplicate."""
    label = row.get('label') or ''
    return bool(label and not UNNAMED.match(label)) or row.get('source') == 'human'


def plan_merges(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Groups of 2+ rows that are one screen: ``[{'team_id', 'scope', 'keep': row, 'dups': [rows]}]``."""
    by_scope: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_scope[(r['team_id'], r['scope'])].append(r)
    groups = []
    conflicts: List[Dict[str, Any]] = []
    for (team_id, scope), items in sorted(by_scope.items()):
        items = sorted(items, key=keep_rank)
        taken = set()
        for anchor in items:
            if anchor['id'] in taken:
                continue
            taken.add(anchor['id'])
            dups = []
            for other in items:
                if other['id'] in taken:
                    continue
                if screen_memory.match_screen({'dhash': other['dhash'], 'region_center': other['region_center']}, [anchor]):
                    dups.append(other)
                    taken.add(other['id'])
            if dups and sum(1 for r in [anchor] + dups if is_decided(r)) > 1:
                # two named / human-judged rows of one picture: a person decides, nothing is merged
                conflicts.append({'team_id': team_id, 'scope': scope, 'rows': [anchor] + dups})
                continue
            if dups:
                groups.append({'team_id': team_id, 'scope': scope, 'keep': anchor, 'dups': dups})
    plan_merges.conflicts = conflicts
    return groups


def render_report(groups: List[Dict[str, Any]], total_rows: int) -> str:
    lines = [f'rows scanned: {total_rows}; duplicate groups: {len(groups)}; '
             f'rows to soft-merge: {sum(len(g["dups"]) for g in groups)}']
    per_scope: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    for g in groups:
        per_scope[g['scope']][0] += 1
        per_scope[g['scope']][1] += len(g['dups'])
    for c in getattr(plan_merges, 'conflicts', []):
        lines.append('SKIPPED (several named / human rows): ' + c['scope'] + ' -> ' + ', '.join(str(r.get('label') or '-') for r in c['rows']))
    lines.append('')
    lines.append('scope | groups | duplicate rows')
    for scope, (n, d) in sorted(per_scope.items()):
        lines.append(f'{scope} | {n} | {d}')
    lines.append('')
    lines.append('scope | kept (label, type, seen) | merged rows (label, type, seen)')
    for g in groups:
        k = g['keep']
        dup = '; '.join(f'{d.get("label") or "-"}, {d["incident_type"]}, {d["seen_count"]}' for d in g['dups'])
        lines.append(f'{g["scope"]} | {k.get("label") or "-"}, {k["incident_type"]}, {k["seen_count"]} | {dup}')
    return '\n'.join(lines)


def render_sql(groups: List[Dict[str, Any]]) -> str:
    out = ['BEGIN;']
    for g in groups:
        k = g['keep']
        total = int(k.get('seen_count') or 0) + sum(int(d.get('seen_count') or 0) for d in g['dups'])
        ids = ','.join(f"'{d['id']}'" for d in g['dups'])
        out.append(f"UPDATE screen_fingerprints SET seen_count = {total}, updated_at = now() "
                   f"WHERE id = '{k['id']}' AND team_id = '{g['team_id']}';")
        if not k.get('has_thumb'):
            out.append(f"UPDATE screen_fingerprints SET sample_image_path = (SELECT sample_image_path FROM "
                       f"screen_fingerprints WHERE id IN ({ids}) AND left(sample_image_path, 11) = 'data:image/' LIMIT 1) "
                       f"WHERE id = '{k['id']}' AND team_id = '{g['team_id']}' AND EXISTS (SELECT 1 FROM "
                       f"screen_fingerprints WHERE id IN ({ids}) AND left(sample_image_path, 11) = 'data:image/');")
        out.append(f"UPDATE screen_fingerprints SET merged_into = '{k['id']}', updated_at = now() "
                   f"WHERE id IN ({ids}) AND team_id = '{g['team_id']}' AND merged_into IS NULL;")
    out.append('COMMIT;')
    return '\n'.join(out) + '\n'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rows', help='JSON file with the rows (see --print-select)')
    ap.add_argument('--print-select', action='store_true', help='print the read-only SELECT that exports the rows')
    ap.add_argument('--sql', help='write the soft-merge UPDATE statements to this file')
    args = ap.parse_args(argv)
    if args.print_select:
        print(SELECT)
        return 0
    if not args.rows:
        ap.error('--rows is required')
    with open(args.rows, encoding='utf-8') as fh:
        rows = json.load(fh)
    groups = plan_merges(rows)
    print(render_report(groups, len(rows)))
    if args.sql:
        with open(args.sql, 'w', encoding='utf-8') as fh:
            fh.write(render_sql(groups))
        print(f'\nwrote {args.sql}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
