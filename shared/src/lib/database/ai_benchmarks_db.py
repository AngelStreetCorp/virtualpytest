"""
AI benchmark results (TASK-143) — the benchmark cases live in the AI call log.

A benchmark case **is** an AI call: ``scripts/ai_bench.py`` runs the production path with one
pinned profile (``router.resolve_profile`` labels the call ``eval:<usage key>``), so the row the
call log builds already carries the model, the endpoint, the tokens, the latency and the cost.
The runner attaches the case verdict to that row (``parse_ok``) and the run and case ids
(``ref_type`` / ``ref_id`` / ``ref_kind``), so the results need no table of their own: Grafana
and Monitoring → AI usage read ``ai_calls``.

The frozen input of a case set lives in ``docs/agent/ai/benchmarks/cases/<usage key>.jsonl``
and the per-run summary in ``docs/agent/ai/benchmarks/bench-<usage key>.jsonl`` (the shape
``scripts/benchmark_log.py`` reads). The call log keeps 90 days; the result files are the
long-term record.

Every query filters by ``team_id`` unless the caller explicitly asks for all teams.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

# The stats label a pinned (scoring) call carries: eval:<usage key>.
EVAL_PREFIX = 'eval:'
# The ref_type a benchmark case carries: what the call was about.
REF_TYPE = 'benchmark'

# The error codes the call log stores, in words the page can show.
ERROR_TEXT = {
    'timeout': 'the model timed out',
    'rate_limit': 'the provider rate-limited the call',
    'no_credit': 'the provider is out of credit',
    'auth': 'the provider refused the key',
    'bad_request': 'the provider rejected the request',
    'server': 'the provider failed',
    'connection': 'the provider was unreachable',
    'empty_answer': 'the model answered nothing',
    'busy': 'the endpoint was saturated',
    'parse': 'the answer was not usable',
    'refusal': 'the model refused',
    'other': 'the call failed',
}


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def eval_label(usage_key: str) -> str:
    """The stats label a benchmark call of ``usage_key`` carries."""
    return f"{EVAL_PREFIX}{usage_key}"


def usage_key_of(label: Optional[str]) -> str:
    """The usage key behind an ``eval:<usage key>`` label."""
    label = str(label or '')
    return label[len(EVAL_PREFIX):] if label.startswith(EVAL_PREFIX) else label


def kind_of(usage_key: str) -> str:
    """What kind of case a usage key runs: text, vision or decision."""
    key = usage_key or ''
    if key.startswith('vision.'):
        return 'vision'
    if key.startswith('text.decision'):
        return 'decision'
    return 'text'


def write_cases(rows: List[Dict[str, Any]]) -> int:
    """Write the call-log rows of one run. Returns how many rows landed.

    The rows are the ones the production path built (``call_log.build_row``): only the case
    verdict and the run / case ids are added by the runner. A failure is logged, never raised:
    a benchmark run must not lose its result file because the database was unreachable.
    """
    clean = [r for r in rows if r.get('usage_key') and r.get('ref_id')]
    if not clean:
        return 0
    try:
        from shared.src.lib.database import ai_routing_db
        return ai_routing_db.ingest_calls(clean)
    except Exception as e:
        print(f"[@db:ai_benchmarks:write_cases] Error: {e}")
        return 0


def _case_view(row: Dict[str, Any]) -> Dict[str, Any]:
    """One call-log row as a benchmark case."""
    key = usage_key_of(row.get('usage_key'))
    verdict = row.get('parse_ok')
    error_type = row.get('error_type')
    return {
        'id': row.get('id'),
        'ts': row.get('ts'),
        'run_id': row.get('ref_id'),
        'team_id': row.get('team_id'),
        'uc': key,
        'usage_key': key,
        'category': category_of(key),
        'profile': row.get('profile') or '',
        'model': row.get('model'),
        'endpoint': row.get('endpoint'),
        'case_id': row.get('ref_kind'),
        'kind': kind_of(key),
        'ok': bool(verdict),
        'scored': verdict is not None,
        'score': (1.0 if verdict else 0.0) if verdict is not None else None,
        'error': ERROR_TEXT.get(error_type) if (error_type and not row.get('ok')) else None,
        'ms': int(row.get('latency_ms') or 0),
        'tokens_in': int(row.get('tokens_in') or 0),
        'tokens_out': int(row.get('tokens_out') or 0),
        'cost': row.get('cost'),
        'request_id': row.get('request_id'),
    }


def list_cases(team_id: Optional[str] = None, *, all_teams: bool = False,
               usage_key: Optional[str] = None, model: Optional[str] = None,
               since: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    """The benchmark cases, newest first. Filtered by team unless ``all_teams``.

    ``usage_key`` is the plain key (``vision.alert_triage``); the rows carry it as the stats
    label ``eval:<usage key>``.
    """
    try:
        q = (get_supabase().table('ai_calls').select('*')
             .like('usage_key', f'{EVAL_PREFIX}%').eq('ref_type', REF_TYPE)
             .order('ts', desc=True).limit(max(1, min(limit, 5000))))
        if not all_teams:
            q = q.or_(f'team_id.is.null,team_id.eq.{team_id}') if team_id else q.is_('team_id', 'null')
        if usage_key:
            q = q.eq('usage_key', eval_label(usage_key))
        if model:
            q = q.eq('model', model)
        if since:
            q = q.gte('ts', since)
        result = q.execute()
        return [_case_view(dict(r)) for r in (result.data or [])]
    except Exception as e:
        print(f"[@db:ai_benchmarks:list_cases] Error: {e}")
        return []


def category_of(usage_key: str) -> str:
    """The feature (page category) a benchmarked usage key belongs to: the production key's own."""
    from shared.src.lib.ai import usages
    return usages.page_category(usage_key or '')


