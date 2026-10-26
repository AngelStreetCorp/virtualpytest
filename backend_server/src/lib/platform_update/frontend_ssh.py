"""
Server -> frontend VM over SSH, for the pull update (TASK-101). Used by the prerequisites check and the deploy.

Two ways to authenticate, both documented in docs/user-guide/update-setup.md:
  * a key (default): ``ssh -o BatchMode=yes``; the key is the service user's default key or ``FRONTEND_DEPLOY_SSH_KEY``;
    the remote account needs ``sudo -n`` for the service user and the restart.
  * a password (``FRONTEND_DEPLOY_SSH_PASSWORD``, what the older deploy button already uses): through ``sshpass -e``
    (the password travels in the child's environment, never in argv).

Nothing here has a lab default. The frontend target says where the frontend lives, and every
consumer (the prerequisites check, the pull deploy, the older Code deployment buttons) reads it through
``config`` so they can never disagree. Host, SSH user and key come from ``settings.get`` (Platform update -> Settings,
else ``FRONTEND_DEPLOY_HOST`` / ``_SSH_USER`` / ``_SSH_KEY`` in the .env; TASK-128):

  * a host name or IP   a separate frontend VM, reached over SSH (``mode`` = ``ssh``)
  * ``local``           the frontend runs on the server VM itself (``mode`` = ``local``)
  * ``none``            there is no frontend to update (``mode`` = ``none``)
  * unset or empty      not decided: ``mode`` = ``unset``, the prerequisites check is KO until it is set
"""

import os
import shlex
import shutil
from typing import Dict, List, Optional

from . import settings

STAGING_DIR = '/var/tmp/vpt_bundle_incoming'


def config(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = os.environ if env is None else env
    get = lambda k, d='': (env.get(k) or d).strip()  # noqa: E731
    target = settings.get('frontend_deploy_host', env)
    mode = 'unset' if not target else (target.lower() if target.lower() in ('local', 'none') else 'ssh')
    return {
        'mode': mode,
        'host': target if mode == 'ssh' else '',
        'user': settings.get('frontend_deploy_ssh_user', env),
        'password': get('FRONTEND_DEPLOY_SSH_PASSWORD'),
        'key': settings.get('frontend_deploy_ssh_key', env),
        'target_dir': get('FRONTEND_DEPLOY_TARGET_DIR', '/opt/virtualpytest'),
        'backup_root': get('FRONTEND_DEPLOY_BACKUP_ROOT', '/var/tmp/virtualpytest_backups'),
        'service': get('FRONTEND_DEPLOY_SERVICE_NAME', 'vpt-frontend'),
        'service_user': get('FRONTEND_DEPLOY_SERVICE_USER', 'vpt_user'),
    }


def ssh_options(cfg: Dict[str, str]) -> List[str]:
    opts = ['-o', 'ConnectTimeout=8', '-o', 'StrictHostKeyChecking=accept-new']
    if not cfg['password']:
        opts += ['-o', 'BatchMode=yes']
    if cfg['key']:
        opts += ['-i', cfg['key']]
    return opts


def child_env(cfg: Dict[str, str]) -> Dict[str, str]:
    return {'SSHPASS': cfg['password']} if cfg['password'] else {}


def _wrap(cfg: Dict[str, str]) -> List[str]:
    return ['sshpass', '-e'] if cfg['password'] else []


def secrets(cfg: Dict[str, str]) -> List[str]:
    return [cfg['password']] if cfg['password'] else []


def sudo(cfg: Dict[str, str], args: str) -> str:
    """``sudo`` for the remote shell: key mode needs ``sudo -n``; password mode feeds the password on stdin."""
    if cfg['password']:
        return f'echo {shlex.quote(cfg["password"])} | sudo -S {args}'
    return f'sudo -n {args}'


def ssh_argv(cfg: Dict[str, str], remote_command: str) -> List[str]:
    return _wrap(cfg) + ['ssh'] + ssh_options(cfg) + [f'{cfg["user"]}@{cfg["host"]}', remote_command]


def as_service_user(cfg: Dict[str, str], command: str) -> str:
    return sudo(cfg, f'-H -u {shlex.quote(cfg["service_user"])} bash -lc {shlex.quote(command)}')


def rsync_argv(cfg: Dict[str, str], source_tree: str, excludes: List[str]) -> List[str]:
    ssh_cmd = ' '.join(['ssh'] + [shlex.quote(o) for o in ssh_options(cfg)])
    argv = _wrap(cfg) + ['rsync', '-a', '--checksum', '--delete', '--chmod=Da+rx,Fa+r', '-e', ssh_cmd]
    argv += [f'--exclude={p}' for p in excludes]
    argv += [source_tree.rstrip('/') + '/', f'{cfg["user"]}@{cfg["host"]}:{STAGING_DIR}/']
    return argv


def missing_local_tools(cfg: Dict[str, str], which=shutil.which) -> List[str]:
    need = ['ssh', 'rsync'] + (['sshpass'] if cfg['password'] else [])
    return [t for t in need if not which(t)]
