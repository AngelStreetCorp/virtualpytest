"""
Background jobs of Platform update steps 2 and 3 (TASK-99 G6/G7).

The page adds no build or deploy logic of its own: step 2 runs ``customer_bundle.py build`` and step 3
runs ``deploy_bundle.sh`` as subprocesses of this server. Both stream their output line by line into
the run's log file (``<run_id>.log``, prefixed ``[step N]``), so the page shows them through the log it
already polls, and the deployment view (``deployment.py``) reads the same file.

* one build and one deploy at a time per server (``JobBusy``, HTTP 409);
* tokens travel in the child's environment, never in argv, and are masked in every logged line;
* a zip is never uploaded here: the page uses ``/server/system/source/zip/upload`` and sends the
  ``upload_id`` (``SOURCE_UPLOAD_ROOT/<id>/source.zip``), so there is one upload store and one set of limits;
* the child is started in its own session; a job that was running when the server restarted is
  closed as failed by ``recover_interrupted`` (a deploy restarts the server it was started from).
"""

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.src.lib.utils import git_auth

from . import before_versions, settings  # noqa: F401  (settings registers the saved GitHub token with git_auth)
from .deployment import build_view, project_root, timing_summary
from .runs import PlatformUpdateError, RunStore, require_backup

BUILD_STEP = 2
DEPLOY_STEP = 3
UPLOAD_ID_RE = re.compile(r'^[0-9a-f]{32}$')
TAG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$')
PROJECT_RE = re.compile(r'^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+$')
REF_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,120}$')
VERSION_RE = re.compile(r'(main-\d{4}[0-9.-]*[0-9]|release-\d{4}[0-9.-]*[0-9]|v\d+\.\d+\.\d+)')
DEPLOY_ARGS = ('--server', '--frontend')

_LOCK = threading.Lock()
_RUNNING: Dict[str, str] = {}  # kind -> run_id


class JobBusy(PlatformUpdateError):
    code = 409


def is_running(kind: str) -> bool:
    return kind in _RUNNING


def _claim(kind: str, run_id: str) -> None:
    with _LOCK:
        if kind in _RUNNING:
            raise JobBusy(f'a {kind} is already running on this server')
        _RUNNING[kind] = run_id


def _release(kind: str) -> None:
    with _LOCK:
        _RUNNING.pop(kind, None)


def upload_root() -> str:
    from backend_server.src.routes.server_system_routes import SOURCE_UPLOAD_ROOT
    return SOURCE_UPLOAD_ROOT


def builder_script() -> Path:
    return project_root() / 'setup' / 'proxmox' / 'node' / 'lib' / 'customer_bundle.py'


def deploy_script() -> Path:
    override = os.getenv('VPT_DEPLOY_BUNDLE_SCRIPT', '').strip()
    return Path(override) if override else project_root() / 'setup' / 'proxmox' / 'node' / 'deploy_bundle.sh'


# -- request -> command -------------------------------------------------------------------------
def _zip_path(upload_id: Any, root: str) -> str:
    if not isinstance(upload_id, str) or not UPLOAD_ID_RE.match(upload_id):
        raise PlatformUpdateError('invalid upload id')
    path = os.path.join(root, upload_id, 'source.zip')
    if not os.path.isfile(path):
        raise PlatformUpdateError('the uploaded zip is gone; upload it again')
    return path


