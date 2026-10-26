"""
The one privileged helper the pull update runs as root (TASK-101), and how to call and check it.

``reconcile_feature_units.sh`` used to run through sudo straight from the project tree, a file the service
user owns: whoever can write it gets root. The sudoers drop-in (``setup/sudoers/vpt-update``) now grants
only ``HELPER``, a root-owned copy installed by ``setup/sudoers/install_vpt_update_sudoers.sh``. Every
caller (host applyBundle, the pull deploy of the server, the prerequisites, the "Run command" reconcile)
builds its command here so the path exists in one place.
"""

import hashlib
import os
import shlex
from typing import List, Optional

HELPER = '/usr/local/sbin/vpt-reconcile-feature-units'
LIB_DIR = '/usr/local/lib/vpt-update'
REPO_COPY_RELATIVE = 'setup/proxmox/node/reconcile_feature_units.sh'
LIB_RELATIVE = 'setup/proxmox/node/lib/feature_units.sh'
STALE = 'installed reconcile helper is older than the tree'


def reconcile_argv(project_root: str) -> List[str]:
    """What the service user runs (with ``sudo -n`` in front)."""
    return [HELPER, '--project-root', project_root]


def install_command(project_root: str) -> str:
    """The one line an admin runs as root on a machine to install (or refresh) the sudoers drop-in and the helper.
    The app only shows it; it never runs it."""
    root = project_root.rstrip('/') or '/'
    script = shlex.quote(f'{root}/setup/sudoers/install_vpt_update_sudoers.sh')
    return f'sudo bash {script} --project-root {shlex.quote(root)}'


def _sha256(path: str) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with open(path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b''):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def helper_stale(project_root: str, helper: str = HELPER, lib_dir: str = LIB_DIR) -> Optional[str]:
    """None when the installed helper and its lib match the tree's copies (or there is nothing to compare);
    ``STALE`` when either differs. A helper that is not installed is reported by the sudo probe, not here."""
    pairs = ((helper, os.path.join(project_root, REPO_COPY_RELATIVE)),
             (os.path.join(lib_dir, 'feature_units.sh'), os.path.join(project_root, LIB_RELATIVE)))
    for installed_path, repo_path in pairs:
        installed, repo = _sha256(installed_path), _sha256(repo_path)
        if installed is not None and repo is not None and installed != repo:
            return STALE
    return None
