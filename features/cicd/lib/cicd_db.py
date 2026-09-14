"""
CI/CD feature — reads/writes of the `cicd` schema.

No second connection string: everything goes through the server's existing Supabase
client with `.schema('cicd')` (supabase 2.18.1; the schema is exposed to PostgREST by
db/001_cicd_schema.sql, and service_role holds ALL on its tables).

Every helper degrades instead of raising: when the client is missing or the schema is
not exposed, reads return empty and `schema_error()` explains why, so the pages can
show a single "CI/CD not configured" line instead of failing.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from shared.src.lib.utils.supabase_utils import get_supabase_client

SCHEMA = 'cicd'

#: suite name -> the layer values in ci_jobs it covers. 'all' means "don't filter".
SUITE_LAYERS = {'white': ['white'], 'grey': ['grey'], 'all': ['white', 'grey']}


def _table(name: str):
    """PostgREST query builder bound to the cicd schema, or None when unavailable."""
    client = get_supabase_client()
    if client is None:
        return None
    return client.schema(SCHEMA).table(name)


def schema_error() -> Optional[str]:
    """None when the cicd schema answers; otherwise a one-line reason for the UI."""
    try:
        table = _table('ci_projects')
        if table is None:
            return 'no database client on the server (SUPABASE_URL / service key missing)'
        table.select('project').limit(1).execute()
        return None
    except Exception as e:  # schema not exposed, grants missing, database down
        return str(e)


# ─── projects ────────────────────────────────────────────────────────────────

def list_projects(include_disabled: bool = True) -> List[Dict[str, Any]]:
    table = _table('ci_projects')
    if table is None:
        return []
    query = table.select('*').order('project')
    if not include_disabled:
        query = query.eq('enabled', True)
    return query.execute().data or []


def get_project(project: str) -> Optional[Dict[str, Any]]:
    table = _table('ci_projects')
    if table is None:
        return None
    rows = table.select('*').eq('project', project).limit(1).execute().data or []
    return rows[0] if rows else None


def upsert_project(project: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Create or patch one registry row. Only known columns are written."""
    table = _table('ci_projects')
    if table is None:
        raise RuntimeError('no database client')
    allowed = {
        'repo', 'workflow_file', 'default_branch', 'report_prefix',
        'suites', 'runner_labels', 'cloud_suites', 'enabled',
    }
    payload = {k: v for k, v in fields.items() if k in allowed}
    payload['project'] = project
    # An ISO string, not the literal 'now()': PostgREST sends the value as data, it does
    # not evaluate SQL functions in a payload.
    payload['updated_at'] = datetime.now(timezone.utc).isoformat()
    rows = table.upsert(payload, on_conflict='project').execute().data or []
    return rows[0] if rows else payload


# ─── runs / jobs ─────────────────────────────────────────────────────────────

def list_runs(
    project: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    branch: Optional[str] = None,
    suite: Optional[str] = None,
    limit: int = 50,
    changed_since: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Rows of ci_run_summary, newest first.

    `changed_since` (ISO timestamp) keeps only runs that started, or had a job finish, at or
    after that instant — the incremental-refresh cursor of the CI/CD Reports page. It is a
    filter on the view's own `started_at` / `finished_at`, so the cursor is a server clock
    value the client got from a previous answer, never the browser's clock. `finished_at`
    moves on every job upsert (the workflows' `ON CONFLICT … finished_at = now()`, and
    upsert_job() below), so a re-run job surfaces too, not only brand-new runs.
    """
    table = _table('ci_run_summary')
    if table is None:
        return []
    query = table.select('*')
    if changed_since:
        query = query.or_(f'started_at.gte.{changed_since},finished_at.gte.{changed_since}')
    if project:
        query = query.eq('project', project)
    if branch:
        query = query.eq('branch', branch)
    if suite:
        query = query.eq('suite', suite)
    if since:
        query = query.gte('started_at', since)
    if until:
        query = query.lte('started_at', until)
    return query.order('started_at', desc=True).limit(limit).execute().data or []


def list_jobs(project: Optional[str] = None, runs: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Job rows, optionally restricted to one project and a set of run ids."""
    table = _table('ci_jobs')
    if table is None:
        return []
    query = table.select('*')
    if project:
        query = query.eq('project', project)
    if runs:
        query = query.in_('run', runs)
    return query.order('finished_at', desc=True).execute().data or []


def get_run(project: str, run: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """One run plus its jobs."""
    summary = _table('ci_run_summary')
    if summary is None:
        return None, []
    rows = summary.select('*').eq('project', project).eq('run', run).limit(1).execute().data or []
    return (rows[0] if rows else None), list_jobs(project, [run])


def upsert_run(row: Dict[str, Any]) -> None:
    table = _table('ci_runs')
    if table is None:
        raise RuntimeError('no database client')
    table.upsert(row, on_conflict='project,run').execute()


def upsert_job(row: Dict[str, Any]) -> None:
    table = _table('ci_jobs')
    if table is None:
        raise RuntimeError('no database client')
    # The column DEFAULT only fires on insert. A re-run job that arrives through /ingest
    # without a timestamp would otherwise keep its first finished_at and stay invisible
    # to list_runs(changed_since=…). Mirrors the self-hosted psql path's `finished_at = now()`.
    row = {**row, 'finished_at': row.get('finished_at') or datetime.now(timezone.utc).isoformat()}
    table.upsert(row, on_conflict='project,run,job').execute()


# ─── dispatches ──────────────────────────────────────────────────────────────

def record_dispatch(
    project: str, branch: str, suite: str, runner_target: str, requested_by: Optional[str],
) -> Optional[int]:
    table = _table('ci_dispatches')
    if table is None:
        return None
    rows = table.insert({
        'project': project,
        'branch': branch,
        'suite': suite,
        'runner_target': runner_target,
        'requested_by': requested_by,
    }).execute().data or []
    return rows[0].get('id') if rows else None


def update_dispatch(dispatch_id: int, **fields: Any) -> None:
    table = _table('ci_dispatches')
    if table is None or not fields:
        return
    table.update(fields).eq('id', dispatch_id).execute()


def list_dispatches(project: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    table = _table('ci_dispatches')
    if table is None:
        return []
    query = table.select('*')
    if project:
        query = query.eq('project', project)
    return query.order('requested_at', desc=True).limit(limit).execute().data or []
