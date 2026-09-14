"""
AI-test feature - backend_host part (docs/technical/FEATURES.md).

Registered by shared/src/lib/utils/features.py when the feature is enabled:
  /host/testprompt/execute  run a Test Prompt on a device (host_testprompt_routes)
  /host/crawl/app           BFS app crawl, web + Android (host_crawl_routes + app_crawler)
Runner hosts (HOST_TYPE=runner_*) only serve script execution, like routes/registry.py.
"""
import os


def register(app):
    if (os.getenv('HOST_TYPE', '') or '').startswith('runner_'):
        return
    from .host_testprompt_routes import host_testprompt_bp
    from .host_crawl_routes import host_crawl_bp
    app.register_blueprint(host_testprompt_bp)
    app.register_blueprint(host_crawl_bp)
