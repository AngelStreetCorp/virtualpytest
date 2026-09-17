"""
OpenAPI Documentation Routes
Serves generated OpenAPI/Swagger documentation HTML files
"""

import os
from flask import Blueprint, send_from_directory
from pathlib import Path

# Create blueprint for OpenAPI documentation.
# /server/docs/api, not /docs/api: nginx proxies only /server/* to the backend, and /docs/api
# is already the frontend's own published docs site (frontend/public/docs/api, Swagger UI at
# /docs/api/interactive.html) — so the old prefix was both unreachable and shadowed.
server_openapi_bp = Blueprint('server_openapi', __name__, url_prefix='/server/docs/api')

# Get project root and docs directory
current_dir = Path(__file__).parent
backend_server_dir = current_dir.parent.parent
project_root = backend_server_dir.parent
docs_dir = project_root / 'docs' / 'api' / 'docs'

@server_openapi_bp.route('/docs/<path:filename>')
def serve_openapi_docs(filename):
    """Serve OpenAPI documentation HTML files"""
    try:
        return send_from_directory(str(docs_dir), filename)
    except FileNotFoundError:
        return {"error": "Documentation file not found"}, 404

@server_openapi_bp.route('/docs/')
@server_openapi_bp.route('/docs')
def serve_index():
    """Serve the main documentation index"""
    try:
        return send_from_directory(str(docs_dir), 'index.html')
    except FileNotFoundError:
        return {"error": "Documentation index not found. Run: python3 scripts/export_openapi_specs.py"}, 404
