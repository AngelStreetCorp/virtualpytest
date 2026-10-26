#!/usr/bin/env python3
"""screen_label_coverage.py — how much of the recurring screen registry is named? (TASK-162)

READ-ONLY. This script never writes: it only selects from ``screen_fingerprints`` and
prints the numbers the owner's goal is measured on:

    every screen seen more than 10 times that is NOT live must be labelled and have
    a fingerprint.

SCOPE OF THE POPULATION
    A row is in the population when
      * ``merged_into IS NULL``  — a soft-merged duplicate is not a screen of its own (TASK-159 G7)
      * ``seen_count > --min-seen`` (default 10, so the owner's "more than 10 times")

WHY EVERY ROW HERE IS "NOT LIVE"
    ``screen_fingerprints`` is written only by ``register_screen``, which the monitor calls
    after a frame passed the Localize gates: full-frame motion reads ``live`` and skips
    (monitor_localize.GATE_LIVE), so a genuinely moving picture never becomes a row. A
    ``freeze`` row is by definition a frozen frame.
    THE ONE EXCEPTION: with the opt-in ``DEVICE<N>_LOCALIZE_SETTLED=1`` flag, a gated
    frame is forced to the matcher when its dHash stays within 24 bits for 3 s
    (monitor_localize.settled_decision), and that gate can be ``live`` — so a very slow
    live scene can register. TASK-159 §12 records this as a known limit.
    Consequence: this report cannot prove a row is not live from the row alone. The
    screen_label_worker re-asks every row that closed question ("moving video or settled
    screen?") before it names anything, and a row that answers LIVE is left unnamed and
    reported as live. ``--min-seen`` only bounds the report; it is not the live filter.

THE FOUR BUCKETS (mutually exclusive, most specific first)
    named_fingerprinted  real name AND a full v6 fingerprint stored (dhash + regions/crop/…)
    named_no_fingerprint real name but no fingerprint blob — pre-v6 rows (the freeze path
                         stored only ``dhash``); they are named but not fingerprinted
    unknown_n            the registry's own placeholder ``unknown_<N>``: registered, not yet named
    unlabelled           label IS NULL: no name at all

THE METRIC (one line, this is what must reach 0)
    screens >10 seen, not live, missing a label or a fingerprint: <named_no_fingerprint + unknown_n + unlabelled>

The owner's goal is a screen that is **labelled AND fingerprinted** — a name on its own does not
finish a screen, and neither does a fingerprint on a row nobody can name. So the metric counts every
row that lacks EITHER one: a real name with no fingerprint (a pre-v6 row, or one the monitor
registered before the fingerprint existed), a row still holding the registry's ``unknown_N``
placeholder, and a row with no name at all. ``named_fingerprinted`` is the only bucket that is done.

``unknown_n + unlabelled`` is the honest "must reach 0": a row the AI could not name with confidence
stays ``unknown_N`` on purpose and is listed for a human, so the metric also counts those. The
``--metric`` flag prints that line alone, for a cron/alert to grep.

    python3 scripts/screen_label_coverage.py                 # full report
    python3 scripts/screen_label_coverage.py --metric        # the one line only
    python3 scripts/screen_label_coverage.py --json          # machine-readable
    python3 scripts/screen_label_coverage.py --sql           # the SQL, for psql
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

_REPO = os.environ.get('VIRTUALPYTEST_REPO') or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from dotenv import load_dotenv  # noqa: E402

# A row is still unnamed while its label is NULL or the registry's placeholder.
# Same expression the namer and the picker use (auto_classify_unknowns.UNNAMED_RE,
# name_screen_row's WHERE) — one definition, three callers.
UNNAMED_RE = r'^unknown_[0-9]+$'
_UNNAMED = re.compile(UNNAMED_RE)

# THE OWNER'S NUMBER. Kept as a named constant, not an argparse default, so a test can pin it and so a
# later change to the WORKER's floor (screen_label_worker.MIN_SEEN, deliberately lower) cannot silently
# move the metric the owner asked to reach 0. See TASK-162 s6.
MIN_SEEN = 10

SELECT = ('id, scope, label, dhash, region_center, fingerprint, userinterface, '
          'incident_type, verdict, source, verdict_by, seen_count, '
          'classification_attempts, first_seen, last_seen, sample_image_path')

COLUMNS = ['scope', 'seen', 'named+fp', 'named-no-fp', 'unknown_N', 'unlabelled', 'no-sample']


def load_dotenv_project() -> None:
    """Load the project .env (SUPABASE_*); the unit itself sets only REPO/PYTHONPATH."""
    load_dotenv(os.path.join(_REPO, '.env'), override=False, encoding='utf-8-sig')


def team_id_arg() -> str:
    from shared.src.lib.config.constants import get_team_id
    return os.environ.get('VIRTUALPYTEST_TEAM_ID') or get_team_id()


def has_fingerprint(row: dict) -> bool:
    """True when the row carries a real fingerprint blob, not just the identity ``dhash``.

    ``fingerprint`` is the v6 JSON (dhash, regions, crop, focus, title, text) written by
    ``register_screen``. A pre-v6 freeze row has it NULL and keeps only ``dhash`` /
    ``region_center``: that screen is identified, but a later match cannot use its regions.
    """
    fp = row.get('fingerprint')
    if isinstance(fp, dict) and fp.get('dhash'):
        return True
    if isinstance(fp, str) and fp.strip() and fp.strip() not in ('{}', 'null'):
        return True
    return False


def bucket(row: dict) -> str:
    label = row.get('label')
    if label and not _UNNAMED.match(str(label)):
        return 'named_fingerprinted' if has_fingerprint(row) else 'named_no_fingerprint'
    if label:
        return 'unknown_n'
    return 'unlabelled'


def fetch(db, team_id: str) -> list:
    """Every live (not soft-merged) row of the team. Read-only."""
    res = (db.table('screen_fingerprints')
           .select(SELECT, count='exact')
           .eq('team_id', team_id)
           .is_('merged_into', 'null')
           .order('seen_count', desc=True)
           .execute())
    return res.data or []


def tally(rows: list) -> dict:
    out = {'named_fingerprinted': 0, 'named_no_fingerprint': 0, 'unknown_n': 0, 'unlabelled': 0}
    for r in rows:
        out[bucket(r)] += 1
    return out


def metric_of(totals: dict) -> int:
    """The owner's number: the screens that are NOT both labelled and fingerprinted.

    A screen is done when it carries a real name AND a real fingerprint.  Every other row is
    unfinished, so the metric counts: a name with no fingerprint, a row still holding the
    registry's ``unknown_N`` placeholder, and a row with no name at all.

    Kept as ONE function so the printed line, the --metric line and the --json key cannot drift
    apart from each other.
    """
    return (totals.get('named_no_fingerprint', 0)
            + totals.get('unknown_n', 0)
            + totals.get('unlabelled', 0))


def by_scope(rows: list) -> dict:
    scopes: dict = {}
    for r in rows:
        s = r.get('scope') or '(none)'
        if s not in scopes:
            scopes[s] = []
        scopes[s].append(r)
    return scopes


def stale_days(row: dict, now) -> float:
    """Days since the row was last seen (0.0 when never, e.g. a NULL last_seen)."""
    from datetime import datetime, timezone
    raw = row.get('last_seen')
    if not raw:
        return 0.0
    try:
        seen = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        return 0.0
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return max(0.0, (now - seen).total_seconds() / 86400.0)


def sql_for(team_id: str, min_seen: int) -> str:
    """The same numbers as SQL, for psql / a human read. Read-only (SELECT only)."""
    return f"""
