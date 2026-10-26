"""
CI/CD and integrations — the slice of the GitLab REST API the app needs.

Self-hosted GitLab, so the base URL is configuration rather than a constant: the customer's
instance answers on its own address, often plain HTTP and often behind an internal CA. Auth is
a Personal Access Token in the PRIVATE-TOKEN header — no redirect URI, no application
registration, works on every GitLab from 11.x up.

Verified 2026-10-13 against GitLab CE 19.4.2 (Omnibus), the version the customer runs.

stdlib only (urllib) to match github_api.py and the rest of the server; every call raises
GitLabError with a readable message so routes can turn it into a 502 + reason instead of a stack.

Multi-instance: every public function takes keyword-only `api` / `tok` so a configured instance
(base URL + token from the settings form) can be used without mutating module state — Flask is
multi-threaded, so an env-var write per request would not be safe. Left unset, the module's
env-backed defaults are used (GITLAB_URL / GITLAB_TOKEN).

Env:
    GITLAB_URL         base URL, e.g. https://gitlab.customer.tld  (default gitlab.com)
    GITLAB_TOKEN       PAT with `api` to trigger pipelines, `read_api` to only read
    GITLAB_CA_BUNDLE   path to an internal CA .crt, when the instance is on https
    GITLAB_INSECURE    set to 1 to skip TLS verification — last resort, see _ssl_context()
"""

import base64
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

API = os.environ.get('GITLAB_URL', 'https://gitlab.com').rstrip('/')
TIMEOUT = 15

#: GitLab job status -> the three states `cicd.ci_jobs.status` understands.
#: An unrecognised status maps to 'running' on purpose: one we cannot name is one we
#: cannot claim has finished.
JOB_STATUS_MAP = {
    'success': 'success',
    'skipped': 'success',
    'failed': 'failure',
    'canceled': 'failure',
    'created': 'running',
    'waiting_for_resource': 'running',
    'preparing': 'running',
    'pending': 'running',
    'running': 'running',
    'manual': 'running',
    'scheduled': 'running',
}


