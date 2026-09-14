"""
CI/CD feature — backend_server part (TASK-06 W2/W5/W7).

Registered by shared/src/lib/utils/features.py when the feature is enabled
(docs/technical/FEATURES.md). Everything lives under /server/cicd.

Replaces the core blueprint `server_ci_reports_routes.py`: the runs/jobs data now comes
from the `cicd` schema (single source of truth shared with the Grafana dashboard), while
the report HTML keeps being served off disk from /opt/ci-reports.

Auth follows the current /server/* baseline (docs: project_server_auth_baseline): reads
are open like the rest of /server/*, launching a run needs a signed-in user, editing the
project registry needs the admin role, and the workflow ingest endpoint carries its own
bearer token.
"""

import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request, send_from_directory

from backend_server.src.lib.auth_middleware import require_role, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

from features.cicd.lib import cicd_db
from features.cicd.lib import github_api

feature_cicd_bp = Blueprint('feature_cicd', __name__, url_prefix='/server/cicd')

#: Where the workflows' publish steps drop the HTML reports (same as the core route used).
CI_REPORTS_DIR = Path(os.environ.get('CI_REPORTS_DIR', '/opt/ci-reports'))

#: Runner name -> LAN address of its VM, for the restart button. Extend with
#: CI_RUNNER_HOSTS (JSON object); CI_RUNNER_HOST is the fallback.
#:
#: Additional project runners are configured through CI_RUNNER_HOSTS.
_DEFAULT_RUNNER_HOSTS = {
    # Proxmox VM 163 "cicd-runner"
    'vpt-163-1': '192.168.0.163',
    'vpt-163-2': '192.168.0.163',
    'vpt-163-3': '192.168.0.163',
    # Proxmox VM 164 "cicd-clone-1"
    'vpt-164-1': '192.168.0.164',
    'vpt-164-2': '192.168.0.164',
    'vpt-164-3': '192.168.0.164',
}

SUITES = ('white', 'grey', 'all')
RUNNER_TARGETS = ('self-hosted', 'github-hosted')


def _not_configured(reason: str):
    """Single shape the pages render as "CI/CD not configured: …"."""
    return jsonify({'success': False, 'configured': False, 'error': reason})


# ─── config / health ─────────────────────────────────────────────────────────

