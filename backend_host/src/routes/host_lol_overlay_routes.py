"""
Host LoL overlay route: serves the live file the League of Legends bot rewrites every tick.

Contract: docs/agent/game/lol/OVERLAY_CONTRACT.md. The file lives on the Windows PC that runs the
bot (default C:\\virtualpytest\\lol-overlay-live.json, override with LOL_OVERLAY_LIVE_PATH); on any
other host the route answers data=null.
"""

import json
import os
import time

from flask import Blueprint, jsonify

from backend_host.src.lib.utils.route_decorators import route_exception_handler

host_lol_overlay_bp = Blueprint('host_lol_overlay', __name__, url_prefix='/host/lol-overlay')

DEFAULT_LIVE_PATH = r'C:\virtualpytest\lol-overlay-live.json'


@host_lol_overlay_bp.route('/live', methods=['GET'])
@route_exception_handler()
def live():
    path = os.environ.get('LOL_OVERLAY_LIVE_PATH', DEFAULT_LIVE_PATH)
    try:
        age_s = max(0.0, time.time() - os.path.getmtime(path))
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        # missing file, or caught mid-write (the bot renames atomically, so rare)
        return jsonify({'success': True, 'data': None, 'age_s': None})
    return jsonify({'success': True, 'data': data, 'age_s': age_s})
