"""
Virtual-scripts feature - backend_server part (docs/technical/FEATURES.md).

Registered by shared/src/lib/utils/features.py when the feature is enabled:
  /server/virtual-script/*  Virtual Scripts CRUD + validation + versions (server_virtual_script_routes)
Execution is core: a run carries `virtual_script_id` through the normal
/server/script/execute path (see docs/agent/execution/VIRTUAL_SCRIPTS.md).
"""
from .server_virtual_script_routes import server_virtual_script_bp


def register(app):
    app.register_blueprint(server_virtual_script_bp)
