"""
The server's SSH key for the frontend leg (TASK-128 G4), and the lines an admin pastes on the frontend VM.

The key is the one the pull deploy already uses: ``FRONTEND_DEPLOY_SSH_KEY`` (Settings, else .env) or, when unset, the
default key of the user the server process runs as (``~/.ssh/id_ed25519``). ``create()`` makes it with ``ssh-keygen`` as
that process user and NEVER overwrites an existing key. The app never logs in to the frontend VM or runs anything as
root there: ``frontend_command()`` is a string the admin runs as root on the frontend VM.
"""

import os
import re
import shlex
import socket
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import frontend_ssh, settings
from .runs import PlatformUpdateError

DEFAULT_KEY = '~/.ssh/id_ed25519'
DEFAULT_DEPLOY_USER = 'deploy'
KEY_OPTIONS = 'no-agent-forwarding,no-X11-forwarding,no-port-forwarding'
PLACEHOLDER_IP = '<this server IP>'
DROPIN = 'setup/sudoers/vpt-update-frontend'
DROPIN_TARGET = '/etc/sudoers.d/vpt-update-frontend'
_USER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_.-]{0,63}$')
Run = Callable[..., subprocess.CompletedProcess]


def _run(argv: List[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def key_path(env: Optional[Dict[str, str]] = None) -> str:
    return settings.get('frontend_deploy_ssh_key', env) or os.path.expanduser(DEFAULT_KEY)


def exists(path: str) -> bool:
    return os.path.exists(path) or os.path.exists(path + '.pub')


def public_key(path: str, run: Run = _run) -> str:
    """The public key text, '' when there is no key. A private key without a ``.pub`` is derived (read-only)."""
    try:
        with open(path + '.pub', encoding='utf-8') as fh:
            text = fh.read().strip()
        if text:
            return text.splitlines()[0].strip()
    except OSError:
        pass
    if os.path.isfile(path):
        try:
            res = run(['ssh-keygen', '-y', '-f', path])
            if res.returncode == 0:
                return (res.stdout or '').strip().splitlines()[0].strip()
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    return ''


def create(path: str, run: Run = _run) -> bool:
    """Make the key if it does not exist (-> True). An existing key, private or public, is left alone (-> False)."""
    if exists(path):
        return False
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    comment = f'vpt-platform-update@{socket.gethostname()}'
    try:
        res = run(['ssh-keygen', '-t', 'ed25519', '-N', '', '-C', comment, '-f', path], 30)
    except FileNotFoundError:
        raise PlatformUpdateError('ssh-keygen is not installed on the server (apt install openssh-client).')
    if res.returncode != 0:
        raise PlatformUpdateError(f'ssh-keygen failed: {((res.stderr or res.stdout or "").strip().splitlines() or ["error"])[-1][:200]}')
    os.chmod(path, 0o600)
    if os.path.exists(path + '.pub'):
        os.chmod(path + '.pub', 0o644)
    return True


def server_ip(address: str) -> str:
    """This server's address as ``address`` (host:port) sees it, '' when unknown. A UDP connect sends nothing."""
    from .db_backup import server_ip as _ip
    return _ip(address)


def authorized_line(pubkey: str, ip: str) -> str:
    return f'from="{ip or PLACEHOLDER_IP}",{KEY_OPTIONS} {pubkey}'


def frontend_command(line: str, user: str = DEFAULT_DEPLOY_USER, project_root: str = '/opt/virtualpytest') -> str:
    """One line for a root shell on the frontend VM: the deploy account, rsync, the key line, the sudoers drop-in."""
    if not _USER_RE.match(user):
        raise PlatformUpdateError('SSH user is not a valid account name.')
    u = shlex.quote(user)
    home = f'/home/{user}'
    ak = shlex.quote(f'{home}/.ssh/authorized_keys')
    q_line = shlex.quote(line)
    dropin = shlex.quote(f'{project_root.rstrip("/")}/{DROPIN}')
    install = (f'install -o root -g root -m 0440 {dropin} {DROPIN_TARGET}' if user == DEFAULT_DEPLOY_USER else
               f"sed {shlex.quote(f's/^deploy /{user} /')} {dropin} | install -o root -g root -m 0440 /dev/stdin {DROPIN_TARGET}")
    return (f"{{ id {u} >/dev/null 2>&1 || adduser --disabled-password --gecos '' {u}; }} && "
            f"{{ command -v rsync >/dev/null || apt-get install -y rsync; }} && "
            f"install -d -o {u} -g {u} -m 0700 {shlex.quote(home + '/.ssh')} && "
            f"{{ grep -qxF {q_line} {ak} 2>/dev/null || echo {q_line} >> {ak}; }} && "
            f"chown {u}:{u} {ak} && chmod 0600 {ak} && {install} && visudo -cf {DROPIN_TARGET}")


def view(env: Optional[Dict[str, str]] = None, run: Run = _run) -> Dict[str, Any]:
    """What the page shows: ``{exists, path, public_key, authorized_keys_line, frontend_command}`` (strings, '' when no key)."""
    path = key_path(env)
    pub = public_key(path, run) if exists(path) else ''
    out: Dict[str, Any] = {'exists': bool(pub), 'path': path, 'public_key': pub, 'authorized_keys_line': '', 'frontend_command': ''}
    if pub:
        cfg = frontend_ssh.config(env)
        out['authorized_keys_line'], out['frontend_command'] = lines_for(
            pub, cfg['host'] if cfg['mode'] == 'ssh' else '', cfg['user'] or DEFAULT_DEPLOY_USER, cfg['target_dir'])
    return out


def lines_for(pubkey: str, host: str, user: str, project_root: str) -> Tuple[str, str]:
    """``(authorized_keys line, frontend command)`` for the frontend VM at ``host``. The one place both are built: the page
    shows them (``view``) and the frontend set-up button runs the same command (TASK-128 G13)."""
    ip = server_ip(f'{host}:22') if host else ''
    line = authorized_line(pubkey, ip)
    return line, frontend_command(line, user, project_root)


def actions(reason: str, env: Optional[Dict[str, str]] = None, run: Run = _run) -> List[Dict[str, str]]:
    """The frontend_ssh KO row's ``actions``; [] when the server has no key yet (the row's fix says to create it)."""
    try:
        v = view(env, run)
    except Exception:
        return []
    if not v['exists']:
        return []
    return [{'machine': 'frontend VM', 'command': v['frontend_command'], 'reason': reason},
            {'machine': 'frontend VM', 'command': v['authorized_keys_line'],
             'reason': 'The authorized_keys line of the server key (already inside the command above).'}]
