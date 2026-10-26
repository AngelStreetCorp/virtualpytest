"""
GitLab feature — backend_server part.

Registered by shared/src/lib/utils/features.py when the feature is enabled
(docs/technical/FEATURES.md). Everything lives under /server/gitlab.

Separate from the cicd feature on purpose: cicd collects GitHub Actions results and carries
the CI reports page, the Grafana dashboard and the `cicd` schema, none of which a customer
running its own GitLab needs. This feature is the GitLab side only, so it can be enabled (or
left off) independently of cicd — which matters for a customer whose DISABLED_FEATURES
already lists cicd.

Permissions follow the other plugins: `plugins.gitlab:view` for reads, `plugins.gitlab:manage`
for configuring an instance or changing the selected project — same shape as
`plugins.jira:view/:manage` in the core integrations routes. Triggering a pipeline additionally
requires a signed-in user, because it is a side effect on the customer's CI.

This feature is a GitLab READER, and nothing else. Building a delivery bundle used to live here as
`/package/*` driven by a panel on the page; packaging is a rollout concern and moved to
`setup/proxmox/node/lib/customer_bundle.py` (owner decision, 2026-10-13), so this module exposes no
packaging route at all. Do not add one back without asking.

Every GitLabError becomes a 502 (or its own 4xx when GitLab says 4xx) carrying GitLab's reason
rather than a stack trace: gitlab_api raises GitLabError with a readable message on purpose.
"""

from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from backend_server.src.lib.auth_middleware import require_permission, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

from features.gitlab.lib import gitlab_api, instances
from features.gitlab.lib.gitlab_api import GitLabError

feature_gitlab_bp = Blueprint('feature_gitlab', __name__, url_prefix='/server/gitlab')

#: How many projects get a per-project health probe on /projects. Each one costs an extra API
#: call, so the list is capped rather than turning a page load into N sequential requests.
HEALTH_PROJECT_LIMIT = 25


def _not_configured(reason: str):
    """Single shape the page renders as "GitLab not configured: …"."""
    return jsonify({'success': False, 'configured': False, 'error': reason})


def _bad_request(exc: GitLabError):
    """GitLab said no — pass its reason through instead of a generic 500.

    A 400 from the trigger endpoint is almost always the caller's mistake (unknown ref, an
    input the CI file does not declare), so its status is preserved instead of flattened.
    """
    status = exc.status if 400 <= (exc.status or 0) < 500 else 502
    return jsonify({'success': False, 'error': str(exc)}), status


def _instance(instance_id: str = None):
    """(api, tok) for a configured instance, or None when there is nothing to talk to."""
    inst = instances.get(instance_id or request.args.get('instance'))
    if not inst or not inst.get('token'):
        return None
    return inst['base_url'], inst['token']


def _project_or_400():
    """The `project` query argument, or a 400 when it is missing.

    The project is a query argument and NOT a path segment, on purpose. Every GitLab project is
    namespaced (`group/project`), and Flask's default string converter does not match a path
    segment carrying an encoded slash — so `/projects/root%2Fvpt-customer/tree` matches no route,
    falls through to the auto_proxy catch-all, and comes back as a 400 about `host_name`, a
    parameter this feature has never heard of. The 400 said nothing about the real problem, and
    it hit every namespaced project, i.e. all of them.
    """
    project = (request.args.get('project') or '').strip()
    if not project:
        return None, (jsonify({'success': False, 'error': 'project is required'}), 400)
    return project, None


# ─── instances (the "set it up" form) ────────────────────────────────────────

