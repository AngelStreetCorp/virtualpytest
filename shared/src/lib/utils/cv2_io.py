"""cv2.imread / cv2.imwrite without opencv-python's path-string leak.

opencv-python's bindings keep a reference to every str filename passed to cv2.imread and
cv2.imwrite: each call leaves one live object behind for the life of the process (measured
2026-10-12 on Python 3.11 with opencv 4.10.0, 4.11.0 and 4.12.0 — sys.getallocatedblocks()
+1.00 per call; imencode/imdecode/np.fromfile/ndarray.tofile +0.00). capture_monitor reads a
capture and a thumbnail per frame, so it grew ~32 path strings a second: 1.45 GB on vpt-pi1
after 2.5 days with 3 devices (BUG-0474).

Upstream: PyOS_FSPath() result never released in pyopencv_to() for path-like args, fixed by
opencv PR #28047 (first in 4.13.0; 4.13/4.14/5.0 measured clean). 4.13+ requires numpy>=2 and
backend_host pins numpy<2, so this module stays until the numpy 2 migration.

Long-running code (host, server, monitors, shared libs) reads and writes images through
these two functions instead. Same arguments and return values as cv2.imread / cv2.imwrite:
imread returns None when the file is missing or not an image; imwrite returns a bool.
"""
import os

import cv2
import numpy as np


def imread(path, flags=cv2.IMREAD_COLOR):
    """cv2.imread(path, flags), decoded from the file's bytes."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite(path, img, params=None):
    """cv2.imwrite(path, img, params): encoded by the path's extension, then written."""
    ext = os.path.splitext(os.fspath(path))[1]
    ok, buf = cv2.imencode(ext, img, params if params is not None else [])
    if not ok:
        return False
    try:
        buf.tofile(path)
    except OSError:
        return False
    return True
