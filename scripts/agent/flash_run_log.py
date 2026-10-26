#!/usr/bin/env python3
"""Per-run record and daily summary of the free-Flash game runs (TASK-164).

Both game players run on MiniMax M3.1 Flash, which is on the owner's unlimited free plan, so a
run must cost $0. This reads the runs of the last N hours and prints one row per run (model,
steps, progress, cost, wall time), and with --write it refreshes the run table and the daily
summary of docs/tasks/TASK-164-flash-play.md.

    # print the table of the last 24 hours
    python3 scripts/agent/flash_run_log.py
    # refresh the doc (idempotent: the table is rewritten, the daily rows are merged)
    python3 scripts/agent/flash_run_log.py --write
    # a wider window
    python3 scripts/agent/flash_run_log.py --hours 72 --write

The runs come from the lab database (script_results + ai_calls). Nothing is written to the
database: this is a reader, and the players write their own records.

Env: FLASH_LOG_DB_CMD (the command the SQL is piped into; the default is the lab psql through
proxmox), FLASH_LOG_TEAM (the team whose runs are counted).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
DOC = os.path.join(REPO, "docs", "tasks", "TASK-164-flash-play.md")
TEAM_ID = os.environ.get("FLASH_LOG_TEAM", "7fdeb4bb-3639-4ec3-959f-b54769a219ce")
DB_CMD = os.environ.get("FLASH_LOG_DB_CMD", [
    "ssh", "proxmox",
    "ssh 192.168.0.102 'PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U supabase_admin "
    "-d postgres -At -v ON_ERROR_STOP=1'",
])

RUNS_MARK = ("<!-- flash-runs:start -->", "<!-- flash-runs:end -->")
DAILY_MARK = ("<!-- flash-daily:start -->", "<!-- flash-daily:end -->")


def log(msg: str) -> None:
    print(f"[flash-run-log] {msg}", file=sys.stderr)


def sql(query: str) -> list[dict]:
    """Run the query on the lab DB and return the JSON rows."""
    cmd = DB_CMD if isinstance(DB_CMD, list) else os.environ.get("FLASH_LOG_DB_CMD", "").split()
    try:
        proc = subprocess.run(cmd, input=query, capture_output=True, text=True, timeout=180)
    except Exception as exc:  # noqa: BLE001 - the reader must not crash the caller
        log(f"cannot reach the database: {exc}")
        return []
    if proc.returncode != 0:
        log(f"psql failed: {proc.stderr.strip()[:300]}")
        return []
    rows = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def fetch_runs(hours: int) -> list[dict]:
    """Every CoC and Pokemon run of the window, with the AI calls it made."""
    query = f"""
select json_build_object(
    'id', r.id,
    'game', case when r.script_name like '%clashofclans%' then 'coc'
                 when r.script_name like '%game_pokemon%' then 'pokemon'
                 else r.script_name end,
    'started', r.started_at,
    'ended', r.completed_at,
    'duration_ms', r.execution_time_ms,
    'host', r.host_name,
    'success', r.success,
    'error', left(coalesce(r.error_msg, ''), 240),
    'meta', r.metadata,
    'calls', coalesce((
        select json_agg(json_build_object(
            'model', c.model, 'usage', c.usage_key, 'n', c.n,
            'ok', c.ok, 'cost', c.cost, 'fallback', c.fallback))
        from (
            select a.model, a.usage_key, count(*) as n,
                   count(*) filter (where a.ok) as ok,
                   coalesce(sum(coalesce(a.cost, 0)), 0) as cost,
                   count(*) filter (where a.fallback_used) as fallback
            from ai_calls a where a.script_result_id = r.id::text
            group by a.model, a.usage_key
        ) c), '[]'::json)
)
from script_results r
where r.team_id = '{TEAM_ID}'
  and r.started_at > now() - interval '{int(hours)} hours'
  and (r.script_name like '%clashofclans%' or r.script_name like '%game_pokemon%')
order by r.started_at desc;
"""
    return sql(query)


def _ts(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def _model(run: dict) -> str:
    """The model the run was served by (the one that made most of the calls)."""
    meta = run.get("meta") or {}
    if isinstance(meta, dict) and meta.get("model"):
        return str(meta["model"])
    calls = [c for c in (run.get("calls") or []) if c.get("n")]
    if not calls:
        return "no AI call"
    calls.sort(key=lambda c: -int(c.get("n") or 0))
    return str(calls[0].get("model") or "?")


def _steps(run: dict) -> str:
    meta = run.get("meta") or {}
    if not isinstance(meta, dict):
        return "-"
    if run.get("game") == "coc":
        return str(meta.get("steps", "-"))
    return f"{meta.get('ticks', '-')} ticks"


def _progress(run: dict) -> str:
    meta = run.get("meta") or {}
    if not isinstance(meta, dict):
        return "-"
    if run.get("game") == "coc":
        stop = meta.get("stop") or "-"
        spent = ((meta.get("budget") or {}).get("run_spent"))
        if isinstance(spent, (int, float)):
            stop = f"{stop}, budget ${spent:.4f}"
        return stop
    start = meta.get("start") or {}
    badges = meta.get("badges", start.get("badges", "-"))
    milestone = start.get("milestone", "-")
    out = f"{milestone}, {badges} badges"
    stall = (meta.get("stall") or {}).get("reason")
    if stall:
        out = f"{out} (stalled: {stall})"
    return out


def _cost(run: dict) -> float:
    """The money the run really cost (ai_calls.cost), not the player's own estimate."""
    return round(sum(float(c.get("cost") or 0) for c in (run.get("calls") or [])), 6)