@feature_gitlab_bp.route('/instances', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:list_instances')
def list_instances():
    return jsonify({
        'success': True,
        'configured': bool(instances.effective()),
        'instances': [instances.public(i) for i in instances.effective()],
    })


@feature_gitlab_bp.route('/instances', methods=['POST'], strict_slashes=False)
@require_permission('plugins.gitlab:manage')
@handle_route_exceptions('gitlab:save_instance')
def save_instance():
    payload = request.get_json(silent=True) or {}
    base_url = (payload.get('base_url') or '').strip()
    token = (payload.get('token') or '').strip()
    if not base_url:
        return jsonify({'success': False, 'error': 'base_url is required'}), 400
    if not token and not instances.get(payload.get('id')):
        return jsonify({'success': False, 'error': 'token is required for a new instance'}), 400

    saved = instances.upsert({**payload, 'base_url': base_url, 'token': token})
    if not saved:
        return jsonify({'success': False, 'error': 'could not write the instance config'}), 500

    # Prove the pair works before the operator leaves the form believing it does.
    try:
        version = gitlab_api.version(api=saved['base_url'], tok=saved['token'])
    except GitLabError as exc:
        return jsonify({
            'success': False,
            'saved': True,
            'instance': instances.public(saved),
            'error': str(exc),
        }), 502
    return jsonify({'success': True, 'instance': instances.public(saved),
                    'version': version.get('version')})


@feature_gitlab_bp.route('/instances/<instance_id>', methods=['DELETE'], strict_slashes=False)
@require_permission('plugins.gitlab:manage')
@handle_route_exceptions('gitlab:delete_instance')
def delete_instance(instance_id: str):
    return jsonify({'success': instances.delete(instance_id)})


@feature_gitlab_bp.route('/instances/<instance_id>/project', methods=['PUT'], strict_slashes=False)
@require_permission('plugins.gitlab:manage')
@handle_route_exceptions('gitlab:select_project')
def select_project(instance_id: str):
    """Remember the operator's pick so the page opens straight on it next time."""
    payload = request.get_json(silent=True) or {}
    project = (payload.get('project') or '').strip()
    if not project:
        return jsonify({'success': False, 'error': 'project is required'}), 400
    saved = instances.select_project(instance_id, project, payload.get('ref') or '')
    if not saved:
        return jsonify({'success': False, 'error': 'unknown instance'}), 404
    return jsonify({'success': True, 'instance': instances.public(saved)})


# ─── config / health ─────────────────────────────────────────────────────────

@feature_gitlab_bp.route('/health', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:health')
def health():
    """What the feature can currently do — drives the page's disabled states.

    Probes the instance rather than only reporting that a token exists: base URL and token
    are two independent ways to be wrong, and an operator needs to know which.
    """
    configured = instances.effective()
    out: Dict[str, Any] = {
        'success': True,
        'configured': bool(configured),
        'instances': [instances.public(i) for i in configured],
    }
    if not configured:
        out['error'] = 'No GitLab instance configured'
        return jsonify(out)

    inst = configured[0]
    out['base_url'] = inst['base_url']
    out['token'] = bool(inst.get('token'))
    try:
        version = gitlab_api.version(api=inst['base_url'], tok=inst['token'])
        out['version'] = version.get('version')
        out['reachable'] = True
    except GitLabError as exc:
        out['reachable'] = False
        out['error'] = str(exc)
    return jsonify(out)


# ─── projects ────────────────────────────────────────────────────────────────

@feature_gitlab_bp.route('/projects', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:list_projects')
def list_projects():
    """Projects visible to the token, each with its latest pipeline as the health signal.

    `?health=0` skips the per-project probe when the caller only wants the list.
    """
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    api, tok = target
    try:
        rows = gitlab_api.projects(search=request.args.get('search') or None, api=api, tok=tok)
    except GitLabError as exc:
        return _bad_request(exc)

    with_health = request.args.get('health', '1') != '0'
    out: List[Dict[str, Any]] = []
    for row in rows[:HEALTH_PROJECT_LIMIT]:
        entry = {
            'id': row.get('id'),
            'name': row.get('name'),
            'path': row.get('path'),
            'path_with_namespace': row.get('path_with_namespace'),
            'default_branch': row.get('default_branch'),
            'web_url': row.get('web_url'),
            'last_activity_at': row.get('last_activity_at'),
            'open_issues_count': row.get('open_issues_count'),
        }
        if with_health:
            try:
                pipelines = gitlab_api.pipeline_runs(row.get('id'), per_page=1, api=api, tok=tok)
            except GitLabError:
                pipelines = []
            entry['last_pipeline'] = pipelines[0] if pipelines else None
        out.append(entry)

    return jsonify({'success': True, 'projects': out, 'truncated': len(rows) > HEALTH_PROJECT_LIMIT})


@feature_gitlab_bp.route('/project', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:get_project')
def get_project():
    project, err = _project_or_400()
    if err:
        return err
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    try:
        return jsonify({'success': True,
                        'project': gitlab_api.resolve_project(project, api=target[0], tok=target[1])})
    except GitLabError as exc:
        return _bad_request(exc)


@feature_gitlab_bp.route('/project/branches', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:branches')
def branches():
    project, err = _project_or_400()
    if err:
        return err
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    try:
        names = gitlab_api.branches(project, per_page=100, api=target[0], tok=target[1])
        # branches() now returns names only (test contract: drop entries without `name`).
        # The frontend GitLabPage renders commit dates next to each branch, so wrap each name
        # as {name, commit: null} — the commit metadata isn't returned here. The frontend's
        # ago(null) renders the same dash the empty state already shows.
        return jsonify({'success': True,
                        'branches': [{'name': n, 'commit': None} for n in names]})
    except GitLabError as exc:
        return _bad_request(exc)


@feature_gitlab_bp.route('/project/overview', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:overview')
def overview():
    project, err = _project_or_400()
    if err:
        return err
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    try:
        return jsonify({'success': True, 'overview': gitlab_api.overview(
            project, ref=request.args.get('ref') or None, api=target[0], tok=target[1])})
    except GitLabError as exc:
        return _bad_request(exc)


# ─── repository ──────────────────────────────────────────────────────────────

@feature_gitlab_bp.route('/project/tree', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:tree')
def tree():
    project, err = _project_or_400()
    if err:
        return err
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    try:
        entries = gitlab_api.repository_tree(
            project, ref=request.args.get('ref') or None,
            path=request.args.get('path') or '', api=target[0], tok=target[1])
        if request.args.get('with_commits') in ('1', 'true'):
            commits = gitlab_api.last_commits(
                project, request.args.get('ref') or None, [e['path'] for e in entries],
                api=target[0], tok=target[1])
            for e in entries:
                e['last_commit'] = commits.get(e['path'])
        return jsonify({'success': True, 'entries': entries})
    except GitLabError as exc:
        return _bad_request(exc)


@feature_gitlab_bp.route('/project/readme', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:readme')
def readme():
    project, err = _project_or_400()
    if err:
        return err
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    try:
        doc = gitlab_api.readme(project, ref=request.args.get('ref') or None,
                                api=target[0], tok=target[1])
        return jsonify({'success': True, 'readme': doc})
    except GitLabError as exc:
        return _bad_request(exc)


@feature_gitlab_bp.route('/project/file', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:file')
def repository_file():
    project, err = _project_or_400()
    if err:
        return err
    path = request.args.get('path') or ''
    if not path:
        return jsonify({'success': False, 'error': 'path is required'}), 400
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    try:
        doc = gitlab_api.file_content(project, path, ref=request.args.get('ref') or None,
                                      api=target[0], tok=target[1])
        return jsonify({'success': True, 'file': doc})
    except GitLabError as exc:
        return _bad_request(exc)


# ─── pipelines ───────────────────────────────────────────────────────────────

@feature_gitlab_bp.route('/project/pipelines', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:pipelines')
def pipelines():
    project, err = _project_or_400()
    if err:
        return err
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    try:
        runs = gitlab_api.pipeline_runs(
            project, ref=request.args.get('ref') or None,
            status=request.args.get('status') or None, api=target[0], tok=target[1])
        return jsonify({'success': True, 'pipelines': runs})
    except GitLabError as exc:
        return _bad_request(exc)


@feature_gitlab_bp.route('/project/pipelines/jobs', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:pipeline_jobs')
def pipeline_jobs():
    project, err = _project_or_400()
    if err:
        return err
    try:
        pipeline_id = int(request.args.get('pipeline_id') or 0)
    except ValueError:
        return jsonify({'success': False, 'error': 'pipeline_id must be a number'}), 400
    if not pipeline_id:
        return jsonify({'success': False, 'error': 'pipeline_id is required'}), 400
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    try:
        return jsonify({'success': True, 'jobs': gitlab_api.run_jobs(project, pipeline_id,
                                                                    api=target[0], tok=target[1])})
    except GitLabError as exc:
        return _bad_request(exc)


@feature_gitlab_bp.route('/runners', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:runners')
def runners():
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    try:
        return jsonify({'success': True, 'runners': gitlab_api.runners(api=target[0], tok=target[1])})
    except GitLabError as exc:
        return _bad_request(exc)


# ─── actions ─────────────────────────────────────────────────────────────────

@feature_gitlab_bp.route('/project/trigger', methods=['POST'], strict_slashes=False)
@require_user_auth
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:trigger')
def trigger():
    """Start a pipeline on the customer's GitLab.

    GitLab CE 19.4 cannot take parameters here — a bare `ref` is the only form it accepts (see
    lib/gitlab_api.py::trigger_pipeline) — so `inputs` is only forwarded when the caller sends it.
    """
    project, err = _project_or_400()
    if err:
        return err
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    payload = request.get_json(silent=True) or {}
    ref = payload.get('ref') or request.args.get('ref') or 'main'
    try:
        pipeline = gitlab_api.trigger_pipeline(project, ref, payload.get('inputs'),
                                               api=target[0], tok=target[1])
        return jsonify({'success': True, 'pipeline': pipeline})
    except GitLabError as exc:
        return _bad_request(exc)


@feature_gitlab_bp.route('/project/jobs/trace', methods=['GET'], strict_slashes=False)
@require_permission('plugins.gitlab:view')
@handle_route_exceptions('gitlab:job_trace')
def job_trace():
    project, err = _project_or_400()
    if err:
        return err
    try:
        job_id = int(request.args.get('job_id') or 0)
    except ValueError:
        return jsonify({'success': False, 'error': 'job_id must be a number'}), 400
    if not job_id:
        return jsonify({'success': False, 'error': 'job_id is required'}), 400
    target = _instance()
    if not target:
        return _not_configured('No GitLab instance configured')
    try:
        return jsonify({'success': True, 'trace': gitlab_api.job_trace(project, job_id,
                                                                       api=target[0], tok=target[1])})
    except GitLabError as exc:
        return _bad_request(exc)


def register(app):
    app.register_blueprint(feature_gitlab_bp)
