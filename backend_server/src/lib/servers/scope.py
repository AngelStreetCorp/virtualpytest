"""
``@supports_all_servers(merge)``: opt a ``/server/*`` GET route into ``?scope=all`` (TASK-179 P3).

``scope=all`` runs the view locally (in-process), asks every other server for the same path with ``scope=local``
(``fanout.all_servers``) and returns ``merge(local_json, self_row, results)``. Any other ``scope`` leaves the view
untouched, so a peer never fans out again. Place it directly above the view (below ``handle_route_exceptions``): the
global auth guard is a ``before_request``, so the caller is already authenticated when this runs.
"""

import functools
import os
import time
from typing import Any, Callable, Dict, List

from flask import jsonify, make_response, request

from backend_server.src.lib.servers import registry
from backend_server.src.lib.servers.fanout import NeedsSignedInUser, ServerResult, all_servers, credential_headers

Merge = Callable[[Dict[str, Any], Dict[str, Any], List[ServerResult]], Dict[str, Any]]

NOT_IN_LIST_WARNING = 'this server is not in the server list (check SERVER_NAME)'


def _self_row() -> Dict[str, Any]:
    me = (registry.self_name() or '').lower()
    for row in registry.servers():
        if me and row['name'].lower() == me:
            return dict(row)
    url = os.getenv('SERVER_URL', '')
    return {'name': registry.self_name() or 'this server',
            'url': (url if url.startswith(('http://', 'https://')) else request.host_url).rstrip('/'),
            'enabled': True, 'sort_order': 0}


def supports_all_servers(merge: Merge):
    def decorate(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if request.args.get('scope') != 'all':
                return view(*args, **kwargs)
            try:
                headers = credential_headers()
            except NeedsSignedInUser:
                return jsonify({'success': False,
                                'error': 'scope=all needs a signed-in user (Authorization Bearer or X-Auto-Sign); '
                                         'the service API key cannot act as a user on other servers'}), 403
            started = time.monotonic()
            local = make_response(view(*args, **kwargs))
            local_json = local.get_json(silent=True)
            if local.status_code >= 400 or not isinstance(local_json, dict):
                return local  # nothing to merge into: the local answer is the answer
            self_row = _self_row()
            self_row['latency_ms'] = int((time.monotonic() - started) * 1000)
            query = request.args.to_dict(flat=False)
            merged = merge(local_json, self_row, all_servers(request.path, query, headers=headers))
            if not registry.self_in_list():
                merged['warning'] = NOT_IN_LIST_WARNING
            return jsonify(merged), 200
        return wrapper
    return decorate
