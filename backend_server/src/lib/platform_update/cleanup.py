"""
Free disk space on the server (TASK-128 G6): delete what Platform update left behind, beyond the newest five of each kind.

Three kinds, each a set of folders directly inside one known directory:

  backups   ``<state dir>/platform-update/backups/<timestamp>/``  the step 1 backups (.env files, 0700)
  bundles   ``<state dir>/platform-update/bundles/<run id>/``     the bundles step 2 built (archive + delivery note)
  bak       ``<parent of the project root>/<root name>.bak-<timestamp>/``  the previous trees ``deploy_bundle.sh`` keeps

Safety, because this deletes:
  * only direct children of those directories, never the directory itself and never a path the caller names;
  * a child is deleted only if it is a real folder (a symlink is refused and reported, never followed), its real path
    is still inside its directory, and (``bak``) its name matches the pattern ``deploy_bundle.sh`` writes;
  * the bundle of a run that is still active is kept, and nothing is deleted while a build or deploy job runs here;
  * ``dry_run`` lists exactly what a real run would delete and changes nothing.

Hosts are out of scope: this frees the server only.
"""

import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .runs import PlatformUpdateError

KEEP = 5


class Busy(PlatformUpdateError):
    code = 409

LABELS = {
    'backups': 'Update backups (.env copies)',
    'bundles': 'Built bundles',
    'bak': 'Previous trees kept by deploy_bundle.sh',
}


def _size(path: str) -> int:
    """Bytes under ``path``, symlinks counted as links (never followed)."""
    total = 0
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in files + dirs:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                continue
    return total


def _dirs(state_dir: Path, project_root: str) -> Dict[str, Dict[str, Any]]:
    root = Path(project_root.rstrip('/') or '/')
    base = re.escape(root.name)
    return {
        'backups': {'dir': Path(state_dir) / 'backups', 'pattern': re.compile(r'^\d{8}-\d{6}(-\d+)?$')},
        'bundles': {'dir': Path(state_dir) / 'bundles', 'pattern': re.compile(r'^[A-Za-z0-9_-]+$')},
        'bak': {'dir': root.parent, 'pattern': re.compile(rf'^{base}\.bak-\d{{8}}-\d{{6}}(-\d+)?$')},
    }


def _entries(kind: str, spec: Dict[str, Any], protected: set) -> Dict[str, Any]:
    directory: Path = spec['dir']
    out = {'kind': kind, 'label': LABELS[kind], 'dir': str(directory), 'keep': [], 'delete': [], 'refused': []}
    if not directory.is_dir() or directory.is_symlink():
        return out
    real_dir = os.path.realpath(directory)
    found = []
    for child in directory.iterdir():
        if not spec['pattern'].match(child.name):
            continue                                       # not ours: never listed, never touched
        if child.is_symlink() or not child.is_dir():
            if child.is_symlink():
                out['refused'].append({'name': child.name, 'reason': 'symlink'})
            continue
        if os.path.dirname(os.path.realpath(child)) != real_dir:
            out['refused'].append({'name': child.name, 'reason': 'outside its folder'})
            continue
        found.append(child)
    found.sort(key=lambda c: (c.stat().st_mtime, c.name), reverse=True)
    for i, child in enumerate(found):
        item = {'name': child.name, 'path': str(child), 'bytes': _size(str(child))}
        if i < KEEP or child.name in protected:
            out['keep'].append(item)
        else:
            out['delete'].append(item)
    return out


def plan(state_dir: Path, project_root: str, protected_bundles: Optional[set] = None) -> Dict[str, Any]:
    """What a cleanup deletes: ``{groups[], total_bytes, count}``. Changes nothing."""
    specs = _dirs(state_dir, project_root)
    groups = [_entries(k, specs[k], (protected_bundles or set()) if k == 'bundles' else set()) for k in ('backups', 'bundles', 'bak')]
    total = sum(i['bytes'] for g in groups for i in g['delete'])
    return {'keep_newest': KEEP, 'groups': groups, 'total_bytes': total,
            'count': sum(len(g['delete']) for g in groups)}


def _delete(item: Dict[str, Any], directory: str) -> Optional[str]:
    """Delete one planned folder after checking it again (it may have changed since the plan). -> error text or None."""
    path = item['path']
    if os.path.islink(path) or not os.path.isdir(path):
        return 'is no longer a plain folder'
    if os.path.dirname(os.path.realpath(path)) != os.path.realpath(directory):
        return 'is outside its folder'
    try:
        shutil.rmtree(path)
    except OSError as exc:
        return f'{type(exc).__name__}: {exc.strerror or exc}'[:160]
    return None


def run(state_dir: Path, project_root: str, dry_run: bool = True, protected_bundles: Optional[set] = None,
        busy: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    """Plan, and unless ``dry_run`` delete. -> the plan plus ``dry_run``, ``freed_bytes``, ``deleted``, ``errors``."""
    result = plan(state_dir, project_root, protected_bundles)
    result.update({'dry_run': bool(dry_run), 'freed_bytes': 0, 'deleted': 0, 'errors': []})
    if dry_run:
        return result
    if busy():
        raise Busy('a bundle build or deploy is running on this server: free space when it ends')
    for group in result['groups']:
        for item in group['delete']:
            error = _delete(item, group['dir'])
            if error:
                result['errors'].append({'path': item['path'], 'error': error})
            else:
                result['freed_bytes'] += item['bytes']
                result['deleted'] += 1
    return result
