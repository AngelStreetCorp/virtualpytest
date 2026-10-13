"""Shared helpers for the TASK-49 route tests: a stand-in for report_snapshots_db when the real
module is not importable, and a tiny Flask app that fakes the global auth guard."""

import sys
import types

from flask import Flask, request

_DB_FUNCTIONS = (
    'create_snapshot', 'get_snapshot', 'list_snapshots', 'get_snapshot_by_key_hash',
    'get_snapshot_by_delete_key_hash', 'revoke_snapshot', 'revoke_snapshot_by_id', 'record_view',
    'list_purgeable', 'mark_purged', 'team_live_bytes', 'list_team_snapshots', 'get_script_summaries',
    'get_profile_names',
)


def ensure_snapshots_db_importable():
    """Tests monkeypatch every db function, so a stub with the section 7 names is enough."""
    name = 'shared.src.lib.database.report_snapshots_db'
    try:
        __import__(name)
        return
    except ImportError:
        pass
    stub = types.ModuleType(name)

    def _unpatched(*args, **kwargs):
        raise AssertionError('report_snapshots_db function called without a test patch')

    for fn in _DB_FUNCTIONS:
        setattr(stub, fn, _unpatched)
    stub.LIST_STATUSES = ('active', 'expired', 'revoked', 'all')
    sys.modules[name] = stub
    import shared.src.lib.database as package
    package.report_snapshots_db = stub


def make_app(blueprint):
    app = Flask(__name__)
    app.config['TESTING'] = True

    @app.before_request
    def _fake_auth():
        # Stands in for the global /server/* guard: headers choose the principal.
        request.user_role = request.headers.get('X-Test-Role', 'tester')
        request.user_id = request.headers.get('X-Test-User', '11111111-1111-4111-8111-111111111111')
        request.user_permissions = []
        request.user_denied_permissions = []
        request.user_team_ceiling = None

    app.register_blueprint(blueprint)
    return app
