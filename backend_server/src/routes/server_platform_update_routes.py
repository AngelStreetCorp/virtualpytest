"""
Platform update routes (TASK-95, TASK-109): the guided, seven-step rollout behind Configuration -> Platform update.

Admin only (``require_role('admin')``), except ``GET /maintenance`` which every logged-in user may read
(it feeds the global maintenance banner). The operator triggers each step from the page, one by one:

  0 prerequisites   ``check``: runs the prerequisite checks; done when no required check is KO
  1 backup          ``backup``: database schema + the .env of the server, hosts and frontend VM, kept on the server;
                    ``confirm``: the operator says the VMs are snapshotted
  2 bundle          ``build`` (background job) or ``report`` (the page prepared a source with the existing endpoints)
  3 deploy          ``deploy_pull`` / ``confirm_pull``, ``deploy_bundle`` (deploy node), ``report`` / ``rolled_back``;
                    ``/control`` pause|resume|abort, ``/impact``, ``/rollback``, ``/rollback/migrations``, ``/leave-partial`` (G12)
  4 migrations      ``check`` / ``apply``
  5 testing         ``health`` / ``smoke``
  6 close           ``POST /runs/<id>/close``

A run written before the TASK-109 step change is refused with a clear message instead of being migrated.
"""

import os
import hashlib
from flask import Blueprint, Response, jsonify, request, send_file

from backend_server.src.lib.auth_middleware import require_role, require_user_auth
from backend_server.src.lib.platform_update import backup as step_backup
from backend_server.src.lib.platform_update import (
    bundle_jobs, cleanup, db_backup, deployment, frontend_setup, migrations as mig, prerequisites, pull_deploy, restore as env_restore, rollback as pu_rollback, server_key, settings as pu_settings,
)
from backend_server.src.lib.platform_update.runs import (
    BACKUP_STEP, BUNDLE_STEP, DEPLOY_STEP, LAST_STEP, LEGACY_MESSAGE, LegacyRun, MIGRATIONS_STEP, PREREQ_STEP,
    PlatformUpdateError, TESTING_STEP, default_store, is_legacy, require_backup,
)
from backend_server.src.lib.platform_update.windows import default_window_store
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.server_utils import get_host_manager

server_platform_update_bp = Blueprint('server_platform_update', __name__, url_prefix='/server/platform-update')

PROJECT_ROOT = os.getenv('VPT_PROJECT_ROOT', '/opt/virtualpytest')


def _store():
    return default_store()


def _backend():
    return mig.PsycopgBackend()


def _user() -> str:
    return getattr(request, 'user_email', None) or getattr(request, 'user_id', None) or 'unknown'


def _error(exc: PlatformUpdateError):
    return jsonify({'success': False, 'error': str(exc)}), exc.code


def _run_payload(run_id: str):
    store = _store()
    run = pu_rollback.recover(store, bundle_jobs.recover_interrupted(store, store.get(run_id)))
    payload = store.with_log(run)
    payload['legacy'] = is_legacy(run)
    payload['deployment'] = _deployment_view(store, run)
    return {'success': True, 'run': payload}


def _deployment_view(store, run):
    """The deploy step's per-host cards, parsed from the whole run log (the payload log is only the tail)."""
    if is_legacy(run) or run['steps'][DEPLOY_STEP]['state'] == 'pending':
        return None
    try:
        return deployment.build_view(store.log_lines(run['id'], tail=10_000_000))
    except (OSError, FileNotFoundError):
        return None


def _hosts() -> list:
    return list(get_host_manager().get_all_hosts().values())


# -- maintenance banner (any logged-in user) -----------------------------------------------------
@server_platform_update_bp.route('/maintenance', methods=['GET'])
@require_user_auth
@handle_route_exceptions('server_platform_update:maintenance')
def maintenance():
    view = _store().maintenance()
    windows = ([view['window']] if view['window'] else []) + default_window_store().active()
    return jsonify({'success': True, 'active': bool(windows), 'windows': windows, 'notice': view['notice']}), 200


