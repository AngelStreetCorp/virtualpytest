"""Host monitor-profile routes (TASK-90 follow-up): which profiles this host offers and what the last apply did.

Read-only. Changing a profile is a normal save of MONITOR_PROFILE / DEVICE<N>_MONITOR_PROFILE through
POST /host/system/config, which starts apply_monitor_profiles(); the outcome is read here.
"""
import re

from flask import Blueprint, jsonify

from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils import monitor_profile as mp
from shared.src.lib.utils.monitor_profile import read_env_files

host_monitor_profile_bp = Blueprint('host_monitor_profile', __name__, url_prefix='/host/monitor')


@host_monitor_profile_bp.route('/profiles', methods=['GET'])
@route_exception_handler()
def list_monitor_profiles():
    env = read_env_files(re.compile(r'^(DEVICE\d+_)?MONITOR_PROFILE$'))
    return jsonify({
        'success': True,
        'profiles': mp.list_profiles(),
        'default': (env.get('MONITOR_PROFILE') or '').strip() or 'tv_app',
        'units': mp.unit_states(),
    }), 200


@host_monitor_profile_bp.route('/profiles/status', methods=['GET'])
@route_exception_handler()
def monitor_profiles_status():
    desired = mp._desired_state()
    previous = mp._read_state()
    saved = desired['profiles']
    applied = (previous or {}).get('profiles')
    mismatch = sorted(d for d in saved if applied is not None and applied.get(d) != saved[d])
    return jsonify({
        'success': True,
        'saved': saved,
        'applied': applied,
        'mismatch': mismatch,
        'result': mp.read_apply_result(),
        'units': mp.unit_states(),
    }), 200
