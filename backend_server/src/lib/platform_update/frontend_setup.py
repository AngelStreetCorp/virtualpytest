"""
"Set up frontend VM" (TASK-128 G13): prepare the frontend VM with a password the app uses once and never keeps.

The admin gives the frontend VM's address, an admin account and its password. The server logs in with them (``sshpass -e``),
runs the SAME command ``server_key.frontend_command`` shows for pasting (deploy account, rsync, the server key line with
``from=``, the sudoers drop-in checked by ``visudo -cf``), saves host / ``deploy`` / key path in the settings store and
forgets the password.

How the password travels (and nowhere else):
  1. ``SSHPASS`` in the environment of the ONE child process (``sshpass -e ssh ...``): never in argv.
  2. The FIRST LINE of that child's stdin, read by the remote shell and handed to ``sudo -S`` through a shell builtin
     (``printf``), so it is in no remote argv either. The remote script follows on the same stdin.
  3. Nothing writes it: not the run log, not the settings, not the response. Captured output is masked before it leaves.
The admin account must be ``root`` or be allowed to run ``sudo`` with its password.
"""

import os
import re
import shlex
import shutil
import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional

from . import frontend_ssh, prerequisites, server_key, settings
from .runs import PlatformUpdateError

TIMEOUT = 90
TAIL = 600
MAX_PASSWORD = 256
_USER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_.-]{0,63}$')
_lock = threading.Lock()

# Runs on the frontend VM. stdin = password line, then the script. root runs it directly; any other account feeds the
# password to ``sudo -S`` with a builtin printf (no argv). ``-p ''`` keeps sudo's prompt out of the output.
REMOTE_RUNNER = ("IFS= read -r P; S=$(cat); "
                 "if [ \"$(id -u)\" = 0 ]; then bash -c \"$S\" </dev/null; "
                 "else printf '%s\\n' \"$P\" | sudo -S -p '' bash -c \"$S\"; fi; "
                 "rc=$?; unset P; exit $rc")

class SetupBusy(PlatformUpdateError):
    code = 409


Run = Callable[[List[str], str, Dict[str, str], int], subprocess.CompletedProcess]


def _run(argv: List[str], stdin: str, env: Dict[str, str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout, check=False,
                          env={**os.environ, **env})


def validate(host: Any, admin_user: Any, password: Any) -> None:
    if not isinstance(host, str) or not host.strip() or host.strip().lower() in ('local', 'none'):
        raise PlatformUpdateError('Frontend VM address must be a host name or an IP address.')
    settings._check('frontend_deploy_host', host.strip())
    if not isinstance(admin_user, str) or not _USER_RE.match(admin_user.strip()):
        raise PlatformUpdateError('Admin user is not a valid account name.')
    if (not isinstance(password, str) or not password or len(password) > MAX_PASSWORD
            or '\n' in password or '\r' in password or '\x00' in password):
        raise PlatformUpdateError('Password is required (one line, up to 256 characters).')


def ssh_argv(host: str, admin_user: str) -> List[str]:
    return ['sshpass', '-e', 'ssh', '-T', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'PubkeyAuthentication=no', '-o', 'PreferredAuthentications=password,keyboard-interactive',
            '-o', 'NumberOfPasswordPrompts=1', f'{admin_user}@{host}', f'bash -c {shlex.quote(REMOTE_RUNNER)}']


def _step(steps: List[Dict[str, Any]], name: str, ok: bool, detail: str = '') -> bool:
    steps.append({'name': name, 'ok': ok, 'detail': detail})
    return ok


def _tail(text: str, password: str) -> str:
    return prerequisites.mask(text, [password]).strip()[-TAIL:]


def is_running() -> bool:
    return _lock.locked()


def run(host: str, admin_user: str, password: str, run_cmd: Run = _run, which: Callable = None,
        check: Optional[Callable[[], Dict[str, Any]]] = None, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """-> ``{ok, steps: [{name, ok, detail}], check?}``. Raises ``PlatformUpdateError`` for bad input and when a run is going."""
    which = which or shutil.which
    validate(host, admin_user, password)
    host, admin_user = host.strip(), admin_user.strip()
    if not _lock.acquire(blocking=False):
        raise SetupBusy('A frontend VM set-up is already running.')
    steps: List[Dict[str, Any]] = []
    try:
        if not which('sshpass') or not which('ssh'):
            _step(steps, 'tools', False, 'sshpass and ssh must be installed on the server (apt install sshpass openssh-client).')
            return {'ok': False, 'steps': steps}
        path = server_key.key_path(env)
        try:
            created = server_key.create(path)
            pub = server_key.public_key(path)
        except PlatformUpdateError as exc:
            _step(steps, 'server key', False, str(exc))
            return {'ok': False, 'steps': steps}
        if not pub:
            _step(steps, 'server key', False, f'No public key found for {path}.')
            return {'ok': False, 'steps': steps}
        _step(steps, 'server key', True, 'created' if created else 'exists')
        cfg = frontend_ssh.config(env)
        line, script = server_key.lines_for(pub, host, server_key.DEFAULT_DEPLOY_USER, cfg['target_dir'])
        if 'from="' + server_key.PLACEHOLDER_IP in line:
            _step(steps, 'server address', False, 'This server\'s address, as the frontend VM sees it, is unknown.')
            return {'ok': False, 'steps': steps}
        name = f'{admin_user}@{host}: account, key and sudoers'
        try:
            res = run_cmd(ssh_argv(host, admin_user), password + '\n' + script, {'SSHPASS': password}, TIMEOUT)
            ok, out = res.returncode == 0, (res.stdout or '') + (res.stderr or '')
            if res.returncode == 5:
                out = 'Wrong password for ' + admin_user + '. ' + out
        except subprocess.TimeoutExpired:
            ok, out = False, f'timed out after {TIMEOUT} s'
        except Exception as exc:
            ok, out = False, f'{type(exc).__name__}: {exc}'
        if not _step(steps, name, ok, '' if ok else _tail(out, password) or 'failed'):
            return {'ok': False, 'steps': steps}
        try:
            settings.update({'frontend_deploy_host': host, 'frontend_deploy_ssh_user': server_key.DEFAULT_DEPLOY_USER,
                             'frontend_deploy_ssh_key': path})
        except Exception as exc:
            _step(steps, 'save settings', False, str(exc)[:200])
            return {'ok': False, 'steps': steps}
        _step(steps, 'save settings', True)
        result = check() if check else prerequisites.check_frontend_ssh(prerequisites.Ctx('github', 'none', prerequisites.Deps()))
        _step(steps, 'check the SSH connection', result.get('status') == 'ok', str(result.get('detail') or ''))
        return {'ok': result.get('status') == 'ok', 'steps': steps, 'check': result}
    finally:
        password = ''   # the one copy this function owns; the caller drops its own
        _lock.release()
