"""
Themes Routes - colour themes an install provides (TASK-102)

Reads every ``*.json`` file in ``config/themes/`` at the repo root (a customer overlay ships its own
files there; an absent folder means no provided themes). Invalid files are skipped with a log line.

Endpoints:
  GET /server/themes  - {"success": true, "themes": [...]}  (any signed-in user; global auth guard)
"""

import json
import os
import re
from pathlib import Path

from flask import Blueprint, jsonify

from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

server_themes_bp = Blueprint('server_themes', __name__, url_prefix='/server/themes')

_REPO_ROOT = Path(__file__).resolve().parents[3]
THEMES_DIR = Path(os.environ.get('VPT_THEMES_DIR', str(_REPO_ROOT / 'config' / 'themes')))

_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
_TONES = {'neutral', 'warm', 'cool'}


def _validate(data) -> str:
    """Return an error message, or '' when the theme is valid."""
    if not isinstance(data, dict):
        return 'not a JSON object'
    if not isinstance(data.get('id'), str) or not data['id'].strip():
        return 'missing id'
    if not isinstance(data.get('name'), str) or not data['name'].strip():
        return 'missing name'
    if not isinstance(data.get('accent'), str) or not _HEX.match(data['accent']):
        return 'accent must be #rrggbb'
    if data.get('tone') not in _TONES:
        return 'tone must be neutral, warm or cool'
    for key in ('dark', 'light'):
        if key in data:
            if not isinstance(data[key], dict):
                return f'{key} must be an object'
            for k, v in data[key].items():
                if not isinstance(k, str) or not isinstance(v, (str, list)):
                    return f'{key}.{k} must be a string or list'
    return ''


def load_themes(directory: Path = None) -> list:
    directory = directory or THEMES_DIR
    if not directory.is_dir():
        return []
    themes, seen = [], set()
    for path in sorted(directory.glob('*.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            print(f"[@routes:themes] skipped {path.name}: unreadable ({exc})")
            continue
        error = _validate(data)
        if error:
            print(f"[@routes:themes] skipped {path.name}: {error}")
            continue
        if data['id'] in seen or data['id'] in ('gold', 'custom'):
            print(f"[@routes:themes] skipped {path.name}: id '{data['id']}' is taken")
            continue
        seen.add(data['id'])
        themes.append(data)
    return themes


@server_themes_bp.route('', methods=['GET'])
@handle_route_exceptions('themes')
def list_themes():
    return jsonify({'success': True, 'themes': load_themes()})
