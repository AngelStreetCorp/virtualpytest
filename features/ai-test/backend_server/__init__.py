"""
AI-test feature - backend_server part (docs/technical/FEATURES.md).

Registered by shared/src/lib/utils/features.py when the feature is enabled:
  /server/testprompt/*      Test Prompt CRUD + execution (server_testprompt_routes)
The crawl_app MCP tool lives in mcp_tools/ (picked up by the MCP tool auto-discovery)
and the agent skills in ../skills/ (picked up by SkillLoader).
Virtual Scripts (/server/virtual-script/*) are a separate feature: features/virtual-scripts.
"""
from .server_testprompt_routes import server_testprompt_bp, register_testprompt_socketio


def register(app):
    app.register_blueprint(server_testprompt_bp)
    # Test Prompt reuses the /agent namespace to push live tool events to the
    # frontend while a run is in flight (app.socketio is set by create_flask_app).
    if hasattr(app, 'socketio'):
        register_testprompt_socketio(app.socketio)