def parse_spec(data: Dict[str, Any], root: Optional[str] = None) -> Dict[str, str]:
    """Page request -> ``{'core': 'github:<tag>', 'overlay': 'gitlab:<p>@<ref>', 'format', 'prev_pin'}``."""
    root = root if root is not None else upload_root()
    core = data.get('core') if isinstance(data.get('core'), dict) else {}
    overlay = data.get('overlay') if isinstance(data.get('overlay'), dict) else {}
    kind = str(core.get('kind') or '')
    if kind == 'github':
        tag = str(core.get('tag') or '').strip()
        if not TAG_RE.match(tag):
            raise PlatformUpdateError('pick a release tag for the core')
        core_arg = f'github:{tag}'
    elif kind == 'zip':
        core_arg = f'zip:{_zip_path(core.get("upload_id"), root)}'
    else:
        raise PlatformUpdateError('the core source must be a GitHub tag or a zip')

    okind = str(overlay.get('kind') or 'none')
    if okind == 'none':
        overlay_arg = 'none'
    elif okind == 'gitlab':
        project, ref = str(overlay.get('project') or '').strip(), str(overlay.get('ref') or '').strip()
        if not PROJECT_RE.match(project) or not REF_RE.match(ref):
            raise PlatformUpdateError('pick a GitLab project (group/name) and a branch')
        overlay_arg = f'gitlab:{project}@{ref}'
    elif okind == 'github':
        url, ref = str(overlay.get('url') or '').strip(), str(overlay.get('ref') or '').strip()
        if not re.match(r'^https://[A-Za-z0-9.-]+/[A-Za-z0-9_.~/-]+$', url) or not REF_RE.match(ref):
            raise PlatformUpdateError('give the overlay as a https GitHub URL and a ref (no credentials in the URL)')
        overlay_arg = f'github:{url}@{ref}'
    elif okind == 'zip':
        overlay_arg = f'zip:{_zip_path(overlay.get("upload_id"), root)}'
    else:
        raise PlatformUpdateError('unknown overlay source')

    fmt = str(data.get('format') or 'zip')
    if fmt not in ('zip', 'tar.gz'):
        raise PlatformUpdateError('format must be zip or tar.gz')
    prev = str(data.get('prev_pin') or '').strip()
    if prev and not TAG_RE.match(prev):
        raise PlatformUpdateError('invalid previous version')
    return {'core': core_arg, 'overlay': overlay_arg, 'format': fmt, 'prev_pin': prev}


def gitlab_credentials() -> Tuple[str, str]:
    """(base_url, token) of the GitLab instance configured on THIS server (the gitlab feature's first
    instance, else its env fallback). ('', '') when the feature is off or nothing is configured."""
    try:
        from features.gitlab.lib import instances
        inst = instances.get(None)
        if inst and inst.get('token'):
            return str(inst.get('base_url') or ''), str(inst['token'])
    except Exception:
        pass
    return os.getenv('VPT_GITLAB_URL', ''), os.getenv('VPT_GITLAB_TOKEN', '')


def github_token() -> str:
    return git_auth.github_token()


def build_command(spec: Dict[str, str], out_dir: str) -> Tuple[List[str], Dict[str, str], List[str]]:
    """-> (argv, env additions, secrets to mask). Tokens only ever go in the environment."""
    argv = [sys.executable, str(builder_script()), 'build', '--core', spec['core'],
            '--overlay', spec['overlay'], '--format', spec['format'], '--out', out_dir]
    if spec['prev_pin']:
        argv += ['--prev-pin', spec['prev_pin']]
    env: Dict[str, str] = {}
    secrets: List[str] = []
    base_url, token = gitlab_credentials()
    if spec['overlay'].startswith('gitlab:'):
        if not (base_url and token):
            raise PlatformUpdateError('no GitLab is configured on this server (Settings -> GitLab)')
        argv += ['--gitlab-url', base_url]
        env['VPT_GITLAB_TOKEN'] = token
        secrets.append(token)
    gh = github_token()
    if gh:
        env['VPT_GITHUB_TOKEN'] = gh
        secrets.append(gh)
    return argv, env, secrets


def sources(project: str = '', timeout: int = 90) -> Dict[str, Any]:
    """``customer_bundle.py candidates`` as the page's source lists (never carries a token)."""
    base_url, token = gitlab_credentials()
    argv = [sys.executable, str(builder_script()), 'candidates']
    if project:
        if not PROJECT_RE.match(project):
            raise PlatformUpdateError('invalid GitLab project')
        argv += ['--project', project]
    if base_url:
        argv += ['--gitlab-url', base_url]
    env = {**os.environ, 'VPT_GITLAB_TOKEN': token, 'VPT_GITHUB_TOKEN': github_token()}
    try:
        res = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, check=False)
        out = json.loads(res.stdout)
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        raise PlatformUpdateError(f'could not list the sources: {exc}')
    out['gitlab_instance'] = {'configured': bool(base_url and token), 'base_url': base_url}
    return out


# -- running a child ----------------------------------------------------------------------------
def _mask(line: str, secrets: List[str]) -> str:
    for s in secrets:
        if s:
            line = line.replace(s, '***')
    return line


