"""
CI/CD feature — the slice of the GitHub REST API the pages need.

Uses `GITHUB_TOKEN` (checked 2026-09-03: OAuth token of `angelstreet`, scopes
`gist, read:org, repo, workflow`, no expiry — enough for runners, workflow runs and
workflow_dispatch on both AngelStreetCorp/virtualpytest and example-org/sample-app).

stdlib only (urllib) to match the rest of the server; every call raises GitHubError
with a readable message so routes can turn it into a 502 + reason instead of a stack.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

API = 'https://api.github.com'
TIMEOUT = 10

#: The synthetic runner row for GitHub-hosted execution — always available, no LAN.
CLOUD_RUNNER = 'github-hosted'


class GitHubError(RuntimeError):
    pass


def token() -> str:
    return os.environ.get('GITHUB_TOKEN', '').strip()


def _request(path: str, method: str = 'GET', body: Optional[dict] = None) -> Any:
    tok = token()
    if not tok:
        raise GitHubError('GITHUB_TOKEN not set on the server')
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f'{API}{path}',
        data=data,
        method=method,
        headers={
            'Authorization': f'token {tok}',
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json',
            'User-Agent': 'virtualpytest-cicd',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = (json.loads(e.read()) or {}).get('message', '')
        except Exception:
            pass
        raise GitHubError(f'GitHub {e.code} on {method} {path}{": " + detail if detail else ""}')
    except Exception as e:
        raise GitHubError(f'GitHub request failed on {method} {path}: {e}')


def self_hosted_runners(repo: str) -> List[Dict[str, Any]]:
    """Self-hosted runners registered on the repo."""
    data = _request(f'/repos/{repo}/actions/runners')
    out = []
    for r in data.get('runners', []):
        out.append({
            'name': r.get('name'),
            'status': r.get('status'),                    # online | offline
            'busy': bool(r.get('busy')),
            'labels': [l.get('name') for l in r.get('labels', []) if l.get('name')],
            'target': 'self-hosted',
        })
    return out


def dispatch_workflow(repo: str, workflow_file: str, ref: str, inputs: Dict[str, str]) -> None:
    """Fire workflow_dispatch. GitHub answers 204 with no body on success.

    Inputs the workflow does not declare make GitHub reject the whole call, so callers
    must only pass inputs known to exist in that repo's workflow.
    """
    _request(
        f'/repos/{repo}/actions/workflows/{workflow_file}/dispatches',
        method='POST',
        body={'ref': ref, 'inputs': inputs},
    )


def workflow_runs(repo: str, workflow_file: str, branch: Optional[str] = None,
                  status: Optional[str] = None, per_page: int = 20) -> List[Dict[str, Any]]:
    """Recent runs of one workflow. `status` accepts GitHub's filters, e.g. `in_progress`."""
    query = [f'per_page={per_page}']
    if branch:
        query.append(f'branch={urllib.parse.quote(branch)}')
    if status:
        query.append(f'status={status}')
    path = f'/repos/{repo}/actions/workflows/{workflow_file}/runs?' + '&'.join(query)
    data = _request(path)
    out = []
    for r in data.get('workflow_runs', []):
        out.append({
            'github_run_id': r.get('id'),
            'run_number': r.get('run_number'),
            'branch': r.get('head_branch'),
            'sha': (r.get('head_sha') or '')[:7],
            'status': r.get('status'),                    # queued | in_progress | completed
            'conclusion': r.get('conclusion'),            # success | failure | cancelled | None
            'event': r.get('event'),                      # push | workflow_dispatch | schedule
            'created_at': r.get('created_at'),
            'updated_at': r.get('updated_at'),
            'html_url': r.get('html_url'),
        })
    return out


def in_progress_runs(repo: str, workflow_file: str) -> List[Dict[str, Any]]:
    """Queued + running runs, so the page can show LIVE state before any publish step."""
    runs: List[Dict[str, Any]] = []
    seen = set()
    for state in ('queued', 'in_progress'):
        for r in workflow_runs(repo, workflow_file, status=state, per_page=10):
            if r['github_run_id'] not in seen:
                seen.add(r['github_run_id'])
                runs.append(r)
    return runs


def run_jobs(repo: str, github_run_id: int) -> List[Dict[str, Any]]:
    """Per-job state of one GitHub run — drives the "3/8 jobs" progress on the live row.

    `started_at` is carried so the runner cards can show how long the job a runner is
    currently executing has been going; `runner_name` is what attributes a job to a card.
    """
    data = _request(f'/repos/{repo}/actions/runs/{github_run_id}/jobs?per_page=50')
    out = []
    for j in data.get('jobs', []):
        out.append({
            'name': j.get('name'),
            'status': j.get('status'),
            'conclusion': j.get('conclusion'),
            'runner_name': j.get('runner_name'),
            'started_at': j.get('started_at'),
        })
    return out


def branches(repo: str, per_page: int = 30) -> List[str]:
    data = _request(f'/repos/{repo}/branches?per_page={per_page}')
    return [b.get('name') for b in data if isinstance(b, dict) and b.get('name')]