@feature_cicd_bp.route('/health', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('cicd:health')
def health():
    """What the feature can currently do — drives the pages' disabled states."""
    schema_error = cicd_db.schema_error()
    return jsonify({
        'success': True,
        'configured': schema_error is None,
        'schema_error': schema_error,
        'github_token': bool(github_api.token()),
        'reports_dir': str(CI_REPORTS_DIR),
        'reports_dir_present': CI_REPORTS_DIR.exists(),
        'ingest_token': bool(os.environ.get('CICD_INGEST_TOKEN', '').strip()),
    })


# ─── project registry ────────────────────────────────────────────────────────

@feature_cicd_bp.route('/projects', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('cicd:list_projects')
def list_projects():
    error = cicd_db.schema_error()
    if error:
        return _not_configured(error)
    return jsonify({'success': True, 'configured': True, 'projects': cicd_db.list_projects()})


@feature_cicd_bp.route('/projects/<project>', methods=['PUT'], strict_slashes=False)
@require_user_auth
@require_role('admin')
@handle_route_exceptions('cicd:update_project')
def update_project(project: str):
    error = cicd_db.schema_error()
    if error:
        return _not_configured(error)
    payload = request.get_json(silent=True) or {}
    row = cicd_db.upsert_project(project, payload)
    return jsonify({'success': True, 'project': row})


# ─── runs ────────────────────────────────────────────────────────────────────

@feature_cicd_bp.route('/runs', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('cicd:list_runs')
def list_runs():
    """ci_run_summary rows, newest first. `?expand=jobs` attaches each run's jobs.

    `?changed_since=<ISO>` returns only runs started or updated (a job finished) at or after
    that instant, so the Reports page can merge deltas into its cached list instead of
    re-reading all 200 runs with their jobs every 15-60 s. The client derives the cursor
    from the newest `started_at` / `finished_at` it already holds (database clock), so no
    server_time is echoed back — the server VM and the database VM keep separate clocks.
    """
    error = cicd_db.schema_error()
    if error:
        return _not_configured(error)

    project = request.args.get('project') or None
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
    except ValueError:
        limit = 50

    runs = cicd_db.list_runs(
        project=project,
        since=request.args.get('since') or None,
        until=request.args.get('until') or None,
        branch=request.args.get('branch') or None,
        suite=request.args.get('suite') or None,
        limit=limit,
        changed_since=request.args.get('changed_since') or None,
    )

    if request.args.get('expand') == 'jobs' and runs:
        jobs = cicd_db.list_jobs(project, [r['run'] for r in runs])
        by_run: Dict[str, Dict[str, Any]] = {}
        for job in jobs:
            # keyed by job name so the page can render the same {job: {...}} map the
            # old disk-based /server/ci-reports/list returned
            by_run.setdefault(f"{job['project']}/{job['run']}", {})[job['job']] = job
        for run in runs:
            run['jobs_detail'] = by_run.get(f"{run['project']}/{run['run']}", {})

    return jsonify({'success': True, 'configured': True, 'runs': runs})


@feature_cicd_bp.route('/runs/<project>/<run>', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('cicd:get_run')
def get_run(project: str, run: str):
    error = cicd_db.schema_error()
    if error:
        return _not_configured(error)
    summary, jobs = cicd_db.get_run(project, run)
    if summary is None:
        return jsonify({'success': False, 'error': f'run {project}/{run} not found'}), 404
    return jsonify({'success': True, 'run': summary, 'jobs': jobs})


# ─── runners ─────────────────────────────────────────────────────────────────

def _can_run(cloud_suites: List[str]) -> List[str]:
    """Suites a GitHub-hosted runner may execute for a project.

    'all' only when the cloud is trusted with both layers; with the shipped seed
    (white only, because Cloudflare blocks non-browser clients on the public URL) the
    Run page therefore disables grey and all for the cloud row, with the reason shown.
    """
    suites = [s for s in cloud_suites if s in ('white', 'grey')]
    if 'white' in suites and 'grey' in suites:
        suites.append('all')
    return suites


@feature_cicd_bp.route('/runners', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('cicd:list_runners')
def list_runners():
    """Self-hosted runners of each project's repo plus the synthetic cloud runner."""
    error = cicd_db.schema_error()
    if error:
        return _not_configured(error)

    wanted = request.args.get('project') or None
    runners: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    for proj in cicd_db.list_projects(include_disabled=False):
        name = proj['project']
        if wanted and name != wanted:
            continue
        try:
            for runner in github_api.self_hosted_runners(proj['repo']):
                runner.update({
                    'project': name,
                    'repo': proj['repo'],
                    # the LAN runner is the only one that can reach LAN-only targets
                    'can_run': list(SUITES),
                })
                runners.append(runner)
        except github_api.GitHubError as e:
            errors[name] = str(e)

        runners.append({
            'name': github_api.CLOUD_RUNNER,
            'status': 'online',                 # GitHub-hosted capacity is always available
            'busy': False,
            'labels': ['ubuntu-latest'],
            'target': 'github-hosted',
            'project': name,
            'repo': proj['repo'],
            'can_run': _can_run(proj.get('cloud_suites') or []),
        })

    return jsonify({'success': True, 'configured': True, 'runners': runners, 'errors': errors})


@feature_cicd_bp.route('/branches', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('cicd:branches')
def branches():
    """Branch names of one project's repo, for the Run page's branch picker."""
    error = cicd_db.schema_error()
    if error:
        return _not_configured(error)
    project = cicd_db.get_project(request.args.get('project') or '')
    if project is None:
        return jsonify({'success': False, 'error': 'unknown project'}), 400
    try:
        names = github_api.branches(project['repo'])
    except github_api.GitHubError as e:
        # Not fatal: the page falls back to the project's default branch.
        return jsonify({'success': True, 'branches': [project.get('default_branch') or 'main'],
                        'error': str(e)})
    return jsonify({'success': True, 'branches': names})


def _runner_host(name: str) -> str:
    hosts = dict(_DEFAULT_RUNNER_HOSTS)
    raw = os.environ.get('CI_RUNNER_HOSTS', '').strip()
    if raw:
        try:
            hosts.update(json.loads(raw))
        except Exception:
            pass
    return hosts.get(name) or os.environ.get('CI_RUNNER_HOST', '192.168.0.163')


@feature_cicd_bp.route('/runners/<name>/restart', methods=['POST'], strict_slashes=False)
@handle_route_exceptions('cicd:restart_runner')
def restart_runner(name: str):
    """SSH into the runner VM and restart its GitHub Actions runner service.

    Moved verbatim from the core ci-reports blueprint (same env contract), except that
    the synthetic cloud runner has nothing to restart.
    """
    if name == github_api.CLOUD_RUNNER:
        return jsonify({'success': False, 'error': 'GitHub-hosted capacity has no runner to restart'})

    host = _runner_host(name)
    user = os.environ.get('CI_RUNNER_USER', 'jndoye')
    password = os.environ.get('CI_RUNNER_SSH_PASSWORD', '')
    jump = os.environ.get('CI_RUNNER_SSH_JUMP', '')     # e.g. "jndoye@<origin-ip>"
    ssh_key = os.environ.get('CI_RUNNER_SSH_KEY', '')   # path to private key

    ssh_opts = ['-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=10', '-o', 'BatchMode=no']
    if jump:
        ssh_opts += ['-o', f'ProxyJump={jump}']
    if ssh_key:
        ssh_opts += ['-i', ssh_key]

    # The official runner installs as actions.runner.<owner>-<repo>.<name>.service. A VM
    # hosts several of those (virtualpytest + sample-app runners side by side), so match the
    # unit that ends in this runner's own name — picking the first unit on the box would
    # restart an unrelated runner. Fall back to the any-runner match, then to the
    # hand-written github-runner unit older VMs used.
    quoted = shlex.quote(name)
    remote_cmd = (
        f"N={quoted}; "
        "U=$(systemctl list-units --all --no-legend \"actions.runner.*.$N.service\" | awk '{print $1}' | head -1); "
        "U=${U:-$(systemctl list-units --all --no-legend 'actions.runner.*.service' | awk '{print $1}' | head -1)}; "
        "U=${U:-github-runner}; sudo systemctl restart \"$U\" && sudo systemctl status \"$U\" --no-pager -l | head -8"
    )

    try:
        if password and not ssh_key:
            if not shutil.which('sshpass'):
                return jsonify({'success': False, 'error': 'sshpass not installed on server — set CI_RUNNER_SSH_KEY instead'})
            cmd = ['sshpass', '-p', password, 'ssh'] + ssh_opts + [f'{user}@{host}', remote_cmd]
        else:
            cmd = ['ssh'] + ssh_opts + [f'{user}@{host}', remote_cmd]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return jsonify({'success': True, 'output': result.stdout.strip()})
        return jsonify({'success': False, 'error': result.stderr.strip() or result.stdout.strip()})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'SSH timed out after 30 seconds'})


# ─── dispatch / live ─────────────────────────────────────────────────────────

@feature_cicd_bp.route('/dispatch', methods=['POST'], strict_slashes=False)
@require_user_auth
@handle_route_exceptions('cicd:dispatch')
def dispatch():
    """Launch a workflow run: {project, branch, suite, runner}.

    Records the request in ci_dispatches, fires workflow_dispatch, then polls GitHub
    briefly so the caller gets the run id back (the API has no synchronous answer).
    """
    error = cicd_db.schema_error()
    if error:
        return _not_configured(error)

    payload = request.get_json(silent=True) or {}
    project_name = (payload.get('project') or '').strip()
    suite = (payload.get('suite') or 'all').strip()
    runner_target = (payload.get('runner') or 'self-hosted').strip()

    project = cicd_db.get_project(project_name) if project_name else None
    if project is None:
        return jsonify({'success': False, 'error': f'unknown project {project_name!r}'}), 400
    if suite not in SUITES:
        return jsonify({'success': False, 'error': f'suite must be one of {", ".join(SUITES)}'}), 400
    if runner_target not in RUNNER_TARGETS:
        return jsonify({'success': False, 'error': f'runner must be one of {", ".join(RUNNER_TARGETS)}'}), 400

    if runner_target == 'github-hosted' and suite not in _can_run(project.get('cloud_suites') or []):
        allowed = ', '.join(_can_run(project.get('cloud_suites') or [])) or 'nothing'
        return jsonify({
            'success': False,
            'error': f'{suite} cannot run on GitHub-hosted capacity for {project_name} (allowed: {allowed})',
        }), 400

    branch = (payload.get('branch') or project.get('default_branch') or 'main').strip()
    requested_by = getattr(request, 'user_email', None)

    dispatch_id = cicd_db.record_dispatch(project_name, branch, suite, runner_target, requested_by)

    try:
        github_api.dispatch_workflow(
            project['repo'], project['workflow_file'], branch,
            {'suite': suite, 'runner': runner_target},
        )
    except github_api.GitHubError as e:
        if dispatch_id:
            cicd_db.update_dispatch(dispatch_id, status='error')
        return jsonify({'success': False, 'error': str(e)}), 502

    # Poll for the run this dispatch created (GitHub needs a moment to register it).
    found: Optional[Dict[str, Any]] = None
    deadline = time.time() + 20
    while time.time() < deadline and found is None:
        time.sleep(2)
        try:
            for run in github_api.workflow_runs(project['repo'], project['workflow_file'],
                                                branch=branch, per_page=10):
                if run.get('event') == 'workflow_dispatch' and run.get('status') in ('queued', 'in_progress'):
                    found = run
                    break
        except github_api.GitHubError:
            break   # dispatch already succeeded; the live endpoint will pick the run up

    if found and dispatch_id:
        cicd_db.update_dispatch(dispatch_id, github_run_id=found['github_run_id'], status='running')

    return jsonify({
        'success': True,
        'dispatch_id': dispatch_id,
        'project': project_name,
        'branch': branch,
        'suite': suite,
        'runner': runner_target,
        'run': found,
    })


@feature_cicd_bp.route('/live', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('cicd:live')
def live():
    """Queued/running GitHub runs with their job progress, plus recent dispatches.

    This is what the Run page shows before the workflow's publish step has written any
    ci_runs row, so a launch is visible immediately.
    """
    error = cicd_db.schema_error()
    if error:
        return _not_configured(error)

    wanted = request.args.get('project') or None
    running: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    for project in cicd_db.list_projects(include_disabled=False):
        name = project['project']
        if wanted and name != wanted:
            continue
        try:
            for run in github_api.in_progress_runs(project['repo'], project['workflow_file']):
                jobs = github_api.run_jobs(project['repo'], run['github_run_id'])
                done = sum(1 for j in jobs if j.get('status') == 'completed')
                run.update({
                    'project': name,
                    'workflow': project['workflow_file'],
                    'jobs_total': len(jobs),
                    'jobs_done': done,
                    'runner': next((j.get('runner_name') for j in jobs if j.get('runner_name')), None),
                    # Per-job detail so a caller can attribute in-flight work to a specific
                    # runner (several runners serve one repo) and show how long it has run.
                    'jobs': jobs,
                })
                running.append(run)
        except github_api.GitHubError as e:
            errors[name] = str(e)

    return jsonify({
        'success': True,
        'configured': True,
        'running': running,
        'dispatches': cicd_db.list_dispatches(wanted),
        'errors': errors,
    })


# ─── ingest (workflows that cannot reach the LAN database) ───────────────────

@feature_cicd_bp.route('/ingest', methods=['POST'], strict_slashes=False)
@handle_route_exceptions('cicd:ingest')
def ingest():
    """Record a run and/or its jobs on behalf of a workflow job.

    For GitHub-hosted jobs: Postgres is LAN-only, so a cloud runner cannot use psql the
    way the self-hosted jobs do. Bearer token is CICD_INGEST_TOKEN.

    Body: {"run": {project, run, …}, "jobs": [{project, run, job, status, …}, …]}
    """
    expected = os.environ.get('CICD_INGEST_TOKEN', '').strip()
    if not expected:
        return jsonify({'success': False, 'error': 'CICD_INGEST_TOKEN not set on the server'}), 503
    supplied = (request.headers.get('Authorization') or '').removeprefix('Bearer ').strip()
    if supplied != expected:
        return jsonify({'success': False, 'error': 'invalid ingest token'}), 401

    error = cicd_db.schema_error()
    if error:
        return _not_configured(error)

    payload = request.get_json(silent=True) or {}
    run_row = payload.get('run') or None
    job_rows = payload.get('jobs') or []

    if run_row:
        if not run_row.get('project') or not run_row.get('run'):
            return jsonify({'success': False, 'error': 'run needs project and run'}), 400
        cicd_db.upsert_run(run_row)

    written = 0
    for job in job_rows:
        if not (job.get('project') and job.get('run') and job.get('job') and job.get('status')):
            return jsonify({'success': False, 'error': 'each job needs project, run, job, status'}), 400
        cicd_db.upsert_job(job)
        written += 1

    return jsonify({'success': True, 'run': bool(run_row), 'jobs': written})


# ─── report HTML off disk ────────────────────────────────────────────────────

@feature_cicd_bp.route('/report/<run>/', defaults={'filename': 'index.html'})
@feature_cicd_bp.route('/report/<run>/<path:filename>')
def serve_report(run: str, filename: str):
    """Serve a file from one run's report directory (moved from the core blueprint)."""
    # `run` is a single directory name under CI_REPORTS_DIR — never a path
    if run in ('.', '..') or '/' in run or '\\' in run or '\x00' in run:
        return jsonify({'error': f'Invalid run id {run!r}'}), 400
    reports_root = CI_REPORTS_DIR.resolve()
    run_dir = (reports_root / run).resolve()
    if run_dir.parent != reports_root or not run_dir.exists():
        return jsonify({'error': f'Run {run} not found'}), 404
    if filename.endswith('/') or (run_dir / filename).is_dir():
        filename = filename.rstrip('/') + '/index.html'
    if filename == 'index.html' and not (run_dir / filename).is_file():
        # No run-level page is ever written (each job writes <job>/index.html), yet every
        # ci_runs.report_url points here — Grafana's "open" link and the API sweep both
        # landed on a 404 (2026-09-08). Render the job list from jobs/*.json instead.
        return _run_index_html(run, run_dir), 200, {'Content-Type': 'text/html; charset=utf-8'}
    if not (run_dir / filename).is_file():
        # Distinguish "job wrote no report" from a typo: the job directory exists but the
        # runner never produced index.html (e.g. pytest aborted before writing it).
        hint = ' — the job finished without writing a report' if (run_dir / filename).parent.is_dir() else ''
        return jsonify({'error': f'File {filename} not found in run {run}{hint}'}), 404
    try:
        return send_from_directory(str(run_dir), filename)
    except FileNotFoundError:
        return jsonify({'error': f'File {filename} not found in run {run}'}), 404


def _run_index_html(run: str, run_dir: Path) -> str:
    """Minimal run page: one row per job with its status and a link to its report."""
    import html as _html
    meta = {}
    try:
        meta = json.loads((run_dir / 'meta.json').read_text())
    except Exception:  # noqa: BLE001 - meta is optional
        pass
    rows = []
    for job_file in sorted((run_dir / 'jobs').glob('*.json')) if (run_dir / 'jobs').is_dir() else []:
        try:
            job = json.loads(job_file.read_text())
        except Exception:  # noqa: BLE001 - a malformed job file must not hide the others
            job = {}
        name = job_file.stem
        status = str(job.get('status') or 'unknown')
        color = {'success': '#2e7d32', 'failure': '#c62828'}.get(status, '#757575')
        report = job.get('report')
        link = (f'<a href="{_html.escape(str(report))}/">report</a>'
                if report and (run_dir / str(report) / 'index.html').is_file() else '—')
        rows.append(f'<tr><td>{_html.escape(name)}</td><td>{_html.escape(str(job.get("category") or ""))}</td>'
                    f'<td style="color:{color};font-weight:600">{_html.escape(status)}</td><td>{link}</td></tr>')
    title = f"{_html.escape(str(meta.get('repo') or 'run'))} #{_html.escape(str(run))}"
    subtitle = ' · '.join(_html.escape(str(meta[k])) for k in ('branch', 'sha', 'date') if meta.get(k))
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<title>{title}</title>'
        '<style>body{font-family:system-ui,sans-serif;margin:24px;color:#212121}'
        'table{border-collapse:collapse}td,th{padding:6px 14px;border-bottom:1px solid #e0e0e0;text-align:left}'
        'th{background:#37474f;color:#fff;font-size:.8rem;text-transform:uppercase}</style></head><body>'
        f'<h1 style="margin:0 0 4px">{title}</h1><div style="color:#666;margin-bottom:16px">{subtitle}</div>'
        '<table><thead><tr><th>Job</th><th>Category</th><th>Status</th><th>Report</th></tr></thead>'
        f'<tbody>{"".join(rows) or "<tr><td colspan=4>No jobs recorded</td></tr>"}</tbody></table></body></html>'
    )


def register(app):
    app.register_blueprint(feature_cicd_bp)
