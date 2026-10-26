#!/usr/bin/env python3
"""24 h wasted-AI-call report (TASK-93): provider x feature x reason, wasted share of served calls.

A call is wasted when a request went out (outcome 'served') and brought nothing usable: failed, answered
nothing, unparseable, or cut off. Calls stopped before a request (skipped / avoided) are listed apart.

    python3 scripts/ai_wasted_report.py --dsn postgresql://user:pass@host:port/db [--hours 24]
    ssh proxmox "ssh 192.168.0.102 'PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U supabase_admin -d postgres'" \
        < <(python3 scripts/ai_wasted_report.py --sql)

``--dsn`` defaults to $AI_REPORT_DSN. ``--sql`` prints the queries only (for psql).
"""
import argparse
import os
import sys

WHY = ("coalesce(error_type, CASE WHEN parse_ok IS FALSE THEN 'parse' "
       "WHEN stop_reason = 'max_tokens' THEN 'cut_off' END)")
WASTED = "(NOT ok OR parse_ok IS FALSE OR stop_reason = 'max_tokens')"


def queries(hours: int) -> list[tuple[str, str]]:
    since = f"ts > now() - interval '{int(hours)} hours'"
    return [
        ("Wasted calls by provider x feature x reason", f"""
SELECT endpoint AS provider, usage_key AS feature, {WHY} AS reason, count(*) AS calls, max(ts) AS last
FROM ai_calls WHERE {since} AND outcome = 'served' AND {WASTED}
GROUP BY 1, 2, 3 ORDER BY 4 DESC;"""),
        ("Totals", f"""
SELECT count(*) FILTER (WHERE outcome = 'served') AS served,
       count(*) FILTER (WHERE outcome = 'served' AND {WASTED}) AS wasted,
       round(100.0 * count(*) FILTER (WHERE outcome = 'served' AND {WASTED})
             / nullif(count(*) FILTER (WHERE outcome = 'served'), 0), 2) AS wasted_pct,
       count(*) FILTER (WHERE outcome = 'skipped') AS stopped_before_request,
       count(*) FILTER (WHERE outcome = 'avoided') AS avoided,
       count(*) FILTER (WHERE outcome = 'served' AND error_type = 'other') AS other_errors
FROM ai_calls WHERE {since};"""),
        ("Stopped before a request (skipped)", f"""
SELECT endpoint AS provider, usage_key AS feature, coalesce(error_type, '-') AS reason, count(*) AS calls
FROM ai_calls WHERE {since} AND outcome = 'skipped' GROUP BY 1, 2, 3 ORDER BY 4 DESC;"""),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--dsn", default=os.environ.get("AI_REPORT_DSN"))
    parser.add_argument("--sql", action="store_true", help="print the SQL only")
    args = parser.parse_args()
    if args.sql:
        print("\n".join(sql for _, sql in queries(args.hours)))
        return 0
    if not args.dsn:
        parser.error("give --dsn or set AI_REPORT_DSN (or use --sql with psql)")
    import psycopg2
    with psycopg2.connect(args.dsn) as conn, conn.cursor() as cur:
        for title, sql in queries(args.hours):
            cur.execute(sql)
            columns = [c.name for c in cur.description]
            rows = [[str(v) for v in row] for row in cur.fetchall()]
            widths = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c) for i, c in enumerate(columns)]
            print(f"\n== {title} ({args.hours} h)")
            print("  ".join(c.ljust(w) for c, w in zip(columns, widths)))
            for row in rows:
                print("  ".join(v.ljust(w) for v, w in zip(row, widths)))
            if not rows:
                print("(none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
