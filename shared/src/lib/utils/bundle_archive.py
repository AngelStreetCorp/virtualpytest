"""
Safe handling of a platform bundle archive (TASK-101), shared by the server and the hosts.

A bundle is ``.zip`` or ``.tar.gz`` with ONE top-level ``virtualpytest/`` folder that holds
``BUNDLE_MANIFEST.txt`` and no ``.git`` (the same rules ``setup/proxmox/node/deploy_bundle.sh`` enforces).
Nothing here touches an install: it only checks and extracts into a directory the caller gives.
"""

import hashlib
import os
import stat
import tarfile
import zipfile
from typing import Callable, Dict, Iterable, List, Optional

TOP = 'virtualpytest'
CHUNK = 1024 * 1024


class BundleError(Exception):
    """The archive is not a safe, complete bundle. The message is fit to show to an operator."""


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b''):
            digest.update(chunk)
    return digest.hexdigest()


def check_member_name(name: str) -> None:
    """Reject a path that could land outside the destination."""
    norm = name.replace('\\', '/')
    if '\\' in name or norm.startswith('/') or (len(norm) > 1 and norm[1] == ':'):
        raise BundleError(f'unsafe path in archive: {name!r}')
    if any(part == '..' for part in norm.split('/')):
        raise BundleError(f'unsafe path in archive: {name!r}')
    if '\x00' in name:
        raise BundleError('unsafe path in archive (NUL byte)')


def check_names(names: Iterable[str]) -> List[str]:
    names = [n for n in names if n]
    if not names:
        raise BundleError('the archive is empty')
    for name in names:
        check_member_name(name)
    tops = sorted({n.split('/')[0] for n in names})
    if tops != [TOP]:
        raise BundleError(f'archive top level must be a single {TOP}/ folder, found: {", ".join(tops)}')
    if f'{TOP}/BUNDLE_MANIFEST.txt' not in names:
        raise BundleError('no BUNDLE_MANIFEST.txt in the archive: not a bundle')
    if any(n == f'{TOP}/.git' or n.startswith(f'{TOP}/.git/') for n in names):
        raise BundleError('the archive carries a .git: not a bundle')
    return names


def _kind(path: str) -> str:
    low = path.lower()
    if low.endswith('.zip'):
        return 'zip'
    if low.endswith('.tar.gz') or low.endswith('.tgz'):
        return 'tar'
    raise BundleError('unsupported archive (expected .zip or .tar.gz)')


def _inside(base: str, target: str) -> bool:
    base = os.path.realpath(base)
    target = os.path.realpath(target)
    return target == base or target.startswith(base + os.sep)


def safe_extract(archive: str, dest: str) -> str:
    """Extract ``archive`` into the (new or empty) directory ``dest``; return ``<dest>/virtualpytest``.

    Every member name is checked before anything is written; links that point outside ``dest`` and
    special files are refused. Executable bits are kept (zip does not restore them by itself).
    """
    kind = _kind(archive)
    os.makedirs(dest, exist_ok=True)
    try:
        if kind == 'zip':
            _extract_zip(archive, dest)
        else:
            _extract_tar(archive, dest)
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as exc:
        raise BundleError(f'cannot read the archive: {exc}')
    tree = os.path.join(dest, TOP)
    if not os.path.isfile(os.path.join(tree, 'BUNDLE_MANIFEST.txt')):
        raise BundleError('the extracted tree has no BUNDLE_MANIFEST.txt')
    if os.path.lexists(os.path.join(tree, '.git')):
        raise BundleError('the extracted tree carries a .git')
    return tree


def _extract_zip(archive: str, dest: str) -> None:
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        check_names([i.filename.rstrip('/') for i in infos])
        for info in infos:
            mode = info.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise BundleError(f'symlink in a zip bundle: {info.filename!r}')
        zf.extractall(dest)
        for info in infos:
            mode = info.external_attr >> 16
            if mode and not info.is_dir() and mode & 0o111:
                path = os.path.join(dest, info.filename)
                if _inside(dest, path) and os.path.isfile(path):
                    os.chmod(path, 0o755)


def _extract_tar(archive: str, dest: str) -> None:
    with tarfile.open(archive, 'r:gz') as tf:
        members = tf.getmembers()
        check_names([m.name.rstrip('/') for m in members])
        for m in members:
            if m.isdev() or m.isfifo():
                raise BundleError(f'special file in the archive: {m.name!r}')
            if m.islnk() or m.issym():
                if m.islnk():
                    target = os.path.join(dest, m.linkname)
                else:
                    target = os.path.join(os.path.dirname(os.path.join(dest, m.name)), m.linkname)
                if os.path.isabs(m.linkname) or not _inside(dest, target):
                    raise BundleError(f'link points outside the bundle: {m.name!r}')
        tf.extractall(dest, members=members)


def download(url: str, dest_file: str, headers: Optional[Dict[str, str]] = None, max_bytes: int = 2 * 1024 ** 3,
             timeout: int = 60, get: Optional[Callable] = None) -> str:
    """Stream ``url`` to ``dest_file`` (never held in memory), refusing more than ``max_bytes``.
    Returns the sha256 of what was written. ``get`` is injectable for tests (requests.get signature)."""
    if get is None:
        import requests
        get = requests.get
    try:
        resp = get(url, headers=headers or {}, stream=True, timeout=timeout)
    except Exception as exc:
        raise BundleError(f'download failed: {type(exc).__name__}: {exc}'[:300])
    try:
        status = getattr(resp, 'status_code', 200)
        if status != 200:
            raise BundleError(f'download failed: the server answered HTTP {status}')
        declared = getattr(resp, 'headers', {}).get('Content-Length')
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise BundleError(f'the bundle is larger than the {max_bytes // (1024 ** 2)} MB limit')
        digest = hashlib.sha256()
        total = 0
        with open(dest_file, 'wb') as out:
            for chunk in resp.iter_content(chunk_size=CHUNK):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise BundleError(f'the bundle is larger than the {max_bytes // (1024 ** 2)} MB limit')
                digest.update(chunk)
                out.write(chunk)
        return digest.hexdigest()
    finally:
        close = getattr(resp, 'close', None)
        if close:
            close()


# Mirrors RSYNC_EXCLUDES of setup/proxmox/node/update_core.sh (+ the .backups folder the host keeps): what a
# sync from a bundle never overwrites or deletes, so a machine keeps its identity across an update.
RSYNC_EXCLUDES = (
    '.git', '.github', '.cursor', '.husky', '.env', 'venv', 'node_modules', '__pycache__', '*.pyc', '*.pyo',
    'frontend/public/docs', 'frontend/dist', 'playwright-report*', 'playwright-viewport-report*',
    'security_report', 'backend_host/config/user_data', 'backend_host/config/webkit_user_data',
    'frontend/.env.production', 'frontend/vite.config.local.json', 'frontend/public/branding.json',
    'frontend/public/brand', 'frontend/public/favicon.ico', 'frontend/public/logo.png',
    'test_scripts/script_identity_map.json', 'test_scripts/campaign_identity_map.json',
    'test_campaign/campaign_identity_map.json', 'frontend/public/data/script_identity_map.json',
    'frontend/public/data/campaign_identity_map.json', '.backups',
)


def rsync_command(source_tree: str, project_root: str) -> list:
    # --checksum: zip mtimes are 2 s coarse, so size+time can call a changed file unchanged
    cmd = ['rsync', '-a', '--checksum', '--delete']
    cmd += [f'--exclude={p}' for p in RSYNC_EXCLUDES]
    cmd += [source_tree.rstrip('/') + '/', project_root.rstrip('/') + '/']
    return cmd
