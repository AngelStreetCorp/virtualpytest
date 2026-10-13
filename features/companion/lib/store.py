"""Where the companion result for a device lives: ``<metadata>/companion.json``.

Written by the vpt-companion service, read by the host route. It sits next to
``last_zapping.json``; the hot/cold archiver only moves ``capture_*.json`` and chunk files,
so it stays put.
"""

import json
import os
from typing import Optional

RESULT_FILE = "companion.json"


def result_path(device_id: str) -> str:
    from shared.src.lib.utils.storage_path_utils import get_capture_folder_from_device_id, get_metadata_path
    return os.path.join(get_metadata_path(get_capture_folder_from_device_id(device_id)), RESULT_FILE)


def write_result(path: str, result: Optional[dict]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_result(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