def list_runs(team_id: Optional[str] = None, *, all_teams: bool = False,
              usage_key: Optional[str] = None, since: Optional[str] = None,
              limit: int = 200, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """One row per run: the usage key, the model, how many cases passed and what it cost.

    Built from the case rows, so the page never has to aggregate on the client.
    """
    rows = list_cases(team_id, all_teams=all_teams, usage_key=usage_key, since=since, limit=limit * 20)
    if category:
        rows = [r for r in rows if category_of(r.get('usage_key')) == category]
    runs: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        run_id = str(r.get('run_id') or '')
        if not run_id:
            continue
        run = runs.get(run_id)
        if run is None:
            run = runs[run_id] = {
                'run_id': run_id,
                'ts': r.get('ts'),
                'team_id': r.get('team_id'),
                'uc': r.get('uc'),
                'usage_key': r.get('usage_key'),
                'category': category_of(r.get('usage_key')),
                'profile': r.get('profile'),
                'model': r.get('model'),
                'endpoint': r.get('endpoint'),
                'cases': 0,
                'scored': 0,
                'passed': 0,
                'ms': 0,
                'tokens_in': 0,
                'tokens_out': 0,
                'cost': 0.0,
            }
        run['cases'] += 1
        run['scored'] += 1 if r.get('scored') else 0
        run['passed'] += 1 if r.get('ok') else 0
        run['ms'] += int(r.get('ms') or 0)
        run['tokens_in'] += int(r.get('tokens_in') or 0)
        run['tokens_out'] += int(r.get('tokens_out') or 0)
        run['cost'] += float(r.get('cost') or 0)
        if r.get('ts') and (not run.get('ts') or str(r['ts']) > str(run['ts'])):
            run['ts'] = r.get('ts')
    out = []
    for run in runs.values():
        run['cost'] = round(run['cost'], 8)
        run['pass_rate'] = round(run['passed'] / run['scored'], 4) if run['scored'] else 0.0
        run['score'] = run['pass_rate']
        out.append(run)
    out.sort(key=lambda r: str(r.get('ts') or ''), reverse=True)
    return out[:limit]


def usage_keys(team_id: Optional[str] = None, *, all_teams: bool = False,
               since: Optional[str] = None) -> List[str]:
    """Every usage key that has at least one benchmark case (since ``since`` when given)."""
    rows = list_cases(team_id, all_teams=all_teams, since=since, limit=5000)
    keys = {r.get('usage_key') for r in rows if r.get('usage_key')}
    return sorted(keys)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