def _in_flight(run: dict) -> bool:
    """True while the row still carries the platform's placeholder.

    `record_script_execution_start` inserts the row with `completed_at = started_at` (two `now()`
    calls a few microseconds apart) and leaves `execution_time_ms` NULL; `update_script_execution_result`
    writes the real end time and the duration when the script finishes. A row that still looks like
    the placeholder is a run **in flight**, not a failed one — the platform's own dashboard uses the
    same rule (backend_server/src/routes/server_dashboard_routes.py::_is_running_row).

    `completed_at IS NULL` is NOT the test: the column is NOT NULL and holds the placeholder, so a
    run that had just started was counted as a failure.
    """
    started, ended = _ts(run.get("started")), _ts(run.get("ended"))
    if not started:
        return False
    if run.get("duration_ms") is not None:
        return False
    if ended is None:
        return True
    return abs((ended - started).total_seconds()) < 1.0


def _wall(run: dict) -> str:
    started, ended = _ts(run.get("started")), _ts(run.get("ended"))
    if not started:
        return "-"
    if _in_flight(run):
        return "running"
    if not ended:
        return "-"
    seconds = int((ended - started).total_seconds())
    return f"{seconds // 60}m{seconds % 60:02d}s"


def _outcome(run: dict) -> str:
    if _in_flight(run):
        return "running"
    if run.get("success"):
        return "ok"
    error = (run.get("error") or "").strip()
    if error:
        return "failed: " + error.splitlines()[0][:80]
    return "failed"


def row_for(run: dict) -> dict:
    return {
        "id": run.get("id"),
        "game": run.get("game"),
        "started": (_ts(run.get("started")) or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d %H:%M"),
        "host": run.get("host") or "-",
        "model": _model(run),
        "steps": _steps(run),
        "progress": _progress(run),
        "cost_usd": _cost(run),
        "wall": _wall(run),
        "outcome": _outcome(run),
    }


def table(rows: list[dict]) -> str:
    head = ("| started (UTC) | game | host | model | steps | progress | cost USD | wall | outcome |\n"
            "|---|---|---|---|---|---|---|---|---|\n")
    body = ""
    for row in rows:
        body += (f"| {row['started']} | {row['game']} | {row['host']} | {row['model']} | {row['steps']} | "
                 f"{row['progress']} | {row['cost_usd']:.6f} | {row['wall']} | {row['outcome']} |\n")
    return head + body


def daily_rows(runs: list[dict]) -> dict[str, dict]:
    """One line per UTC day: runs, calls, models, money."""
    days: dict[str, dict] = {}
    for run in runs:
        started = _ts(run.get("started"))
        if not started:
            continue
        day = started.strftime("%Y-%m-%d")
        entry = days.setdefault(day, {"runs": 0, "coc": 0, "pokemon": 0, "calls": 0, "cost": 0.0, "models": set()})
        entry["runs"] += 1
        entry[run.get("game") or "other"] = entry.get(run.get("game") or "other", 0) + 1
        for call in run.get("calls") or []:
            entry["calls"] += int(call.get("n") or 0)
            entry["cost"] += float(call.get("cost") or 0)
            if call.get("model"):
                entry["models"].add(str(call["model"]))
    return days


def daily_table(days: dict[str, dict]) -> str:
    head = ("| day (UTC) | runs | CoC | Pokemon | AI calls | models | cost USD |\n"
            "|---|---|---|---|---|---|---|\n")
    body = ""
    for day in sorted(days, reverse=True):
        entry = days[day]
        models = ", ".join(sorted(entry["models"])) or "-"
        body += (f"| {day} | {entry['runs']} | {entry.get('coc', 0)} | {entry.get('pokemon', 0)} | "
                 f"{entry['calls']} | {models} | {entry['cost']:.6f} |\n")
    return head + body


def replace_block(text: str, marks: tuple[str, str], block: str) -> str:
    """Replace the text between the two markers (or append the block at the end)."""
    start, end = marks
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    new = f"{start}\n{block}{end}"
    if pattern.search(text):
        return pattern.sub(lambda _m: new, text)
    return text.rstrip() + "\n\n" + new + "\n"


def write_doc(runs: list[dict], path: str = DOC, daily_hours: int = 168) -> str:
    """Refresh the doc: the per-run table of `runs` (the sliding window) and the daily summary.

    The daily summary is read over a wider window (a week by default) so a **day is a day**: with the
    24 h window the oldest day lost its first runs as the window slid, and the number of a finished
    day changed after it was written."""
    rows = [row_for(run) for run in runs]
    days = daily_rows(fetch_runs(daily_hours))
    if not os.path.exists(path):
        log(f"{path} does not exist yet; nothing written")
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    text = replace_block(text, RUNS_MARK, table(rows))
    text = replace_block(text, DAILY_MARK, daily_table(days))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=int, default=24, help="window in hours (default 24)")
    parser.add_argument("--daily-hours", type=int, default=168,
                        help="window of the daily summary in hours (default 168 = a week, so a day is whole)")
    parser.add_argument("--write", action="store_true", help="refresh the run table and the daily summary in the doc")
    parser.add_argument("--doc", default=DOC, help="the doc to refresh")
    args = parser.parse_args()

    runs = fetch_runs(args.hours)
    rows = [row_for(run) for run in runs]
    if args.write:
        path = write_doc(runs, args.doc, daily_hours=args.daily_hours)
        if path:
            log(f"wrote {path} ({len(rows)} runs)")
    print(table(rows))
    days = daily_rows(fetch_runs(args.daily_hours))
    print()
    print(daily_table(days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
