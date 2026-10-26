"""
Replace a config file (a ``.env``) atomically, keeping a copy of the current one and its owner and mode (TASK-128 G7).

Used by the Platform update restore on the server and on a host. The new content is written to a temp file in the
SAME folder (so ``os.replace`` is atomic: a reader sees the old or the new file, never half of it), given the mode of the
file it replaces (0600 when there was none), and only then moved into place. The current file is copied first to
``<path>.bak-<stamp>`` with the same mode, so a wrong restore can be undone by hand.
"""

import os
import shutil
import tempfile
from typing import Optional


def replace_keeping_mode(path: str, data: bytes, stamp: str) -> Optional[str]:
    """Write ``data`` to ``path``. -> the path of the copy of the previous file, or None when there was none."""
    folder = os.path.dirname(path) or '.'
    previous = os.stat(path) if os.path.isfile(path) and not os.path.islink(path) else None
    if os.path.islink(path):
        raise OSError(f'{path} is a symlink: refusing to replace it')
    backup = None
    if previous is not None:
        backup = f'{path}.bak-{stamp}'
        n = 1
        while os.path.exists(backup):
            n += 1
            backup = f'{path}.bak-{stamp}-{n}'
        shutil.copy2(path, backup)                     # keeps the mode; the copy holds the same secrets
        os.chmod(backup, previous.st_mode & 0o777)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix='.restore-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, (previous.st_mode & 0o777) if previous is not None else 0o600)
        if previous is not None and (previous.st_uid, previous.st_gid) != (os.getuid(), os.getgid()):
            try:
                os.chown(tmp, previous.st_uid, previous.st_gid)
            except PermissionError:
                pass                                    # not root: the file keeps the service user as owner
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return backup
