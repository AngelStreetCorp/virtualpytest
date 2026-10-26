"""
Binds the AI caller context (``shared/src/lib/ai/caller.py``, TASK-87) for every /server/* request.

- A signed-in user's request is origin ``ui`` with their user id and the route.
- A request made with the shared service key is origin ``api`` — unless the holder is a host or
  script forwarding who really asked: its ``X-VPT-Caller`` header (``server_auth_headers``) refines it. A header
  that names a host but no origin is that host's own work: ``monitoring``. ``api`` is left for real external
  callers only. The service key is the trust boundary: only a holder of it can set attribution.
- The context is cleared when the request ends.
- ``X-Project-Id`` is read for both signed-in and forwarded requests (BUG-0559): every AI
  call attributed by the gateway is tagged with the project the user is working on, so the
  per-project spend can be computed from the per-call table.
"""

from flask import request

from shared.src.lib.ai import caller as ai_caller

PROJECT_HEADER = "X-Project-Id"


def install_ai_caller_binding(app) -> None:
    @app.before_request
    def _bind_ai_caller():
        path = request.path or ''
        if request.method == 'OPTIONS' or not path.startswith('/server/'):
            return None
        role = getattr(request, 'user_role', None)
        service = role == 'service'
        fields = {'origin': 'api' if service else 'ui'}
        if not service:
            fields.update(route=path, user_id=getattr(request, 'user_id', None))
        else:
            forwarded = ai_caller.parse_header(request.headers.get(ai_caller.HEADER))
            # A host forwarding a call of its own (localize second opinion, triage) names itself with
            # host_name but has no entry-point origin: that is monitoring, not an external API caller (BUG-0496).
            if forwarded.get('host_name') and not forwarded.get('origin'):
                forwarded['origin'] = 'monitoring'
            fields.update(forwarded)
        # Project: the frontend sets X-Project-Id whenever a project is active in the
        # top-bar ProjectSelector (TASK-65 G5). MCP tools also forward it. We pick it up
        # here so every AI call attributed by this process picks up the project tag for
        # free; the call log row carries it through to ai_calls.project_id.
        pid = request.headers.get(PROJECT_HEADER) or request.headers.get(PROJECT_HEADER.lower())
        if pid:
            fields['project_id'] = pid.strip()[:64]
        ai_caller.clear()
        ai_caller.bind(**fields)
        return None

    @app.teardown_request
    def _clear_ai_caller(_exc):
        ai_caller.clear()
