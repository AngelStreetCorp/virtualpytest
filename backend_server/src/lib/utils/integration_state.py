"""
Location of integration state written at runtime (credentials, thread mappings).

These files live OUTSIDE the project tree on purpose: deploys ``rsync --delete`` the
project directory, which would wipe anything the server wrote into it (TestRail was
silently disconnected on every deploy). Default directory is
``~/.config/virtualpytest/`` of the user the server runs as (``vpt_user``), the same
place as the AI secrets store; ``VPT_CONFIG_DIR`` overrides it (e.g. a mounted volume
in Docker).

Tracked, hand-edited config (``grafana_config.json``, the ``*.example`` templates) stays
in ``backend_server/config/integrations/``.
"""

import os
from pathlib import Path

_DEFAULT_DIR = Path('~/.config/virtualpytest')


def state_dir() -> Path:
    return Path(os.getenv('VPT_CONFIG_DIR', '').strip() or _DEFAULT_DIR).expanduser()


def state_path(filename: str) -> Path:
    return state_dir() / filename