-- TASK-162 screen label coverage, team {team_id}, seen_count > {min_seen}, merged_into IS NULL.
-- 'live' is not a column: every row here passed the Localize gates as a settled/frozen
-- frame (a moving picture reads GATE_LIVE and skips registration). The opt-in
-- DEVICE<N>_LOCALIZE_SETTLED=1 can admit a very slow live scene (TASK-159 §12), so the
-- worker re-asks liveness per row before naming it.
SELECT scope,
       count(*)                                                          AS screens,
       count(*) FILTER (WHERE label IS NOT NULL
                          AND label !~ '{UNNAMED_RE}')                    AS named,
       count(*) FILTER (WHERE label IS NOT NULL
                          AND label !~ '{UNNAMED_RE}'
                          AND fingerprint IS NOT NULL
                          AND fingerprint->>'dhash' IS NOT NULL)         AS named_fingerprinted,
       count(*) FILTER (WHERE label ~ '{UNNAMED_RE}')                     AS unknown_n,
       count(*) FILTER (WHERE label IS NULL)                              AS unlabelled,
       count(*) FILTER (WHERE fingerprint IS NULL
                          OR fingerprint->>'dhash' IS NULL)               AS no_fingerprint,
       count(*) FILTER (WHERE sample_image_path IS NULL)                  AS no_sample,
       max(seen_count)                                                    AS max_seen
FROM screen_fingerprints
WHERE team_id = '{team_id}'::uuid AND merged_into IS NULL AND seen_count > {min_seen}
GROUP BY scope ORDER BY count(*) FILTER (WHERE label IS NULL OR label ~ '{UNNAMED_RE}') DESC, scope;

-- The metric, one row.  A screen is done when it is labelled AND fingerprinted; every other row
-- (no name, only the unknown_N placeholder, or a name with no fingerprint) is unfinished.
SELECT count(*) FILTER (WHERE label IS NULL
                          OR label ~ '{UNNAMED_RE}'
                          OR fingerprint IS NULL
                          OR fingerprint->>'dhash' IS NULL)             AS missing_label_or_fingerprint,
       count(*) FILTER (WHERE label IS NULL OR label ~ '{UNNAMED_RE}')  AS still_unlabelled,
       count(*) FILTER (WHERE fingerprint IS NULL
                          OR fingerprint->>'dhash' IS NULL)               AS no_fingerprint,
       count(*)                                                          AS total,
       count(*) FILTER (WHERE label IS NOT NULL
                          AND label !~ '{UNNAMED_RE}')                    AS named
