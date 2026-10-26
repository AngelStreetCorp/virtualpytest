"""
Impact view and roll back of Platform update step 3 (TASK-128 G12).

The deploy (``pull_deploy.py``) writes into the step data which machines it touched (``updated``: role, name, and the backup
that machine can be restored from) and the versions each ran before (``before_versions``). From that this module:

  ``impact``              per machine: new / rolled back / untouched / failed, before and now; the migrations applied in this run.
  ``run_rollback``        puts every touched machine back, in this order: hosts (newest first), then the frontend VM, then the
                          server itself LAST (its restart ends the job; ``confirm_rollback`` checks it afterwards, like
                          ``pull_deploy.confirm``). It stops at the first machine that fails; running it again skips the
                          machines already done.
  ``rollback_migrations`` the ``_rollback.sql`` of the migrations applied in this run, newest first, only after a second explicit
                          confirm of the exact list. A migration with no rollback file STOPS it and the step 1 database dump
                          restore command is shown (the dump is never restored automatically).
  ``leave_partial``       the explicit choice to keep a mixed fleet; closes the step as failed.

What a roll back restores is code and the units reconciled from it. Not undone: data the new code wrote, ``.env`` files (never
touched by an update), the database unless its migrations have rollback files, and anything done on a machine by hand.
The client never supplies a backup id or a path: the ids come from the run JSON, the host validates them again.
"""

import re
import shlex
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from shared.src.lib.utils import bundle_archive as ba
from shared.src.lib.utils import update_privileges as priv

from . import before_versions, bundle_jobs, frontend_ssh, prerequisites, pull_deploy
from .migrations import DEFAULT_DIR, Backend
from .pull_deploy import APPLY_TIMEOUT, Env, deploy_frontend_local, read_version
from .runs import BACKUP_STEP, DEPLOY_STEP, MIGRATIONS_STEP, PlatformUpdateError, RunStore

SERVER_BACKUP_ID_RE = re.compile(r'^\d{8}_\d{6}(_\d{6})?$')
ROLE_ORDER = {'host': 0, 'frontend': 1, 'server': 2}


class RollbackError(PlatformUpdateError):
    code = 409


def _step(store: RunStore, run_id: str, index: int = DEPLOY_STEP) -> Dict[str, Any]:
    return store.get(run_id)['steps'][index]


def rollback_state(store: RunStore, run_id: str) -> Dict[str, Any]:
    return dict(_step(store, run_id)['data'].get('rollback') or {})


def _save_rollback(store: RunStore, run_id: str, rb: Dict[str, Any]) -> None:
    store.set_data(run_id, DEPLOY_STEP, {'rollback': rb})


def _action(rb: Dict[str, Any], role: str, name: str) -> Optional[Dict[str, Any]]:
    return next((a for a in rb.get('actions') or [] if a['role'] == role and a['name'] == name), None)