# -- standalone maintenance windows (TASK-97; Settings -> Maintenance, admin only) ---------------
@server_platform_update_bp.route('/windows', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:list_windows')
def list_windows():
    return jsonify({'success': True, 'windows': default_window_store().list_all()}), 200


@server_platform_update_bp.route('/windows', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:create_window')
def create_window():
    data = request.get_json(silent=True) or {}
    try:
        win = default_window_store().create(
            _user(), data.get('window_start'), data.get('window_end'), str(data.get('reason') or ''),
            scope=data.get('scope') or 'devices', device_ids=data.get('device_ids'),
        )
    except PlatformUpdateError as exc:
        return _error(exc)
    return jsonify({'success': True, 'window': win}), 201


@server_platform_update_bp.route('/windows/<window_id>', methods=['PUT'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:update_window')
def update_window(window_id):
    data = request.get_json(silent=True) or {}
    try:
        win = default_window_store().update(
            window_id, data.get('window_start'), data.get('window_end'),
            reason=data.get('reason') if 'reason' in data else None,
            scope=data.get('scope'), device_ids=data.get('device_ids'),
        )
    except PlatformUpdateError as exc:
        return _error(exc)
    return jsonify({'success': True, 'window': win}), 200


@server_platform_update_bp.route('/windows/<window_id>/end', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:end_window')
def end_window(window_id):
    try:
        win = default_window_store().end(window_id)
    except PlatformUpdateError as exc:
        return _error(exc)
    return jsonify({'success': True, 'window': win}), 200


# -- runs ----------------------------------------------------------------------------------------
@server_platform_update_bp.route('/runs', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:list_runs')
def list_runs():
    return jsonify({'success': True, 'runs': _store().list_runs(20)}), 200


@server_platform_update_bp.route('/runs/active', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:active_run')
def active_run():
    store = _store()
    run = store.active()
    return jsonify(_run_payload(run['id']) if run else {'success': True, 'run': None}), 200


@server_platform_update_bp.route('/runs', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:start_run')
def start_run():
    data = request.get_json(silent=True) or {}
    try:
        run = _store().start(
            _user(), data.get('window_start'), data.get('window_end'), data.get('note') or '',
            scope=data.get('scope') or 'platform', device_ids=data.get('device_ids'),
        )
    except PlatformUpdateError as exc:
        return _error(exc)
    return jsonify(_run_payload(run['id'])), 201


@server_platform_update_bp.route('/runs/<run_id>', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:get_run')
def get_run(run_id):
    try:
        return jsonify(_run_payload(run_id)), 200
    except PlatformUpdateError as exc:
        return _error(exc)


@server_platform_update_bp.route('/runs/<run_id>/log', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:run_log')
def run_log(run_id):
    try:
        store = _store()
        store.get(run_id)
        body = '\n'.join(store.log_lines(run_id, tail=100000)) + '\n'
    except PlatformUpdateError as exc:
        return _error(exc)
    return Response(body, mimetype='text/plain', headers={
        'Content-Disposition': f'attachment; filename="platform-update-{run_id}.log"'})


@server_platform_update_bp.route('/runs/<run_id>/close', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:close_run')
def close_run(run_id):
    data = request.get_json(silent=True) or {}
    try:
        _store().close(run_id, str(data.get('status') or ''), str(data.get('message') or ''))
        return jsonify(_run_payload(run_id)), 200
    except PlatformUpdateError as exc:
        return _error(exc)


# -- bundle sources and delivery note (steps 2-3) ------------------------------------------------
@server_platform_update_bp.route('/bundle/sources', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:bundle_sources')
def bundle_sources():
    """What each source can offer right now: release tags, the GitLab of this server and its branches."""
    try:
        return jsonify(bundle_jobs.sources(str(request.args.get('project') or '').strip())), 200
    except PlatformUpdateError as exc:
        return _error(exc)


@server_platform_update_bp.route('/runs/<run_id>/bundle/delivery-note', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:delivery_note')
def delivery_note(run_id):
    """The delivery note the build wrote next to the archive (path taken from the run, never the request)."""
    try:
        bundle = _store().get(run_id)['steps'][BUNDLE_STEP]['data'].get('bundle') or {}
    except PlatformUpdateError as exc:
        return _error(exc)
    name = bundle.get('delivery_note') or ''
    path = os.path.join(bundle.get('dir') or '', os.path.basename(name))
    if not name or not os.path.isfile(path):
        return jsonify({'success': False, 'error': 'no delivery note for this run'}), 404
    with open(path, encoding='utf-8', errors='replace') as fh:
        return Response(fh.read(), mimetype='text/markdown; charset=utf-8')


# -- settings (TASK-128): what used to be typed into the server .env ------------------------------
@server_platform_update_bp.route('/settings', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:get_settings')
def get_settings():
    """The settings with their source (store / env / none). Secrets are only ``set``, never the value."""
    return jsonify({'success': True, 'settings': pu_settings.view(), 'storage': pu_settings.storage()}), 200


@server_platform_update_bp.route('/settings', methods=['PUT'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:put_settings')
def put_settings():
    """Body: ``{key: value}``. An empty string clears the key (back to the .env fallback)."""
    try:
        changed = pu_settings.update(request.get_json(silent=True) or {})
    except PlatformUpdateError as exc:
        return _error(exc)
    return jsonify({'success': True, 'changed': changed, 'settings': pu_settings.view(), 'storage': pu_settings.storage()}), 200


@server_platform_update_bp.route('/settings/db-backup/token', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:db_backup_token')
def db_backup_token():
    """Make (or replace) the agent token and return the one command for the database VM. The token appears only here."""
    token = pu_settings.generate_agent_token()
    address = pu_settings.get('database_agent')
    command = db_backup.setup_command(token, PROJECT_ROOT, db_backup.server_ip(address) if address else '')
    return jsonify({'success': True, 'command': command, 'agent': address, 'settings': pu_settings.view(), 'storage': pu_settings.storage()}), 200


@server_platform_update_bp.route('/settings/db-backup/check', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:db_backup_check')
def db_backup_check():
    """Does the database VM agent accept the stored token (GET /actions/db-backup)."""
    ok, why = db_backup.agent_answers(db_backup.Deps())
    return jsonify({'success': True, 'ok': ok, 'detail': why}), 200


@server_platform_update_bp.route('/settings/ssh-key', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:get_ssh_key')
def get_ssh_key():
    """The server's SSH key for the frontend leg: the public key and the lines to paste on the frontend VM ('' when no key)."""
    return jsonify({'success': True, 'created': False, **server_key.view()}), 200


@server_platform_update_bp.route('/settings/ssh-key', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:create_ssh_key')
def create_ssh_key():
    """Create the key (ssh-keygen ed25519, as the server's user) when missing. An existing key is never overwritten."""
    try:
        created = server_key.create(server_key.key_path())
    except PlatformUpdateError as exc:
        return _error(exc)
    return jsonify({'success': True, 'created': created, **server_key.view()}), 200


@server_platform_update_bp.route('/settings/frontend-setup', methods=['POST'])
@require_user_auth
@require_role('admin')
def frontend_setup_route():
    """Body ``{host, admin_user, password}``: prepare the frontend VM once (TASK-128 G13). The password lives in this call only:
    it is never logged, stored or returned, and this handler has no ``handle_route_exceptions`` so no error path can print it."""
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    password = body.get('password')
    try:
        result = frontend_setup.run(body.get('host'), body.get('admin_user'), password)
    except PlatformUpdateError as exc:
        return _error(exc)
    except Exception as exc:   # masked: the message of an unexpected error could echo the request
        return jsonify({'success': False, 'error': f'Set-up failed ({type(exc).__name__}).'}), 500
    finally:
        password = body['password'] = None
    return jsonify({'success': True, **result, 'settings': pu_settings.view(), 'storage': pu_settings.storage()}), 200


# -- free disk space (TASK-128 G6) -----------------------------------------------------------------
@server_platform_update_bp.route('/cleanup', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:cleanup')
def cleanup_route():
    """Body ``{dry_run: bool}`` (default true: only a literal ``false`` deletes). Deletes, on this server only, update
    saved .env sets, built bundles and ``deploy_bundle.sh`` ``.bak-*`` trees beyond the newest five of each kind."""
    data = request.get_json(silent=True) or {}
    store = _store()
    active = store.active()
    try:
        result = cleanup.run(
            store.dir, PROJECT_ROOT, dry_run=data.get('dry_run') is not False,
            protected_bundles={active['id']} if active else set(),
            busy=lambda: bundle_jobs.is_running('build') or bundle_jobs.is_running('deploy'))
    except PlatformUpdateError as exc:
        return _error(exc)
    return jsonify({'success': True, **result}), 200


# -- restore a saved .env (TASK-128 G7) --------------------------------------------------------------
@server_platform_update_bp.route('/restore', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:restore')
def restore_route():
    """Body ``{folder, item_id, file}`` naming a file the step 1 backup saved. Writes it back (the current file is kept as
    ``.bak-<timestamp>``) on the server, a host or the frontend VM, and returns the restart command. Never restarts anything.
    The database dump is not restorable here."""
    data = request.get_json(silent=True) or {}
    try:
        result = env_restore.restore(_store().dir, data.get('folder'), data.get('item_id'), data.get('file'),
                                     env_restore.Deps(hosts=_hosts, project_root=lambda: PROJECT_ROOT))
    except PlatformUpdateError as exc:
        return _error(exc)
    return jsonify({'success': True, **result}), 200


# -- prerequisites (TASK-101) ----------------------------------------------------------------------
@server_platform_update_bp.route('/prerequisites', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:prerequisites')
def get_prerequisites():
    """Run the prerequisite checks for the chosen sources. Never raises: a broken check is a KO."""
    result = prerequisites.run_all(
        str(request.args.get('core') or 'github'), str(request.args.get('overlay') or 'none'),
        fmt=str(request.args.get('format') or 'zip'))
    return jsonify({'success': True, **result}), 200


# -- what a host downloads (TASK-101) --------------------------------------------------------------
# Hosts authenticate with the service key (X-API-Key, role `service`); admins may fetch too. A user JWT
# of a lower role is refused here even though the global guard let it through.
PING_BODY = 'vpt-update-ping'


@server_platform_update_bp.route('/bundle/ping', methods=['GET'])
@require_user_auth
@require_role('admin', 'service')
@handle_route_exceptions('server_platform_update:bundle_ping')
def bundle_ping():
    """A tiny body + its sha256: the host self-check downloads and verifies it (can this host pull at all?)."""
    return jsonify({'success': True, 'body': PING_BODY, 'sha256': hashlib.sha256(PING_BODY.encode()).hexdigest()}), 200


@server_platform_update_bp.route('/bundle/<run_id>/archive', methods=['GET'])
@require_user_auth
@require_role('admin', 'service')
@handle_route_exceptions('server_platform_update:bundle_archive')
def bundle_archive_download(run_id):
    """The archive step 2 built for this run (path taken from the run record, never from the request)."""
    try:
        step = _store().get(run_id)['steps'][BUNDLE_STEP]
    except PlatformUpdateError as exc:
        return _error(exc)
    bundle = step['data'].get('bundle') or {}
    path = bundle.get('path') or ''
    if step['state'] != 'done' or not path or not os.path.isfile(path):
        return jsonify({'success': False, 'error': 'no archive for this run'}), 404
    return send_file(path, mimetype='application/octet-stream', conditional=True, as_attachment=True,
                     download_name=os.path.basename(path))


# -- pause / abort / impact / roll back (TASK-128 G12) --------------------------------------------
def _server_version_now() -> str:
    return pull_deploy.read_version(pull_deploy.project_root())


@server_platform_update_bp.route('/runs/<run_id>/control', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:control')
def control_deploy(run_id):
    """Body {action: pause|resume|abort}. Only the pull deploy honours it, and only at its safe points (between machines)."""
    store = _store()
    action = str((request.get_json(silent=True) or {}).get('action') or '')
    try:
        step = store.get(run_id)['steps'][DEPLOY_STEP]
        job = step['data'].get('job') or {}
        if step['state'] != 'running' or job.get('mode') != 'pull' or job.get('state') not in ('running', 'paused'):
            raise PlatformUpdateError('no pull deploy is running that can be paused or aborted '
                                      '(a server already updated waits for its confirmation: roll back instead)')
        store.request_control(run_id, action, _user())
        return jsonify(_run_payload(run_id)), 200
    except PlatformUpdateError as exc:
        return _error(exc)


@server_platform_update_bp.route('/runs/<run_id>/impact', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:impact')
def deploy_impact(run_id):
    try:
        run = pu_rollback.recover(_store(), bundle_jobs.recover_interrupted(_store(), _store().get(run_id)))
        return jsonify({'success': True, 'impact': pu_rollback.impact(run, _hosts(), _server_version_now())}), 200
    except PlatformUpdateError as exc:
        return _error(exc)


@server_platform_update_bp.route('/runs/<run_id>/rollback', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:rollback')
def rollback_deploy(run_id):
    """Body {confirm: true} starts the roll back of the machines (hosts newest first, frontend VM, server last; hosts through
    call_host to /host/system/rollbackBundle). Body {action: 'confirm_restart'} confirms the server after its restart."""
    store = _store()
    data = request.get_json(silent=True) or {}
    log = lambda line: store.log(run_id, line, DEPLOY_STEP)  # noqa: E731
    try:
        if is_legacy(store.get(run_id)):
            raise LegacyRun(LEGACY_MESSAGE)
        if data.get('action') == 'confirm_restart':
            pu_rollback.confirm_rollback(store, run_id, log)
        else:
            if data.get('confirm') is not True:
                raise PlatformUpdateError('confirmation required')
            pu_rollback.run_rollback(store, run_id, pull_deploy.Env(), _user())
        return jsonify(_run_payload(run_id)), 200
    except PlatformUpdateError as exc:
        return _error(exc)


@server_platform_update_bp.route('/runs/<run_id>/rollback/migrations', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:rollback_migrations')
def rollback_migrations_route(run_id):
    """Second confirm: body {confirm: true, filenames: [...]} = the applied files, newest first, exactly as the impact view lists them."""
    store = _store()
    data = request.get_json(silent=True) or {}
    names = data.get('filenames') if isinstance(data.get('filenames'), list) else []
    try:
        pu_rollback.rollback_migrations(store, run_id, _backend(), [str(n) for n in names], data.get('confirm'), _user(),
                                        log=lambda line: store.log(run_id, line, MIGRATIONS_STEP))
        return jsonify(_run_payload(run_id)), 200
    except PlatformUpdateError as exc:
        return _error(exc)


@server_platform_update_bp.route('/runs/<run_id>/leave-partial', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:leave_partial')
def leave_partial_route(run_id):
    store = _store()
    try:
        pu_rollback.leave_partial(store, run_id, (request.get_json(silent=True) or {}).get('confirm'), _user(), _hosts(), _server_version_now())
        return jsonify(_run_payload(run_id)), 200
    except PlatformUpdateError as exc:
        return _error(exc)


# -- steps ---------------------------------------------------------------------------------------
@server_platform_update_bp.route('/runs/<run_id>/steps/<int:index>', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:run_step')
def run_step(run_id, index):
    data = request.get_json(silent=True) or {}
    action = str(data.get('action') or '')
    store = _store()
    log = lambda line: store.log(run_id, line, index)  # noqa: E731
    try:
        if is_legacy(store.get(run_id)):
            raise LegacyRun(LEGACY_MESSAGE)
        if index == LAST_STEP or not 0 <= index <= LAST_STEP:
            raise PlatformUpdateError('use /close for the last step' if index == LAST_STEP else 'unknown step')
        handler = _HANDLERS.get((index, action))
        if handler is None:
            raise PlatformUpdateError(f'unknown action "{action}" for step {index}')
        if index == DEPLOY_STEP and action in ('deploy_pull', 'deploy_bundle', 'begin', 'report'):
            require_backup(store.get(run_id))      # TASK-128 G12: no deploy without this run's step 1 backup
        handler(store, run_id, index, data, log)
        return jsonify(_run_payload(run_id)), 200
    except PlatformUpdateError as exc:
        return _error(exc)


def _ensure_running(store, run_id, index):
    step = store.get(run_id)['steps'][index]
    if step['state'] != 'running':
        store.begin_step(run_id, index)


def _step0_check(store, run_id, index, data, log):
    """Step 0: run the prerequisite checks for the chosen sources. Done when no required check is KO."""
    store.begin_step(run_id, index)
    core = str(data.get('core') or 'github')
    overlay = str(data.get('overlay') or 'none')
    try:
        result = prerequisites.run_all(core, overlay)
    except Exception as exc:
        store.finish_step(run_id, index, False, f'checks could not run: {type(exc).__name__}')
        return
    for c in result['checks']:
        log(f'{c["title"]}: {c["status"].upper()}{"" if c["required"] or c["status"] == "na" else " (warning only)"}')
    bad = [c['title'] for c in result['checks'] if c['required'] and c['status'] == 'ko']
    store.finish_step(run_id, index, result['ok'],
                      f'{result["passed"]}/{result["total"]} OK' if result['ok'] else 'KO: ' + '; '.join(bad),
                      {'prerequisites': result, 'core': core, 'overlay': overlay})


def _step1_backup(store, run_id, index, data, log):
    """Step 1: save the schema and the .env files. The step stays open until the operator confirms the snapshots."""
    _ensure_running(store, run_id, index)
    try:
        result = step_backup.run_backup(store.dir, run_id, log=log)
    except PlatformUpdateError as exc:
        store.finish_step(run_id, index, False, str(exc))
        raise
    if not result['ok']:
        bad = [i['label'] for i in result['items'] if i['status'] == 'ko']
        store.finish_step(run_id, index, False, 'KO: ' + '; '.join(bad), {'backup': result})
        return
    store.set_data(run_id, index, {'backup': result})
    log(f'Backup saved in {result["path"]} (kept on the server, no download)')


def _step1_confirm(store, run_id, index, data, log):
    step = store.get(run_id)['steps'][index]
    if step['state'] != 'running' or not (step['data'].get('backup') or {}).get('ok'):
        raise PlatformUpdateError('back up first')
    if data.get('snapshotted') is not True:
        raise PlatformUpdateError('confirm that the VMs are snapshotted')
    log('The operator confirmed the VM snapshots')
    store.finish_step(run_id, index, True, step['data']['backup']['folder'], {'snapshotted': True})


def _step_report(store, run_id, index, data, log):
    """Steps 2 and 3: the page ran the work with the existing endpoints and reports the outcome."""
    _ensure_running(store, run_id, index)
    if index == BUNDLE_STEP:
        version = str(data.get('version') or '').strip()
        if data.get('ok') is True and not version:
            raise PlatformUpdateError('version is required')
        extra = {'source': str(data.get('source') or ''), 'version': version,
                 'overlay': str(data.get('overlay') or '')}
    else:
        extra = {'targets': data.get('targets') if isinstance(data.get('targets'), list) else []}
        for t in extra['targets']:
            log(f'{t.get("target")}: {"ok" if t.get("success") else "FAILED"} {t.get("message") or t.get("error") or ""}')
    store.finish_step(run_id, index, data.get('ok') is True, str(data.get('detail') or ''), extra)


def _step2_build(store, run_id, index, data, log):
    """Step 2, bundle from any source: customer_bundle.py build as a background job (bundle_jobs)."""
    bundle_jobs.start_build(store, run_id, data)


def _step3_deploy_bundle(store, run_id, index, data, log):
    """Step 3, deploy node path: deploy_bundle.sh on the archive step 2 built, as a background job."""
    bundle_jobs.start_deploy(store, run_id, data)


def _step3_deploy_pull(store, run_id, index, data, log):
    """Step 3, pull mode (TASK-101): frontend over SSH, hosts pull the bundle, the server last. Gated on the prerequisites."""
    pull_deploy.start(store, run_id, data)


def _step3_confirm_pull(store, run_id, index, data, log):
    pull_deploy.confirm(store, run_id, log)


def _step3_rolled_back(store, run_id, index, data, log):
    for t in data.get('targets') if isinstance(data.get('targets'), list) else []:
        log(f'rollback {t.get("target")}: {"ok" if t.get("success") else "FAILED"} {t.get("message") or t.get("error") or ""}')
    store.mark_failed(run_id, index, str(data.get('detail') or 'rolled back'))


def _step4_check(store, run_id, index, data, log):
    state = mig.status(_backend())
    if state['tracker'] == 'missing':
        raise PlatformUpdateError('migration tracker missing: create it first (Migrations -> Create tracker)')
    log(f'{len(state["pending"])} pending of {state["total"]} migrations')
    if state['pending']:
        raise PlatformUpdateError(f'{len(state["pending"])} migrations pending: review and apply them')
    store.begin_step(run_id, index)
    store.finish_step(run_id, index, True, 'no pending migrations', {'applied': []})


def _step4_apply(store, run_id, index, data, log):
    _ensure_running(store, run_id, index)
    names = data.get('filenames') if isinstance(data.get('filenames'), list) else []
    try:
        done = mig.apply(_backend(), names, data.get('confirm'), _user(), log=log)
    except PlatformUpdateError as exc:
        store.finish_step(run_id, index, False, str(exc))
        raise
    remaining = mig.status(_backend())['pending']
    if remaining:
        # Keep the step open: more files are pending, the operator applies them in another round.
        log(f'{len(done)} applied, {len(remaining)} still pending')
        previous = store.get(run_id)['steps'][index]['data'].get('applied', [])
        store.set_data(run_id, index, {'applied': previous + done})
        return
    previous = store.get(run_id)['steps'][index]['data'].get('applied', [])
    store.finish_step(run_id, index, True, f'{len(previous) + len(done)} migrations applied', {'applied': previous + done})


def _call_host(host, endpoint, method='POST', data=None, timeout=60):
    from shared.src.lib.utils.build_url_utils import call_host
    return call_host(host, endpoint, method=method, data=data, timeout=timeout)


def _step5_health(store, run_id, index, data, log):
    _ensure_running(store, run_id, index)
    hosts = []
    for host in _hosts():
        body, status = _call_host(host, '/host/system/health', method='GET', timeout=15)
        ok = status == 200
        hosts.append({'host': host.get('host_name', '?'), 'ok': ok, 'detail': '' if ok else f'status {status}'})
        log(f'{hosts[-1]["host"]}: health {"ok" if ok else "FAILED"} {hosts[-1]["detail"]}')
    log('Server: responding')
    bad = [h['host'] for h in hosts if not h['ok']]
    if bad:
        store.finish_step(run_id, index, False, f'unhealthy hosts: {", ".join(bad)}',
                          {'health_ok': False, 'health_hosts': hosts})
    else:
        # Stays running: the step is done only when the smoke script has passed too.
        store.set_data(run_id, index, {'health_ok': True, 'health_hosts': hosts})
        log('Health ok - waiting for the smoke script result')


def _step5_smoke(store, run_id, index, data, log):
    step = store.get(run_id)['steps'][index]
    if not step['data'].get('health_ok'):
        raise PlatformUpdateError('run the health check first and fix unhealthy hosts')
    if step['state'] != 'running':
        store.begin_step(run_id, index)
    ok = data.get('ok') is True
    log(f'Smoke script {data.get("script_name") or "?"}: {"ok" if ok else "FAILED"} (task {data.get("task_id") or "?"})')
    store.finish_step(run_id, index, ok, str(data.get('detail') or ''),
                      {'smoke': {'ok': ok, 'script_name': data.get('script_name'), 'task_id': data.get('task_id')}})


_HANDLERS = {
    (PREREQ_STEP, 'check'): _step0_check,
    (BACKUP_STEP, 'backup'): _step1_backup,
    (BACKUP_STEP, 'confirm'): _step1_confirm,
    (BUNDLE_STEP, 'report'): _step_report,
    (BUNDLE_STEP, 'build'): _step2_build,
    (DEPLOY_STEP, 'deploy_bundle'): _step3_deploy_bundle,
    (DEPLOY_STEP, 'deploy_pull'): _step3_deploy_pull,
    (DEPLOY_STEP, 'confirm_pull'): _step3_confirm_pull,
    (DEPLOY_STEP, 'begin'): lambda s, r, i, d, l: s.begin_step(r, i),
    (DEPLOY_STEP, 'report'): _step_report,
    (DEPLOY_STEP, 'rolled_back'): _step3_rolled_back,
    (MIGRATIONS_STEP, 'check'): _step4_check,
    (MIGRATIONS_STEP, 'apply'): _step4_apply,
    (TESTING_STEP, 'health'): _step5_health,
    (TESTING_STEP, 'smoke'): _step5_smoke,
}


# -- migrations (outside a run: tracker + baseline are one-time set-up) ---------------------------
@server_platform_update_bp.route('/migrations', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:migrations')
def migrations_status():
    try:
        return jsonify({'success': True, **mig.status(_backend())}), 200
    except PlatformUpdateError as exc:
        return _error(exc)


def _run_log_fn():
    store = _store()
    active = store.active()
    return (lambda line: store.log(active['id'], line, MIGRATIONS_STEP)) if active else (lambda _line: None)


@server_platform_update_bp.route('/migrations/tracker', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:migrations_tracker')
def migrations_tracker():
    data = request.get_json(silent=True) or {}
    if data.get('confirm') is not True:
        return jsonify({'success': False, 'error': 'confirmation required'}), 400
    try:
        mig.install_tracker(_backend(), _user(), log=_run_log_fn())
        return jsonify({'success': True, **mig.status(_backend())}), 200
    except PlatformUpdateError as exc:
        return _error(exc)


@server_platform_update_bp.route('/migrations/baseline', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_platform_update:migrations_baseline')
def migrations_baseline():
    data = request.get_json(silent=True) or {}
    try:
        marked = mig.baseline(_backend(), str(data.get('up_to') or ''), _user(), data.get('confirm') is True,
                              log=_run_log_fn())
        return jsonify({'success': True, 'marked': marked, **mig.status(_backend())}), 200
    except PlatformUpdateError as exc:
        return _error(exc)