class GitLabError(RuntimeError):
    def __init__(self, status: int, message: str, url: str = '', payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload
        self.url = url


def token() -> str:
    return os.environ.get('GITLAB_TOKEN', '').strip()


def project_ref(project: str) -> str:
    """GitLab accepts a numeric id or a path; a path has to be URL-encoded whole.

    `group/sub/project` is not valid unencoded — the slashes are read as path separators.
    """
    if str(project).isdigit():
        return str(project)
    return urllib.parse.quote(str(project), safe="")


def file_ref(path: str) -> str:
    """Same rule for a file path inside the repository."""
    return urllib.parse.quote(str(path), safe="")


def _ssl_context() -> Optional[ssl.SSLContext]:
    """None means "urllib default". A CA bundle is honoured so an internal CA works
    without turning verification off; GITLAB_INSECURE is the explicit opt-out."""
    bundle = os.environ.get('GITLAB_CA_BUNDLE', '').strip()
    if bundle:
        return ssl.create_default_context(cafile=bundle)
    if os.environ.get('GITLAB_INSECURE', '').strip() in ('1', 'true', 'yes'):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


def _request(path: str, method: str = 'GET', body: Optional[dict] = None,
             form: Optional[Dict[str, str]] = None,
             api: Optional[str] = None, tok: Optional[str] = None) -> Any:
    """Call the API. `body` is JSON, `form` is urlencoded (GitLab's inputs[] style).

    `api`/`tok` override the env-backed instance for one call; pass them to talk to a
    configured instance without touching module state.
    """
    base = (api or API).rstrip('/')
    secret = tok if tok is not None else token()
    if not secret:
        raise GitLabError(0, 'No GitLab token: set GITLAB_TOKEN or configure an instance')

    data = None
    headers = {'PRIVATE-TOKEN': secret, 'Accept': 'application/json',
               'User-Agent': 'virtualpytest-gitlab'}
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'

    url = f'{base}/api/v4{path}'
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = ''
        payload = None
        try:
            payload = json.loads(e.read()) or {}
            message = payload.get('message') if isinstance(payload, dict) else None
            # GitLab answers {"message": "..."} for most errors but
            # {"message": {"base": ["..."]}} for validation failures — and bare
            # {"error": "variables is invalid"} for a removed parameter. All must be readable.
            if isinstance(message, dict):
                detail = '; '.join(f'{k}: {" ".join(v)}' if isinstance(v, list) else f'{k}: {v}'
                                   for k, v in message.items())
            elif message:
                detail = str(message)
            elif isinstance(payload, dict) and payload.get('error'):
                detail = str(payload['error'])
        except Exception:
            pass
        raise GitLabError(e.code, f'GitLab {e.code} on {method} {path}'
                                   f'{": " + detail if detail else ""}', url, payload)
    except urllib.error.URLError as e:
        raise GitLabError(0, f'GitLab unreachable at {base} on {method} {path}: {e.reason}', url)
    except Exception as e:
        raise GitLabError(0, f'GitLab request failed on {method} {path}: {e}', url)


# ─── instance / identity ─────────────────────────────────────────────────────

def version(*, api: Optional[str] = None, tok: Optional[str] = None) -> Dict[str, Any]:
    """Instance version — the cheapest proof that base URL + token are both right."""
    return _request('/version', api=api, tok=tok)


def current_user(*, api: Optional[str] = None, tok: Optional[str] = None) -> Dict[str, Any]:
    """Who the token belongs to. Also the cheapest proof the token is valid."""
    return _request('/user', api=api, tok=tok)


def projects(search: Optional[str] = None, per_page: int = 50,
             api: Optional[str] = None, tok: Optional[str] = None) -> List[Dict[str, Any]]:
    """Projects visible to the token."""
    query = [f'per_page={per_page}']
    if search:
        query.append(f'search={urllib.parse.quote(search, safe="")}')
    data = _request('/projects?' + '&'.join(query), api=api, tok=tok)
    return data if isinstance(data, list) else []


def resolve_project(project: str, *, api: Optional[str] = None,
                    tok: Optional[str] = None) -> Dict[str, Any]:
    """Fetch one project by id or path."""
    return _request(f'/projects/{project_ref(project)}', api=api, tok=tok)


# ─── repository ──────────────────────────────────────────────────────────────

def _commit_summary(c: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The four commit fields a GitHub-style "latest commit" row needs."""
    if not isinstance(c, dict):
        return None
    return {
        'short_id': c.get('short_id') or (c.get('id') or '')[:8],
        'title': c.get('title'),
        'author_name': c.get('author_name'),
        'committed_date': c.get('committed_date'),
    }


def branches(project: str, per_page: int = 30, *, api: Optional[str] = None,
             tok: Optional[str] = None) -> List[Dict[str, Any]]:
    """Branches with their last commit: [{name, commit: {short_id,title,author_name,committed_date}}]."""
    # Note the /repository/ segment: GitHub's /repos/:repo/branches does not exist here and
    # answers a bare {"error": "404 Not Found"} from Workhorse rather than a GitLab error.
    data = _request(f'/projects/{project_ref(project)}/repository/branches?per_page={per_page}',
                    api=api, tok=tok)
    names = [entry["name"] for entry in data if entry.get("name")]
    return names


#: Per-entry last-commit lookups: GitLab REST has no batch endpoint for this, so each entry is
#: one /repository/commits call. Bounded fan-out, capped entries, short cache.
COMMIT_FANOUT = 8
COMMIT_ENTRY_CAP = 50
COMMIT_CACHE_TTL = 60
_commit_cache: Dict[Any, Any] = {}


def last_commits(project: str, ref: Optional[str], paths: List[str], *,
                 api: Optional[str] = None, tok: Optional[str] = None) -> Dict[str, Optional[Dict[str, Any]]]:
    """{path: commit summary or None} for up to COMMIT_ENTRY_CAP paths, fetched in parallel."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    def one(path: str) -> Optional[Dict[str, Any]]:
        key = (api, project, ref, path)
        hit = _commit_cache.get(key)
        if hit and time.time() - hit[0] < COMMIT_CACHE_TTL:
            return hit[1]
        query = ['per_page=1', f'path={urllib.parse.quote(path, safe="")}']
        if ref:
            query.append(f'ref_name={urllib.parse.quote(ref, safe="")}')
        try:
            data = _request(f'/projects/{project_ref(project)}/repository/commits?' + '&'.join(query),
                            api=api, tok=tok)
            value = _commit_summary(data[0]) if isinstance(data, list) and data else None
        except GitLabError:
            return None
        _commit_cache[key] = (time.time(), value)
        return value

    wanted = paths[:COMMIT_ENTRY_CAP]
    with ThreadPoolExecutor(max_workers=COMMIT_FANOUT) as pool:
        return dict(zip(wanted, pool.map(one, wanted)))


def overview(project: str, ref: Optional[str] = None, *, api: Optional[str] = None,
             tok: Optional[str] = None) -> Dict[str, Any]:
    """What the repo home's side panels need, in one call: description, visibility, clone URLs,
    commit count (project statistics), tag count (capped at one page) and the newest pipeline
    on `ref`."""
    row = _request(f'/projects/{project_ref(project)}?statistics=true', api=api, tok=tok)
    tags = _request(f'/projects/{project_ref(project)}/repository/tags?per_page=100', api=api, tok=tok)
    try:
        runs = pipeline_runs(project, ref=ref, per_page=1, api=api, tok=tok)
    except GitLabError:
        runs = []
    stats = row.get('statistics') or {}
    return {
        'description': row.get('description'),
        'visibility': row.get('visibility'),
        'http_url': row.get('http_url_to_repo'),
        'ssh_url': row.get('ssh_url_to_repo'),
        'default_branch': row.get('default_branch'),
        'last_activity_at': row.get('last_activity_at'),
        'web_url': row.get('web_url'),
        'commit_count': stats.get('commit_count'),
        'tag_count': len(tags) if isinstance(tags, list) else 0,
        'last_pipeline': runs[0] if runs else None,
    }


def repository_tree(project: str, ref: Optional[str] = None, path: str = '',
                    recursive: bool = False, per_page: int = 100, *,
                    api: Optional[str] = None, tok: Optional[str] = None) -> List[Dict[str, Any]]:
    """Files and folders at `path`.

    GitLab caps a page at 100 entries and says nothing about a total, so the listing is one
    page: a project browser showing a whole repository would need cursor paging, which is
    more than the page needs.
    """
    query = [f'per_page={per_page}']
    if ref:
        query.append(f'ref={urllib.parse.quote(ref, safe="")}')
    if path:
        query.append(f'path={urllib.parse.quote(path, safe="")}')
    if recursive:
        query.append('recursive=true')
    data = _request(f'/projects/{project_ref(project)}/repository/tree?' + '&'.join(query),
                    api=api, tok=tok)
    out = []
    for entry in (data if isinstance(data, list) else []):
        out.append({
            'name': entry.get('name'),
            'path': entry.get('path'),
            'type': entry.get('type'),          # tree (folder) | blob (file)
            'mode': entry.get('mode'),
        })
    return out


def readme(project: str, ref: Optional[str] = None, *, api: Optional[str] = None,
           tok: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The project's README, decoded. None when the project has none — not an error.

    GitLab v4 has NO `/projects/:id/readme` endpoint (it answers 404 on a real instance); a
    repository file is only reachable through `/repository/files/:file_path`, and the name is
    not known in advance. So the root tree is listed and the README is resolved from it: the
    project may call it `README.md`, `Readme.rst` or plain `README`, and picking the wrong one
    is why this could not just guess a filename.
    """
    entries = repository_tree(project, ref=ref, path='', api=api, tok=tok)
    name = _readme_name(entries)
    if not name:
        return None
    return file_content(project, name, ref=ref, api=api, tok=tok)


def _readme_name(entries: List[Dict[str, Any]]) -> Optional[str]:
    """The README among root entries, markdown first — None when the project has no README."""
    names = [e.get('name') for e in entries if e.get('type') != 'tree' and e.get('name')]
    candidates = [n for n in names if str(n).lower().startswith('readme')]
    if not candidates:
        return None
    # `README.md` wins over `README.rst`, which wins over anything else.
    for suffix in ('.md', '.markdown', '.mdx', '.rst'):
        for name in candidates:
            if str(name).lower().endswith(suffix):
                return name
    return candidates[0]


def file_content(project: str, path: str, ref: Optional[str] = None, *,
                 api: Optional[str] = None, tok: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One repository file, decoded. None when GitLab reports it as too large to inline."""
    query = f'?ref={urllib.parse.quote(ref, safe="")}' if ref else ''
    data = _request(
        f'/projects/{project_ref(project)}/repository/files/{file_ref(path)}{query}',
        api=api, tok=tok)
    return _decoded_file(data) if isinstance(data, dict) else None


def _decoded_file(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """GitLab returns repository file content base64-encoded; give back text.

    Binary content is not decoded — the caller gets None and should not try to render it.
    """
    raw = data.get('content')
    if raw is None:
        return None
    if data.get('encoding') != 'base64':
        return {'path': data.get('file_name') or data.get('path'),
                'ref': data.get('ref'), 'content': raw, 'binary': False}
    try:
        decoded = base64.b64decode(raw)
    except Exception:
        return None
    try:
        return {'path': data.get('file_name') or data.get('path'),
                'ref': data.get('ref'), 'content': decoded.decode('utf-8'), 'binary': False}
    except UnicodeDecodeError:
        return {'path': data.get('file_name') or data.get('path'),
                'ref': data.get('ref'), 'content': None, 'binary': True}


# ─── pipelines / jobs ────────────────────────────────────────────────────────

def pipeline_runs(project: str, ref: Optional[str] = None, status: Optional[str] = None,
                  per_page: int = 20, *, api: Optional[str] = None,
                  tok: Optional[str] = None) -> List[Dict[str, Any]]:
    """Recent pipelines — the GitLab counterpart of workflow_runs().

    `status` takes GitLab's own values (running, pending, success, failed, …). Pipelines are
    already ref-scoped here, so there is no separate branch/status sweep like GitHub needs.
    """
    query = [f'per_page={per_page}']
    if ref:
        query.append(f'ref={urllib.parse.quote(ref, safe="")}')
    if status:
        query.append(f'status={urllib.parse.quote(status, safe="")}')
    data = _request(f'/projects/{project_ref(project)}/pipelines?' + '&'.join(query),
                    api=api, tok=tok)
    out = []
    for p in (data if isinstance(data, list) else []):
        out.append({
            'gitlab_pipeline_id': p.get('id'),
            'branch': p.get('ref'),
            'sha': (p.get('sha') or '')[:7],
            'status': p.get('status'),                # created|pending|running|success|failed|…
            'conclusion': p.get('status') if p.get('status') in ('success', 'failed', 'canceled') else None,
            'source': p.get('source'),                # push|web|schedule|api|…
            'created_at': p.get('created_at'),
            'updated_at': p.get('updated_at'),
            'html_url': p.get('web_url'),
        })
    return out


def in_progress_runs(project: str, *, api: Optional[str] = None,
                     tok: Optional[str] = None) -> List[Dict[str, Any]]:
    """Queued + running pipelines, so a page can show LIVE state before any publish step."""
    runs: List[Dict[str, Any]] = []
    seen = set()
    for state in ('running', 'pending'):
        for r in pipeline_runs(project, status=state, per_page=10, api=api, tok=tok):
            if r['gitlab_pipeline_id'] not in seen:
                seen.add(r['gitlab_pipeline_id'])
                runs.append(r)
    return runs


def run_jobs(project: str, pipeline_id: int, per_page: int = 50, *,
             api: Optional[str] = None, tok: Optional[str] = None) -> List[Dict[str, Any]]:
    """Per-job state of one pipeline — drives the "3/8 jobs" progress on a live row.

    `runner` is what attributes a job to a runner card; `allow_failure` is kept because
    GitLab does not fail a pipeline over an allowed failure and neither should we.
    """
    data = _request(
        f'/projects/{project_ref(project)}/pipelines/{pipeline_id}/jobs?per_page={per_page}',
        api=api, tok=tok)
    out = []
    for j in (data if isinstance(data, list) else []):
        gitlab_status = j.get('status')
        runner = j.get('runner') or {}
        out.append({
            'name': j.get('name'),
            'stage': j.get('stage'),
            'status': gitlab_status,
            'conclusion': gitlab_status if gitlab_status in ('success', 'failed', 'canceled') else None,
            'cicd_status': JOB_STATUS_MAP.get((gitlab_status or '').lower(), 'running'),
            'runner_name': runner.get('description') or runner.get('id'),
            'allow_failure': bool(j.get('allow_failure', False)),
            'started_at': j.get('started_at'),
            'finished_at': j.get('finished_at'),
            'html_url': j.get('web_url'),
        })
    return out


def trigger_pipeline(project: str, ref: str, inputs: Optional[Dict[str, str]] = None, *,
                     api: Optional[str] = None, tok: Optional[str] = None) -> Dict[str, Any]:
    """Start a pipeline.

    The ref goes on the query string. GitLab 19.4 CE is strict about everything else, checked
    live against 19.4.2 on 2026-10-13:

      * `variables[KEY]=value`  -> 400 {"error": "variables is invalid"} (removed from this endpoint)
      * `inputs[KEY]=value`     -> 400 unless the CI file declares a matching `spec: inputs`,
        and on CE 19.4 the linter rejects both a top-level `spec:` (it reads it as a job:
        "jobs spec config should implement the script:, run:, or trigger: keyword") and a
        job-level `spec:` ("config contains unknown keys: spec")
      * so on CE the only usable form is a bare ref.

    Callers that need to pass data to the job must encode it in the ref or in the repository
    (a branch, a committed file, a project-level CI/CD variable) rather than in the trigger.
    A missing ref returns 400 {"message": {"base": ["Reference not found"]}}, which this
    surfaces in the GitLabError instead of a bare status code.
    """
    form = {f'inputs[{k}]': v for k, v in (inputs or {}).items()}
    return _request(f'/projects/{project_ref(project)}/pipeline?ref={urllib.parse.quote(ref, safe="")}',
                    method='POST', form=form, api=api, tok=tok)


def job_trace(project: str, job_id: int, *, api: Optional[str] = None,
              tok: Optional[str] = None) -> str:
    """Raw log of one job. Returns text (never JSON) — GitLab serves this as plain text."""
    tok_value = tok if tok is not None else token()
    if not tok_value:
        raise GitLabError(0, 'No GitLab token: set GITLAB_TOKEN or configure an instance')
    base = (api or API).rstrip('/')
    url = f'{base}/api/v4/projects/{project_ref(project)}/jobs/{job_id}/trace'
    req = urllib.request.Request(url, headers={'PRIVATE-TOKEN': tok_value,
                                               'User-Agent': 'virtualpytest-gitlab'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        raise GitLabError(e.code, f'GitLab {e.code} on trace job {job_id}', url)
    except Exception as e:
        raise GitLabError(0, f'GitLab request failed on trace job {job_id}: {e}', url)


# ─── runners ─────────────────────────────────────────────────────────────────

def runners(project: Optional[str] = None, per_page: int = 50, *,
            api: Optional[str] = None, tok: Optional[str] = None) -> List[Dict[str, Any]]:
    """Runners registered on the instance, or on one project when `project` is given.

    Liveness is read from `status` (falling back to `online`). Do NOT key off `contacted_at`:
    19.4 does not return that field for instance runners at all, so a contacted_at check marks
    every runner offline — verified live against 19.4.2. `job_execution_status` is what says
    the runner is mid-job, which is the "busy" the runner cards need.
    """
    if project:
        data = _request(f'/projects/{project_ref(project)}/runners?per_page={per_page}',
                        api=api, tok=tok)
    else:
        data = _request(f'/runners/all?per_page={per_page}', api=api, tok=tok)
    out = []
    for r in (data if isinstance(data, list) else []):
        status = r.get('status') or ('online' if r.get('online') else 'offline')
        out.append({
            'id': r.get('id'),
            'name': r.get('description'),
            'status': status,
            'busy': r.get('job_execution_status') == 'running',
            'labels': r.get('tag_list') or [],
            'target': 'self-hosted',
        })
    return out