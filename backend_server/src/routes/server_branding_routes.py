"""
Branding Routes - Runtime branding configuration (name, logo, favicon)

Persists to /var/tmp/vpt_branding.json with automatic backup to
/var/tmp/vpt_branding.backup.json before every save.

Endpoints:
  GET  /server/branding         — load current branding (no auth required)
  POST /server/branding         — save branding + create backup
  POST /server/branding/revert  — restore from backup
"""

import json
import os
import shutil
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

server_branding_bp = Blueprint('server_branding', __name__, url_prefix='/server/branding')

BRANDING_FILE   = '/var/tmp/vpt_branding.json'
BRANDING_BACKUP = '/var/tmp/vpt_branding.backup.json'

# Directories where uploaded logo/favicon files are saved so they're served as static assets.
# public/ is the source; dist/ is the built output served by Nginx in production.
# Both are written so the change takes effect immediately without a rebuild.
_FRONTEND_ROOT = os.path.join(os.getcwd(), 'frontend')
FRONTEND_PUBLIC_DIR = os.environ.get(
    'FRONTEND_PUBLIC_DIR',
    os.path.join(_FRONTEND_ROOT, 'public'),
)
FRONTEND_DIST_DIR = os.environ.get(
    'FRONTEND_DIST_DIR',
    os.path.join(_FRONTEND_ROOT, 'dist'),
)

_ALLOWED_KEYS = {'name', 'tagline', 'logoUrl', 'faviconUrl', 'title', 'showFooter'}
_ALLOWED_ASSET_NAMES = {'logo', 'favicon'}
_ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.ico', '.svg', '.webp', '.gif'}


def _load() -> dict:
    try:
        with open(BRANDING_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    # Backup current file before overwriting
    if os.path.exists(BRANDING_FILE):
        shutil.copy2(BRANDING_FILE, BRANDING_BACKUP)
    with open(BRANDING_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@server_branding_bp.route('', methods=['GET'])
@handle_route_exceptions('branding:load')
def load_branding():
    """Return persisted branding overrides (empty dict if none saved yet)."""
    return jsonify({'success': True, 'branding': _load()})


@server_branding_bp.route('', methods=['POST'])
@handle_route_exceptions('branding:save')
def save_branding():
    """
    Save branding overrides.  Only keys in _ALLOWED_KEYS are stored.
    Previous file is backed up automatically before writing.
    """
    data = request.get_json(silent=True) or {}
    filtered = {k: v for k, v in data.items() if k in _ALLOWED_KEYS}
    _save(filtered)
    has_backup = os.path.exists(BRANDING_BACKUP)
    return jsonify({'success': True, 'saved': filtered, 'backup_available': has_backup})


@server_branding_bp.route('/revert', methods=['POST'])
@handle_route_exceptions('branding:revert')
def revert_branding():
    """Restore the previous branding from backup."""
    if not os.path.exists(BRANDING_BACKUP):
        return jsonify({'success': False, 'error': 'No backup available'}), 404
    shutil.copy2(BRANDING_BACKUP, BRANDING_FILE)
    return jsonify({'success': True, 'branding': _load()})


@server_branding_bp.route('/backup', methods=['GET'])
@handle_route_exceptions('branding:backup')
def get_backup():
    """Return the backup branding (for preview before reverting)."""
    try:
        with open(BRANDING_BACKUP, 'r', encoding='utf-8') as f:
            backup = json.load(f)
        return jsonify({'success': True, 'branding': backup})
    except FileNotFoundError:
        return jsonify({'success': True, 'branding': None, 'message': 'No backup available'})


@server_branding_bp.route('/upload', methods=['POST'])
@handle_route_exceptions('branding:upload')
def upload_asset():
    """
    Upload a logo or favicon file and save it to the frontend public directory.

    Form fields:
      - file: the image file
      - asset: 'logo' or 'favicon' (determines output filename)

    Returns the public URL path (e.g. '/logo.png') so the frontend can store it in branding.
    """
    asset = request.form.get('asset', '').strip()
    if asset not in _ALLOWED_ASSET_NAMES:
        return jsonify({'success': False, 'error': f"asset must be one of {_ALLOWED_ASSET_NAMES}"}), 400

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'success': False, 'error': 'Empty filename'}), 400

    _, ext = os.path.splitext(secure_filename(file.filename))
    ext = ext.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return jsonify({'success': False, 'error': f"Extension {ext} not allowed"}), 400

    # Determine output filename: logo.png / logo.svg / favicon.ico / favicon.png etc.
    # Keep extension from uploaded file so browsers recognise the type.
    out_filename = f'{asset}{ext}'

    # Save to public/ (source) — always
    os.makedirs(FRONTEND_PUBLIC_DIR, exist_ok=True)
    out_path = os.path.join(FRONTEND_PUBLIC_DIR, out_filename)
    file.save(out_path)

    # Mirror to dist/ (Nginx-served output) if it exists so the change is live immediately
    written_to = [out_path]
    if os.path.isdir(FRONTEND_DIST_DIR):
        dist_path = os.path.join(FRONTEND_DIST_DIR, out_filename)
        shutil.copy2(out_path, dist_path)
        written_to.append(dist_path)

    return jsonify({'success': True, 'url': f'/{out_filename}', 'filename': out_filename, 'written_to': written_to})