FROM screen_fingerprints
WHERE team_id = '{team_id}'::uuid AND merged_into IS NULL AND seen_count > {min_seen};
"""


def render(scopes: dict, min_seen: int, total_rows: int, totals: dict, rows: list, active_days: int) -> None:
    metric = metric_of(totals)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    fresh = sum(1 for r in rows if stale_days(r, now) <= active_days)
    print(f'\nSCREEN LABEL COVERAGE  (seen_count > {min_seen}, not live, not soft-merged)')
    print(f'  live registry rows: {total_rows}   in scope: {sum(totals.values())}')
    for key, label in (('named_fingerprinted', 'labelled + fingerprinted'),
                       ('named_no_fingerprint', 'labelled, no fingerprint'),
                       ('unknown_n', "unknown_N still unnamed"),
                       ('unlabelled', 'no label at all')):
        share = (100.0 * totals[key] / sum(totals.values())) if sum(totals.values()) else 0.0
        print(f'  {label:.<28} {totals[key]:>4}   ({share:.1f} %)')
    print(f'\n  {"scope":<26}{"seen":>6}{"named+fp":>9}{"no-fp":>7}{"unkN":>6}{"nolabel":>8}{"no-samp":>8}{"fresh":>7}')
    for scope in sorted(scopes, key=lambda s: (len(scopes[s]), s), reverse=True):
        rows_s = scopes[scope]
        t = tally(rows_s)
        named = t['named_fingerprinted'] + t['named_no_fingerprint']
        no_sample = sum(1 for r in rows_s if not (r.get('sample_image_path') or '').strip())
        seen = sum(int(r.get('seen_count') or 0) for r in rows_s)
        fresh_s = sum(1 for r in rows_s if stale_days(r, now) <= active_days)
        print(f'  {scope:<26}{seen:>6}{t["named_fingerprinted"]:>9}'
              f'{t["named_no_fingerprint"]:>7}{t["unknown_n"]:>6}{t["unlabelled"]:>8}'
              f'{no_sample:>8}{fresh_s:>7}')
    print(f'\n  of the {sum(totals.values())} in scope, {fresh} were still being seen in the last {active_days} days')
    print(f'  ("fresh" counts every bucket, not only the unnamed: a screen nobody has looked at for a'
          f' week is history, not a recurring screen)')
    print(f'\nMETRIC  screens >{min_seen} seen, not live, missing a label or a fingerprint: {metric}')


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--team-id', default=None)
    p.add_argument('--min-seen', type=int, default=MIN_SEEN,
                   help=f'only screens seen MORE than this often (default {MIN_SEEN}, the owner\'s metric)')
    p.add_argument('--active-days', type=int, default=7,
                   help='how recently a screen must have been last seen to count as recurring '
                        '(report only; the metric always uses the full population)')
    p.add_argument('--metric', action='store_true',
                   help='print only the one-line metric')
    p.add_argument('--json', action='store_true', help='machine-readable')
    p.add_argument('--sql', action='store_true',
                   help='print the equivalent read-only SQL and exit')
    args = p.parse_args(argv)

    load_dotenv_project()
    team_id = args.team_id or team_id_arg()
    if not team_id:
        print('[coverage] team id is required (--team-id or VIRTUALPYTEST_TEAM_ID)', file=sys.stderr)
        return 2
    if args.sql:
        print(sql_for(team_id, args.min_seen))
        return 0

    from shared.src.lib.utils.supabase_utils import get_supabase_client
    db = get_supabase_client()
    if db is None:
        print('[coverage] no Supabase client — cannot read the registry', file=sys.stderr)
        return 2

    rows = fetch(db, team_id)
    in_scope = [r for r in rows if int(r.get('seen_count') or 0) > args.min_seen]
    totals = tally(in_scope)
    metric = metric_of(totals)

    if args.metric:
        print(f'screens >{args.min_seen} seen, not live, missing a label or a fingerprint: {metric}')
        return 0
    if args.json:
        scopes = by_scope(in_scope)
        print(json.dumps({
            'team_id': team_id,
            'min_seen_exclusive': args.min_seen,
            'live_rows': len(rows),
            'in_scope': sum(totals.values()),
            'totals': totals,
            'missing_label_or_fingerprint': metric,
            'still_unlabelled': totals['unknown_n'] + totals['unlabelled'],
            'active_days': args.active_days,
            'still_seen_recently': sum(1 for r in in_scope
                                       if stale_days(r, __import__('datetime').datetime.now(
                                           __import__('datetime').timezone.utc)) <= args.active_days),
            'named_share_pct': round(100.0 * (totals['named_fingerprinted']
                                              + totals['named_no_fingerprint'])
                                     / sum(totals.values()), 1) if sum(totals.values()) else 0.0,
            'scopes': {s: {'screens': len(v), **tally(v),
                           'seen': sum(int(r.get('seen_count') or 0) for r in v),
                           'no_sample': sum(1 for r in v
                                            if not (r.get('sample_image_path') or '').strip())}
                       for s, v in scopes.items()},
        }, indent=2, sort_keys=True))
        return 0

    render(by_scope(in_scope), args.min_seen, len(rows), totals, in_scope, args.active_days)
    return 0


if __name__ == '__main__':
    sys.exit(main())