def _stream(store: RunStore, run_id: str, step: int, argv: List[str], env: Dict[str, str],
            secrets: List[str], popen: Callable = subprocess.Popen) -> Tuple[int, List[str]]:
    """Run ``argv``, copy every output line to the run log (masked). -> (exit code, all output lines)."""
    lines: List[str] = []
    try:
        proc = popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                     env={**os.environ, **env}, start_new_session=True)
    except OSError as exc:
        store.log(run_id, f'could not start: {exc}', step)
        return 127, lines
    for raw in proc.stdout:
        line = _mask(raw.rstrip('\n'), secrets)
        lines.append(line)
        store.log(run_id, line, step)
    return proc.wait(), lines


def parse_record(lines: List[str]) -> Dict[str, Any]:
    """The archive record ``customer_bundle.py build`` prints as indented JSON after its log."""
    for i in range(len(lines) - 1, -1, -1):
        if lines[i] == '{':
            try:
                rec = json.loads('\n'.join(lines[i:]))
                return rec if isinstance(rec, dict) else {}
            except ValueError:
                return {}
    return {}


def bundle_version(archive_name: str, spec: Dict[str, str]) -> str:
    if spec['core'].startswith('github:'):
        return spec['core'][len('github:'):]
    found = VERSION_RE.search(archive_name or '')
    return found.group(1) if found else re.sub(r'\.(zip|tar\.gz)$', '', archive_name or '')


def run_build(store: RunStore, run_id: str, spec: Dict[str, str], argv: List[str], env: Dict[str, str],
              secrets: List[str], popen: Callable = subprocess.Popen) -> None:
    """Thread body of step 2 (bundle). Always ends the step (done or failed) and always releases the slot."""
    try:
        rc, lines = _stream(store, run_id, BUILD_STEP, argv, env, secrets, popen)
        record = parse_record(lines) if rc == 0 else {}
        if rc != 0 or not record.get('path'):
            reason = next((l for l in reversed(lines) if l.startswith('FAILED')), '') or f'the build exited {rc}'
            store.finish_step(run_id, BUILD_STEP, False, reason[:500], {'job': {'state': 'failed', 'exit': rc}})
            return
        name = record.get('name', '')
        bundle = {k: record.get(k, '') for k in ('name', 'path', 'size', 'sha256', 'delivery_note')}
        bundle['dir'] = os.path.dirname(record['path'])
        store.finish_step(run_id, BUILD_STEP, True, name, {
            'job': {'state': 'done', 'exit': 0}, 'bundle': bundle,
            'source': spec['core'].split(':', 1)[0] + ' + ' + spec['overlay'].split(':', 1)[0],
            'version': bundle_version(name, spec),
            'overlay': '' if spec['overlay'] == 'none' else spec['overlay'].split('@')[0].split(':', 1)[1],
        })
    except Exception as exc:  # the slot and the step must never stay stuck
        try:
            store.finish_step(run_id, BUILD_STEP, False, f'build job error: {exc}'[:500], {'job': {'state': 'failed'}})
        except PlatformUpdateError:
            pass
    finally:
        _release('build')


def start_build(store: RunStore, run_id: str, data: Dict[str, Any], threaded: bool = True,
                popen: Callable = subprocess.Popen) -> None:
    spec = parse_spec(data)
    out_dir = str(store.dir / 'bundles' / run_id)
    argv, env, secrets = build_command(spec, out_dir)
    env['VPT_BUILD_ROOT'] = str(store.dir / 'build-cache')
    if not builder_script().is_file():
        raise PlatformUpdateError(f'{builder_script()} is not on this server')
    _claim('build', run_id)
    try:
        store.begin_step(run_id, BUILD_STEP)
        store.set_data(run_id, BUILD_STEP, {'job': {'state': 'running'}, 'spec': {
            'core': spec['core'].split(':', 1)[0], 'overlay': spec['overlay'].split(':', 1)[0]}})
        store.log(run_id, f'Build: core {_public(spec["core"])}, overlay {_public(spec["overlay"])}', BUILD_STEP)
    except Exception:
        _release('build')
        raise
    target = lambda: run_build(store, run_id, spec, argv, env, secrets, popen)  # noqa: E731
    if threaded:
        threading.Thread(target=target, name=f'bundle-build-{run_id}', daemon=True).start()
    else:
        target()


def _public(arg: str) -> str:
    """A spec for the log: an uploaded zip shows its kind, not the server path."""
    return 'zip upload' if arg.startswith('zip:') else arg