# -- plan --------------------------------------------------------------------------------------------
def plan(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The machines to put back, in order: hosts newest first, the frontend VM, the server last. Only machines with a
    recorded backup (a machine whose backup was never made was never changed)."""
    updated = [u for u in run['steps'][DEPLOY_STEP]['data'].get('updated') or [] if u.get('backup')]
    indexed = list(enumerate(updated))
    indexed.sort(key=lambda p: (ROLE_ORDER.get(p[1]['role'], 9), -p[0]))     # same role: newest (last recorded) first
    return [u for _i, u in indexed]


def can_rollback(run: Dict[str, Any]) -> bool:
    step = run['steps'][DEPLOY_STEP]
    job = step['data'].get('job') or {}
    if run['status'] != 'active' or step['state'] in ('pending', 'waiting'):
        return False
    if step['state'] == 'running' and job.get('state') != 'awaiting_confirmation':
        return False
    rb = step['data'].get('rollback') or {}
    if rb.get('state') in ('running', 'awaiting_confirmation', 'done'):
        return False
    return bool(plan(run))


# -- impact ------------------------------------------------------------------------------------------
def migration_plan(run: Dict[str, Any], directory: Path = DEFAULT_DIR) -> Dict[str, Any]:
    data = run['steps'][MIGRATIONS_STEP]['data']
    rolled = set(data.get('rolled_back') or [])
    applied = [f for f in data.get('applied') or [] if f not in rolled]
    items = []
    for name in reversed(applied):
        rb_name = name[:-4] + '_rollback.sql' if name.endswith('.sql') else name + '_rollback.sql'
        items.append({'file': name, 'rollback_file': rb_name, 'has_rollback': (Path(directory) / rb_name).is_file()})
    dump = next((i for i in (run['steps'][BACKUP_STEP]['data'].get('backup') or {}).get('items') or []
                 if i.get('id') == 'database'), {})
    return {'applied': applied, 'rolled_back': sorted(rolled), 'plan': items,
            'restore_command': dump.get('restore_command') or '', 'needs_dump_restore': bool(data.get('needs_dump_restore'))}


def impact(run: Dict[str, Any], hosts_now: List[dict], server_now: str, directory: Path = DEFAULT_DIR) -> Dict[str, Any]:
    step = run['steps'][DEPLOY_STEP]
    data = step['data']
    before = data.get('versions_before') or {}
    expected = data.get('expected_version') or ''
    updated = data.get('updated') or []
    rb = data.get('rollback') or {}
    now_hosts = {str(h.get('host_name') or h.get('name') or '?'): before_versions._clean(h.get('deployed_version')) for h in hosts_now}

    def row(role: str, name: str, was: str, current: Optional[str]) -> Dict[str, Any]:
        u = next((x for x in updated if x['role'] == role and x['name'] == name), None)
        done_back = (_action(rb, role, name) or {}).get('state') == 'ok'
        state = 'rolled_back' if done_back else 'untouched' if not u else 'new' if u.get('ok') else 'failed'
        shown = current or (expected if state in ('new', 'failed') else was)
        return {'role': role, 'name': name, 'before': was or 'unknown', 'now': shown or 'unknown', 'state': state,
                'has_backup': bool(u and u.get('backup'))}

    machines: List[Dict[str, Any]] = []
    for u in updated:
        if u['role'] == 'frontend':
            machines.append(row('frontend', u['name'], before.get('frontend') or '', None))
    for name, was in (before.get('hosts') or {}).items():
        machines.append(row('host', name, was, now_hosts.get(name)))
    for u in updated:
        if u['role'] == 'server':
            machines.append(row('server', u['name'], before.get('server') or '', server_now))
    if not any(m['role'] == 'server' for m in machines) and before.get('server'):
        machines.append(row('server', 'server', before['server'], server_now))
    new = [m for m in machines if m['state'] in ('new', 'failed')]
    old = [m for m in machines if m['state'] in ('untouched', 'rolled_back')]
    mixed = bool(new) and bool(old)
    summary = '; '.join(f'{m["name"]}: {m["before"]} -> {m["now"]}' for m in new)
    summary += ('. Still on the old version: ' + ', '.join(f'{m["name"]} ({m["now"]})' for m in old)) if mixed else ''
    return {
        'machines': machines, 'migrations': migration_plan(run, directory), 'expected_version': expected,
        'mixed': mixed, 'mixed_summary': summary, 'aborted': bool(data.get('aborted')),
        'can_rollback': can_rollback(run), 'rollback': rb or None, 'partial': data.get('partial'),
        'rollback_order': [{'role': t['role'], 'name': t['name']} for t in plan(run)],
    }


# -- machines ----------------------------------------------------------------------------------------
def _wait_health(env: Env, host: dict, wait_seconds: int = 120) -> None:
    env.sleep(6)
    deadline = time.monotonic() + wait_seconds
    while True:
        _b, status = env.call_host(host, '/host/system/health', 'GET', None, 5)
        if status == 200:
            return
        if time.monotonic() > deadline:
            raise RollbackError(f'the host did not come back {wait_seconds}s after the restart')
        env.sleep(3)


def _roll_host(env: Env, target: Dict[str, Any], log: Callable[[str], None]) -> str:
    name = target['name']
    host = next((h for h in env.hosts() if str(h.get('host_name') or h.get('name') or '?') == name), None)
    if host is None:
        raise RollbackError(f'host {name} is not registered any more: restore it by hand from its backup {target["backup"]}')
    body, status = env.call_host(host, '/host/system/rollbackBundle', 'POST', {'backup_id': target['backup']}, APPLY_TIMEOUT + 30)
    body = body if isinstance(body, dict) else {}
    for line in body.get('log') or []:
        log(f'[{name}] {line}')
    if status != 200 or not body.get('success'):
        raise RollbackError(f'{name}: {body.get("error") or f"HTTP {status}"}')
    _wait_health(env, host)
    return f'{body.get("version_before")} -> {body.get("version_after")}'


def _ssh(env: Env, cfg: Dict[str, str], label: str, remote: str, timeout: int, log: Callable[[str], None]) -> None:
    secrets = frontend_ssh.secrets(cfg)
    try:
        res = env.run(frontend_ssh.ssh_argv(cfg, remote), timeout, frontend_ssh.child_env(cfg))
    except Exception as exc:
        raise RollbackError(f'frontend {label} failed: {type(exc).__name__}: {prerequisites.mask(str(exc), secrets)[:200]}')
    out = prerequisites.mask(((res.stdout or '') + (res.stderr or '')).strip(), secrets)
    for line in out.splitlines()[-8:]:
        log(f'[{cfg["host"]}] {line}')
    if res.returncode != 0:
        raise RollbackError(f'frontend {label} failed (exit {res.returncode}): {out[-200:]}')


def _roll_frontend(env: Env, target: Dict[str, Any], log: Callable[[str], None]) -> str:
    cfg = env.frontend_cfg()
    if cfg['mode'] != 'ssh':
        raise RollbackError('the frontend is not a separate VM any more (Settings): restore it by hand')
    backup, root = target['backup'], cfg['backup_root'].rstrip('/')
    if not re.fullmatch(re.escape(root) + r'/\d{8}_\d{6}', backup):
        raise RollbackError(f'refusing to restore from {backup}: not a backup folder under {root}')
    q = shlex.quote
    excludes = ' '.join(f'--exclude={q(p)}' for p in ba.RSYNC_EXCLUDES)
    target_dir = cfg['target_dir']
    _ssh(env, cfg, 'restore the previous tree',
         frontend_ssh.as_service_user(cfg, f'rsync -a --delete {excludes} {q(backup)}/ {q(target_dir)}/'), 1800, log)
    _ssh(env, cfg, 'build the frontend', frontend_ssh.as_service_user(cfg, f'bash {target_dir}/frontend/scripts/ensure_dist.sh'), 1800, log)
    _ssh(env, cfg, 'restart', frontend_ssh.sudo(cfg, f'systemctl restart {cfg["service"]}'), 120, log)
    _ssh(env, cfg, 'health', f'systemctl is-active {cfg["service"]}', 60, log)
    return f'tree restored from {backup}'


def _server_backup_root() -> str:
    from .pull_deploy import _server_backup_root as root
    return root()


def restore_server_tree(env: Env, backup_id: str, log: Callable[[str], None]) -> str:
    """Server tree back to the backup ``deploy_server`` made. Snapshots the current tree first. No restart here."""
    import os
    root, backup_root = pull_deploy.project_root(), _server_backup_root()
    if not SERVER_BACKUP_ID_RE.match(backup_id or ''):
        raise RollbackError('the recorded server backup id is not valid')
    real_root = os.path.realpath(backup_root)
    source = os.path.realpath(os.path.join(real_root, backup_id))
    if os.path.dirname(source) != real_root or not os.path.isdir(source):
        raise RollbackError(f'server backup {backup_id} is gone from {backup_root}: restore the VM snapshot or the tree by hand')
    version_before = read_version(root)
    try:
        env.backup(root, backup_root)            # the current tree stays restorable
    except Exception as exc:
        raise RollbackError(f'could not snapshot the current server tree, nothing was changed: {type(exc).__name__}: {str(exc)[:150]}')
    res = env.run(ba.rsync_command(source, root), 1800)
    if res.returncode != 0:
        raise RollbackError(f'server restore rsync failed: {(res.stderr or res.stdout)[-300:]}')
    rec = env.run(['sudo', '-n'] + priv.reconcile_argv(root), 300)
    if rec.returncode != 0:
        log(f'reconcile failed (the tree is restored): {(rec.stderr or rec.stdout)[-150:]}')
    return f'{version_before} -> {read_version(root)}'


# -- roll back ---------------------------------------------------------------------------------------
def run_rollback(store: RunStore, run_id: str, env: Env, by: str, threaded: bool = True) -> Dict[str, Any]:
    run = store.get(run_id)
    if not can_rollback(run):
        step = run['steps'][DEPLOY_STEP]
        if step['state'] == 'running' and (step['data'].get('job') or {}).get('state') != 'awaiting_confirmation':
            raise RollbackError('the deploy is still running: abort it first, then roll back')
        raise RollbackError('nothing to roll back (no machine was updated, or a roll back is already running)')
    targets = plan(run)
    bundle_jobs._claim('deploy', run_id)
    rb = rollback_state(store, run_id)
    rb.update({'state': 'running', 'by': by, 'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'actions': rb.get('actions') or [], 'order': [f'{t["role"]}:{t["name"]}' for t in targets]})
    try:
        _save_rollback(store, run_id, rb)
        store.log(run_id, f'Roll back started by {by}: ' + ', '.join(f'{t["name"]} ({t["role"]})' for t in targets), DEPLOY_STEP)
    except Exception:
        bundle_jobs._release('deploy')
        raise
    work = lambda: _do_rollback(store, run_id, env, targets)  # noqa: E731
    if threaded:
        threading.Thread(target=work, name=f'bundle-rollback-{run_id}', daemon=True).start()
    else:
        work()
    return rb


def _do_rollback(store: RunStore, run_id: str, env: Env, targets: List[Dict[str, Any]]) -> None:
    log = lambda line: store.log(run_id, line, DEPLOY_STEP)  # noqa: E731
    rb = rollback_state(store, run_id)
    try:
        server_target = None
        for t in targets:
            existing = _action(rb, t['role'], t['name'])
            if existing and existing['state'] == 'ok':
                log(f'Roll back {t["name"]}: already done, skipped')
                continue
            if t['role'] == 'server':
                server_target = t
                continue
            action = {'role': t['role'], 'name': t['name'], 'backup': t['backup'], 'state': 'running', 'detail': '',
                      'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            rb['actions'] = [a for a in rb['actions'] if not (a['role'] == t['role'] and a['name'] == t['name'])] + [action]
            _save_rollback(store, run_id, rb)
            log(f'Roll back {t["role"]} {t["name"]} from backup {t["backup"]}')
            try:
                action['detail'] = _roll_host(env, t, log) if t['role'] == 'host' else _roll_frontend(env, t, log)
                action['state'] = 'ok'
                log(f'Roll back {t["name"]}: ok ({action["detail"]})')
            except Exception as exc:
                action['state'] = 'failed'
                action['detail'] = (str(exc) if isinstance(exc, PlatformUpdateError) else f'{type(exc).__name__}: {exc}')[:300]
                log(f'Roll back {t["name"]}: FAILED - {action["detail"]}')
                rb['state'] = 'failed'
                _save_rollback(store, run_id, rb)
                return
            _save_rollback(store, run_id, rb)
        if server_target is not None:
            _roll_server(store, run_id, env, rb, server_target, log)
        else:
            _finish(store, run_id, rb, log)
    except Exception as exc:
        rb['state'] = 'failed'
        rb['error'] = (str(exc) if isinstance(exc, PlatformUpdateError) else f'{type(exc).__name__}: {exc}')[:300]
        log(f'Roll back stopped: {rb["error"]}')
        try:
            _save_rollback(store, run_id, rb)
        except PlatformUpdateError:
            pass
    finally:
        bundle_jobs._release('deploy')


def _roll_server(store, run_id, env, rb, target, log) -> None:
    name = target['name']
    action = {'role': 'server', 'name': name, 'backup': target['backup'], 'state': 'running', 'detail': '',
              'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    rb['actions'] = [a for a in rb['actions'] if not (a['role'] == 'server' and a['name'] == name)] + [action]
    _save_rollback(store, run_id, rb)
    log(f'Roll back the server {name} from backup {target["backup"]} (last: its restart ends this job)')
    try:
        action['detail'] = restore_server_tree(env, target['backup'], log)
        cfg = env.frontend_cfg()
        if cfg['mode'] == 'local':
            deploy_frontend_local(env, cfg, log)
        action['state'] = 'ok'
    except Exception as exc:
        action['state'] = 'failed'
        action['detail'] = (str(exc) if isinstance(exc, PlatformUpdateError) else f'{type(exc).__name__}: {exc}')[:300]
        rb['state'] = 'failed'
        log(f'Roll back the server: FAILED - {action["detail"]}')
        _save_rollback(store, run_id, rb)
        return
    rb['state'] = 'awaiting_confirmation'
    rb['restart_scheduled_at'] = time.time()
    _save_rollback(store, run_id, rb)
    log(f'Server tree restored ({action["detail"]}); vpt-server restarts in a few seconds. Confirm the roll back after it is back.')
    env.schedule_restart()


def _finish(store: RunStore, run_id: str, rb: Dict[str, Any], log: Callable[[str], None]) -> None:
    rb['state'] = 'done'
    rb['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    store.set_data(run_id, DEPLOY_STEP, {'rollback': rb, 'rolled_back': True})
    step = _step(store, run_id)
    detail = 'rolled back: every updated machine is on its previous version'
    if step['state'] == 'running':
        store.finish_step(run_id, DEPLOY_STEP, False, detail, {'job': {'state': 'rolled_back', 'mode': 'pull'}})
    else:
        store.mark_failed(run_id, DEPLOY_STEP, detail)
    log('Roll back complete')


def confirm_rollback(store: RunStore, run_id: str, log: Callable[[str], None]) -> None:
    """After the server restarted onto the restored tree: prove it, then close the roll back."""
    rb = rollback_state(store, run_id)
    if rb.get('state') != 'awaiting_confirmation':
        raise RollbackError('nothing to confirm: the roll back is not waiting for the server restart')
    if pull_deploy.PROCESS_START <= float(rb.get('restart_scheduled_at') or 0):
        raise RollbackError('the server has not restarted yet (the same process is still running); wait a few seconds and confirm again')
    running = read_version(pull_deploy.project_root())
    was = (_step(store, run_id)['data'].get('versions_before') or {}).get('server') or ''
    if was and was != 'unknown' and running != was:
        raise RollbackError(f'the server restarted but reports version {running}, it ran {was} before the update: check the server log')
    log(f'Server restarted and runs version {running}')
    _finish(store, run_id, rb, log)


def recover(store: RunStore, run: Dict[str, Any]) -> Dict[str, Any]:
    """A roll back that says ``running`` while this process runs none was cut off by a restart: it can be started again."""
    rb = run['steps'][DEPLOY_STEP]['data'].get('rollback') or {}
    if rb.get('state') == 'running' and bundle_jobs._RUNNING.get('deploy') != run['id']:
        rb = dict(rb, state='failed', error='interrupted: the server restarted during the roll back; run it again (finished machines are skipped)')
        store.set_data(run['id'], DEPLOY_STEP, {'rollback': rb})
        run = store.get(run['id'])
    return run


# -- migrations --------------------------------------------------------------------------------------
class MigrationRollbackStop(RollbackError):
    pass


def rollback_migrations(store: RunStore, run_id: str, backend: Backend, filenames: List[str], confirm: Any, by: str,
                        directory: Path = DEFAULT_DIR, log: Callable[[str], None] = lambda _m: None) -> List[str]:
    """Run the ``_rollback.sql`` of this run's migrations, newest first. ``filenames`` must be the exact list the operator saw."""
    run = store.get(run_id)
    mp = migration_plan(run, directory)
    if confirm is not True:
        raise RollbackError('confirmation required: confirm the list of rollback files')
    if not mp['plan']:
        raise RollbackError('no migration was applied in this run')
    if [i['file'] for i in mp['plan']] != list(filenames):
        raise RollbackError('the list does not match the migrations applied in this run (reload the page)')
    if not backend.can_execute:
        raise RollbackError('no database connection string configured for running migrations')
    done: List[str] = []
    rolled = list(run['steps'][MIGRATIONS_STEP]['data'].get('rolled_back') or [])
    for item in mp['plan']:
        if not item['has_rollback']:
            store.set_data(run_id, MIGRATIONS_STEP, {'rolled_back': rolled, 'needs_dump_restore': True})
            msg = (f'{item["file"]} has no rollback file ({item["rollback_file"]}): stopped. {len(done)} newer migration(s) were undone. '
                   f'Restore the step 1 database dump by hand (it replaces the whole database).')
            log(msg + (f' Command: {mp["restore_command"]}' if mp['restore_command'] else ''))
            raise MigrationRollbackStop(msg + (f' Command, as root on the database VM: {mp["restore_command"]}' if mp['restore_command'] else ''))
        sql = (Path(directory) / item['rollback_file']).read_text(encoding='utf-8')
        log(f'Rolling back {item["file"]} with {item["rollback_file"]}')
        try:
            backend.execute_file(sql)
        except Exception as exc:
            log(f'FAILED {item["rollback_file"]}: {exc}')
            raise RollbackError(f'{item["rollback_file"]} failed: {exc}. Undone before it: {len(done)}')
        backend.unrecord(item['file'])
        done.append(item['file'])
        rolled.append(item['file'])
        store.set_data(run_id, MIGRATIONS_STEP, {'rolled_back': rolled})
    store.mark_failed(run_id, MIGRATIONS_STEP, f'{len(done)} migration(s) rolled back by {by}')
    return done


# -- leave partial -----------------------------------------------------------------------------------
def leave_partial(store: RunStore, run_id: str, confirm: Any, by: str, hosts_now: List[dict], server_now: str) -> Dict[str, Any]:
    run = store.get(run_id)
    if confirm is not True:
        raise RollbackError('confirmation required: you are choosing to keep a mixed fleet')
    step = run['steps'][DEPLOY_STEP]
    if step['state'] == 'running' and (step['data'].get('job') or {}).get('state') != 'awaiting_confirmation':
        raise RollbackError('the deploy is still running: abort it first')
    if (step['data'].get('rollback') or {}).get('state') in ('running', 'awaiting_confirmation'):
        raise RollbackError('a roll back is running')
    view = impact(run, hosts_now, server_now)
    if not view['mixed']:
        raise RollbackError('no mixed versions: there is nothing to leave partial')
    detail = ('Left partial by ' + by + ' - ' + view['mixed_summary'])[:900]
    store.set_data(run_id, DEPLOY_STEP, {'partial': {'by': by, 'summary': view['mixed_summary']}})
    if step['state'] == 'running':
        store.finish_step(run_id, DEPLOY_STEP, False, detail, {'job': {'state': 'partial', 'mode': 'pull'}})
    else:
        store.mark_failed(run_id, DEPLOY_STEP, detail)
    store.log(run_id, detail, DEPLOY_STEP)
    return view