# -- deploy -------------------------------------------------------------------------------------
def deploy_command(archive: str, replace_checkout: bool, update_args: List[str]) -> List[str]:
    argv = ['bash', str(deploy_script()), archive]
    if replace_checkout:
        argv.append('--replace-checkout')
    argv += [a for a in update_args if a in DEPLOY_ARGS]
    return argv


def operator_command(argv: List[str]) -> str:
    """The command an operator runs on the deploy node when this server cannot reach it."""
    return 'VPT_LEASE_AGENT=platform-update ' + ' '.join(argv)


def run_deploy(store: RunStore, run_id: str, argv: List[str], env: Dict[str, str],
               popen: Callable = subprocess.Popen) -> None:
    try:
        rc, _lines = _stream(store, run_id, DEPLOY_STEP, argv, env, [], popen)
        view = build_view(store.log_lines(run_id, tail=10_000_000))
        timings = timing_summary(view)
        failed = rc != 0 or (view is not None and view['state'] == 'failed')
        store.finish_step(run_id, DEPLOY_STEP, not failed,
                          '' if not failed else (f'deploy_bundle.sh exited {rc}' if rc else 'a host phase failed'),
                          {'job': {'state': 'failed' if failed else 'done', 'exit': rc}, 'timings': timings})
    except Exception as exc:
        try:
            store.finish_step(run_id, DEPLOY_STEP, False, f'deploy job error: {exc}'[:500], {'job': {'state': 'failed'}})
        except PlatformUpdateError:
            pass
    finally:
        _release('deploy')


def start_deploy(store: RunStore, run_id: str, data: Dict[str, Any], threaded: bool = True,
                 popen: Callable = subprocess.Popen) -> List[str]:
    require_backup(store.get(run_id))
    bundle = store.get(run_id)['steps'][BUILD_STEP]['data'].get('bundle') or {}
    archive = bundle.get('path') or ''
    if store.get(run_id)['steps'][BUILD_STEP]['state'] != 'done' or not archive:
        raise PlatformUpdateError('build the bundle in step 2 first')
    update_args = data.get('update_args') if isinstance(data.get('update_args'), list) else []
    argv = deploy_command(archive, data.get('replace_checkout') is True, [str(a) for a in update_args])
    if not deploy_script().is_file():
        raise PlatformUpdateError(
            f'deploy_bundle.sh is not on this server. It must run on the deploy node (the machine that holds '
            f'update_core.sh and reaches every VM): copy the archive there and run: {operator_command(argv[:1] + ["deploy_bundle.sh"] + argv[2:])}')
    if not os.path.isfile(archive):
        raise PlatformUpdateError('the built archive is gone from this server; build it again')
    env = {'VPT_LEASE_AGENT': os.getenv('VPT_LEASE_AGENT') or 'platform-update'}
    _claim('deploy', run_id)
    try:
        store.begin_step(run_id, DEPLOY_STEP)
        store.set_data(run_id, DEPLOY_STEP, {'job': {'state': 'running', 'mode': 'bundle', 'archive': bundle.get('name', ''),
                                                      'command': operator_command(argv)}})
        store.log(run_id, f'Deploy bundle {bundle.get("name", "")} (sha256 {bundle.get("sha256", "")[:12]})', DEPLOY_STEP)
        from . import prerequisites
        before_versions.capture_for_deploy(store, run_id, str(project_root()), prerequisites._hosts, data.get('frontend_version'))
    except Exception:
        _release('deploy')
        raise
    target = lambda: run_deploy(store, run_id, argv, env, popen)  # noqa: E731
    if threaded:
        threading.Thread(target=target, name=f'bundle-deploy-{run_id}', daemon=True).start()
    else:
        target()
    return argv


def recover_interrupted(store: RunStore, run: Dict[str, Any]) -> Dict[str, Any]:
    """A step whose job says ``running`` but that this process is not running was cut off by a restart."""
    for index, kind in ((BUILD_STEP, 'build'), (DEPLOY_STEP, 'deploy')):
        step = run['steps'][index]
        if step['state'] == 'running' and (step['data'].get('job') or {}).get('state') in ('running', 'paused') \
                and _RUNNING.get(kind) != run['id']:
            note = ('interrupted: the server restarted while the job ran; read the log, then run the step again'
                    if kind == 'build' else
                    'interrupted: the server restarted while the deploy ran (a deploy restarts this server); '
                    'check the host cards and the log, then close the step')
            run = store.finish_step(run['id'], index, False, note, {'job': {'state': 'interrupted'}})
    return run
