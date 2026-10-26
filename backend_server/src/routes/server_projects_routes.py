"""
Projects Management Routes (TASK-65)
====================================

REST endpoints for the Projects feature. Mirrors `server_workspaces_routes.py`.

Endpoints
---------

  GET    /server/projects                       list every project the caller can see
  POST   /server/projects                       create a project (team:projects:create)
  GET    /server/projects/<id>                  one project with tags + members
  PATCH  /server/projects/<id>                  update (admin OR project owner)
  DELETE /server/projects/<id>                  delete (admin OR project owner)

  GET    /server/projects/<id>/members          list members with role
  POST   /server/projects/<id>/members          add a member (admin OR project owner)
  DELETE /server/projects/<id>/members/<mid>    remove (admin OR project owner)

  GET    /server/projects/<id>/tags             list tags owned by a project
  POST   /server/projects/<id>/tags             attach a tag (admin OR project owner)
  DELETE /server/projects/<id>/tags/<tag_id>    detach (admin OR project owner)

  GET    /server/projects/<id>/executables      scripts/testcases/virtual_scripts/campaigns
                                                tagged with the project (G9 — the project
                                                filter pipe the WorkspaceContext consumes)

Permission rules (Q4 = 1)
-------------------------

  * list / get / members / tags reads: caller is a team member of the project's
    team (the route layer scopes by `org_scope_team_ids`).
  * create: `team:projects:create` permission, scoped to one of the caller's teams.
  * update / delete / add-member / remove-member / tag writes: caller is
    `caller_is_admin()` OR has a row in `projects_members` with `role = 'owner'`
    for this project.
"""

import json
import logging

from flask import Blueprint, request, jsonify

from shared.src.lib.database import projects_db, teams_db
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions, require_team_id_from_body_or_args
from backend_server.src.lib.auth_middleware import (
    org_scope_team_ids,
    require_permission,
)
from backend_server.src.lib.project_permissions import (  # noqa: F401  re-exported for callers below
    can_edit_project,
    caller_project_role,
    _caller_team_member_ids,
)
# The write routes below call the underscore name; BUG-0609's extraction re-exported only the public one
# (NameError on every PATCH/DELETE/members/tags call). server_projects_in_scope_routes uses the same inline rename.
from backend_server.src.lib.project_permissions import can_edit_project as _can_edit_project  # noqa: F401


logger = logging.getLogger(__name__)


server_projects_bp = Blueprint('server_projects', __name__, url_prefix='/server/projects')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Permissions helpers were extracted to `backend_server.src.lib.project_permissions`
# in BUG-0609. They are re-exported at the top of this module so the
# `from backend_server.src.routes.server_projects_routes import can_edit_project`
# import path still works for callers / tests that were written before the move.


def _project_team_in_scope(project: dict) -> bool:
    """Project's team is inside the caller's org scope (or caller is admin)."""
    scope = org_scope_team_ids()
    if scope is None:
        return True
    return str(project.get('team_id')) in scope


def _not_in_scope_or_missing(project_id: str):
    """Return a 404 if the project is missing or outside the caller's scope.

    Returns a 2-tuple `(response_or_None, project_or_None)`. The first
    element is itself a 2-tuple `(jsonify_response, 404)` so the caller
    can do `if blocked: return blocked` and Flask respects the 404
    status. The earlier shape `(response, 404)` (without the outer
    wrapper) silently lost the status because the caller destructured it
    as `blocked, project = (response, 404)`. Keep the contract here.
    """
    project = projects_db.get_project(project_id)
    if project is None:
        return (jsonify({"error": "Project not found"}), 404), None
    if not _project_team_in_scope(project):
        return (jsonify({"error": "Project not found"}), 404), None
    return None, project


def _validate_color(color):
    """Colors must be #RRGGBB hex (the migration's CHECK). None is allowed.

    Returns the error string or None. The route layer wraps it in a Flask response.
    Keeping the validator pure lets the unit test exercise it without a Flask app.
    """
    if color is None:
        return None
    if not isinstance(color, str):
        return "'color' must be a hex string like '#FFB300'"
    if len(color) != 7 or not color.startswith('#'):
        return "'color' must be a hex string like '#FFB300'"
    try:
        int(color[1:], 16)
    except ValueError:
        return "'color' must be a hex string like '#FFB300'"
    return None


def _bad_color_response(color):
    """`(_validate_color(color), 400)` — kept inline so the routes stay terse."""
    msg = _validate_color(color)
    if msg:
        return jsonify({"error": msg}), 400
    return None


# ---------------------------------------------------------------------------
# M7 — audit log (shared helper)
# ---------------------------------------------------------------------------
def _audit_log(project_id: str, action: str, details: dict | None = None) -> None:
    """Emit a structured project-audit log line for a write operation.

    Format: `[PROJECT_AUDIT] project_id=<...> action=<...> actor=<user_id> details=<json>`

    The `[PROJECT_AUDIT]` prefix is grep-friendly; ops/alerts can parse it to
    build a per-project activity feed without an extra table. The action set is
    closed: `create`, `update`, `delete`, `add_member`, `remove_member`,
    `add_tag`, `remove_tag`. The `actor` is `request.user_id` if present,
    otherwise the auth-mode label (`auto_signed`, `service_api_key`, etc.).

    This is the G6 (M7) shared audit helper. The route layer never calls
    `logger.info` directly for project writes — they all funnel through here.
    """
    actor = getattr(request, 'user_id', None) or 'unknown'
    extra = json.dumps(details or {}, default=str, separators=(',', ':'))
    logger.info(
        "[PROJECT_AUDIT] project_id=%s action=%s actor=%s details=%s",
        project_id, action, actor, extra,
    )


# ---------------------------------------------------------------------------
# Routes — list / create / read / update / delete
# ---------------------------------------------------------------------------
@server_projects_bp.route('', methods=['GET'])
@handle_route_exceptions('server_projects:list_projects')
def list_projects():
    """List every project in the caller's teams."""
    scope = org_scope_team_ids()
    if scope is None:
        all_projects = []
        for t in teams_db.get_all_teams():
            all_projects.extend(projects_db.list_projects(t['id']))
        return jsonify(all_projects), 200

    out = []
    for team_id in sorted(scope):
        out.extend(projects_db.list_projects(str(team_id)))
    return jsonify(out), 200


@server_projects_bp.route('', methods=['POST'])
@require_permission('team:projects:create')
@handle_route_exceptions('server_projects:create_project')
def create_project():
    """Create a project. Caller must hold `team:projects:create` in one of their teams.

    Body (G11 extensions — backward compatible):
        {
          'name':     str,            # required
          'color':    '#RRGGBB' | None,
          'description': str | None,
          'team_id':  str,            # optional — falls back to caller's first team
          'tags':     [str, ...],     # optional initial user-attached tags (BUG-0523);
                                       # the scope tag is auto-created and excluded
          'members':  [{team_member_id, role}, ...]   # optional initial extra members
        }
    The creator is auto-added as 'owner' regardless of payload (BUG-0522 fix —
    the row was being silently dropped before, leaving new projects at 0 members).
    """
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"error": "Project name is required"}), 400

    color_block = _bad_color_response(data.get('color'))
    if color_block:
        return color_block

    # The frontend sends team_id on the query string (buildServerUrl); accept body too.
    team_id, err = require_team_id_from_body_or_args()
    scope = org_scope_team_ids()
    if scope is not None and not err:
        if str(team_id) not in scope:
            return jsonify({"error": "team_id is not in your scope"}), 403
    if scope is not None and err:
        # Default to the first team the caller belongs to (TASK-31).
        team_ids = sorted(scope)
        if not team_ids:
            return jsonify({"error": "No team in your scope"}), 403
        team_id = team_ids[0]
    elif err:
        return err

    # Resolve the creator's `team_members.id` UUID (BUG-0522).
    # The FK on `projects.created_by` is `profiles.id`, but the FK on
    # `projects_members.team_member_id` is `team_members.id`. The OLD code passed
    # `request.user_id` (a profile.id) into BOTH — which broke the projects_members
    # insert and left every new project at "0 members". We now resolve the caller's
    # team_member row explicitly so the auto-add-as-owner INSERT succeeds.
    request_user_id = getattr(request, 'user_id', None)
    caller_tm_ids = _caller_team_member_ids()
    if caller_tm_ids:
        creator_team_member_id = str(caller_tm_ids[0])
    else:
        # Service-key / auto-signed / open mode callers pick the first row in the team.
        first = projects_db.list_team_members_for_team(str(team_id))
        if not first:
            return jsonify({"error": "No team member to assign as owner"}), 500
        creator_team_member_id = str(first[0]['id'])

    # G11 — accept initial user tags + initial extra members in one flow.
    initial_user_tags = data.get('tags')
    if initial_user_tags is not None and not isinstance(initial_user_tags, list):
        return jsonify({"error": "'tags' must be a list of strings"}), 400
    if initial_user_tags is not None:
        cleaned = []
        for t in initial_user_tags:
            if not isinstance(t, str):
                return jsonify({"error": "'tags' entries must be strings"}), 400
            label = t.strip().lower()
            if label and label not in cleaned:
                cleaned.append(label)
        initial_user_tags = cleaned

    initial_members = data.get('members')
    if initial_members is not None and not isinstance(initial_members, list):
        return jsonify({"error": "'members' must be a list of {team_member_id, role}"}), 400
    if initial_members is not None:
        validated = []
        for m in initial_members:
            if not isinstance(m, dict):
                return jsonify({"error": "'members' entries must be objects"}), 400
            tm_id = m.get('team_member_id')
            role = m.get('role', 'viewer')
            if not tm_id:
                return jsonify({"error": "'members[].team_member_id' is required"}), 400
            if role not in ('owner', 'viewer'):
                return jsonify({"error": "'members[].role' must be 'owner' or 'viewer'"}), 400
            validated.append({'team_member_id': str(tm_id), 'role': role})
        initial_members = validated

    try:
        project = projects_db.create_project(
            team_id=str(team_id),
            name=name,
            description=data.get('description'),
            color=data.get('color'),
            created_by_team_member_id=creator_team_member_id,
            initial_user_tags=initial_user_tags,
            initial_members=initial_members,
        )
    except projects_db.ProjectDuplicateError as e:
        return jsonify({"error": str(e), "name": e.name}), 409
    except Exception as e:
        logger.error("[@server_projects] create_project error: %s", e)
        return jsonify({"error": "Failed to create project"}), 500

    if not project:
        return jsonify({"error": "Failed to create project"}), 500
    logger.info("Project created: %s (team %s)", project['id'], team_id)
    _audit_log(project['id'], 'create', {
        'team_id': str(team_id),
        'name': name,
        'color': data.get('color'),
        'initial_user_tags': list(initial_user_tags) if initial_user_tags else [],
        'initial_members': list(initial_members) if initial_members else [],
    })
    return jsonify(project), 201


@server_projects_bp.route('/<project_id>', methods=['GET'])
@handle_route_exceptions('server_projects:get_project')
def get_project(project_id: str):
    """One project. Returns 404 if outside scope."""
    blocked, project = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    return jsonify(project), 200


@server_projects_bp.route('/<project_id>', methods=['PATCH'])
@handle_route_exceptions('server_projects:update_project')
def update_project(project_id: str):
    """Update a project. Caller must be admin OR a project owner."""
    blocked, project = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    if not _can_edit_project(project_id):
        return jsonify({"error": "Forbidden", "message": "Only admins and project owners can update a project"}), 403

    data = request.get_json() or {}
    if not data:
        return jsonify({"error": "No data provided"}), 400

    fields = {}
    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        fields['name'] = name
    if 'description' in data:
        fields['description'] = data['description']
    if 'color' in data:
        color_block = _bad_color_response(data['color'])
        if color_block:
            return color_block
        fields['color'] = data['color']

    try:
        updated = projects_db.update_project(project_id, fields)
    except projects_db.ProjectDuplicateError as e:
        return jsonify({"error": str(e), "name": e.name}), 409
    if updated is None:
        return jsonify({"error": "Failed to update project"}), 500
    logger.info("Project updated: %s", project_id)
    _audit_log(project_id, 'update', {'fields': list(fields.keys())})
    return jsonify(updated), 200


@server_projects_bp.route('/<project_id>', methods=['DELETE'])
@handle_route_exceptions('server_projects:delete_project')
def delete_project(project_id: str):
    """Delete a project. Caller must be admin OR a project owner."""
    blocked, _ = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    if not _can_edit_project(project_id):
        return jsonify({"error": "Forbidden", "message": "Only admins and project owners can delete a project"}), 403
    ok = projects_db.delete_project(project_id)
    if not ok:
        return jsonify({"error": "Failed to delete project"}), 500
    logger.info("Project deleted: %s", project_id)
    _audit_log(project_id, 'delete', {'team_id': str(_['team_id']) if _ else None})
    return jsonify({"message": "Project deleted successfully"}), 200


# ---------------------------------------------------------------------------
# Routes — members
# ---------------------------------------------------------------------------
@server_projects_bp.route('/<project_id>/members', methods=['GET'])
@handle_route_exceptions('server_projects:get_project_members')
def get_project_members(project_id: str):
    blocked, _ = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    return jsonify(projects_db.list_project_members(project_id)), 200


@server_projects_bp.route('/<project_id>/members', methods=['POST'])
@handle_route_exceptions('server_projects:add_project_member')
def add_project_member(project_id: str):
    blocked, _ = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    if not _can_edit_project(project_id):
        return jsonify({"error": "Forbidden", "message": "Only admins and project owners can manage members"}), 403

    data = request.get_json() or {}
    team_member_id = data.get('team_member_id')
    role = data.get('role', 'viewer')
    if not team_member_id:
        return jsonify({"error": "team_member_id is required"}), 400
    if role not in ('owner', 'viewer'):
        return jsonify({"error": "role must be 'owner' or 'viewer'"}), 400
    try:
        member = projects_db.add_project_member(project_id, team_member_id, role)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not member:
        return jsonify({"error": "Failed to add project member"}), 500
    logger.info("Added team_member %s to project %s as %s", team_member_id, project_id, role)
    _audit_log(project_id, 'add_member', {
        'team_member_id': str(team_member_id),
        'role': role,
    })
    return jsonify(member), 201


@server_projects_bp.route('/<project_id>/members/<team_member_id>', methods=['DELETE'])
@handle_route_exceptions('server_projects:remove_project_member')
def remove_project_member(project_id: str, team_member_id: str):
    blocked, _ = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    if not _can_edit_project(project_id):
        return jsonify({"error": "Forbidden", "message": "Only admins and project owners can manage members"}), 403
    ok = projects_db.remove_project_member(project_id, team_member_id)
    if not ok:
        return jsonify({"error": "Failed to remove project member"}), 500
    logger.info("Removed team_member %s from project %s", team_member_id, project_id)
    _audit_log(project_id, 'remove_member', {'team_member_id': str(team_member_id)})
    return jsonify({"message": "Project member removed successfully"}), 200


# ---------------------------------------------------------------------------
# Routes — tags
# ---------------------------------------------------------------------------
@server_projects_bp.route('/<project_id>/tags', methods=['GET'])
@handle_route_exceptions('server_projects:get_project_tags')
def get_project_tags(project_id: str):
    blocked, _ = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    return jsonify(projects_db.list_project_tags(project_id)), 200


@server_projects_bp.route('/<project_id>/tags', methods=['POST'])
@handle_route_exceptions('server_projects:add_project_tag')
def add_project_tag(project_id: str):
    blocked, _ = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    if not _can_edit_project(project_id):
        return jsonify({"error": "Forbidden", "message": "Only admins and project owners can manage tags"}), 403

    data = request.get_json() or {}
    tag_id = data.get('tag_id')
    if not isinstance(tag_id, int):
        return jsonify({"error": "tag_id (int) is required"}), 400
    ok = projects_db.add_project_tag(project_id, tag_id)
    if not ok:
        return jsonify({"error": "Failed to add project tag"}), 500
    _audit_log(project_id, 'add_tag', {'tag_id': tag_id})
    return jsonify({"tag_id": tag_id, "project_id": project_id}), 201


@server_projects_bp.route('/<project_id>/tags/<int:tag_id>', methods=['DELETE'])
@handle_route_exceptions('server_projects:remove_project_tag')
def remove_project_tag(project_id: str, tag_id: int):
    blocked, _ = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    if not _can_edit_project(project_id):
        return jsonify({"error": "Forbidden", "message": "Only admins and project owners can manage tags"}), 403
    ok = projects_db.remove_project_tag(project_id, tag_id)
    if not ok:
        return jsonify({"error": "Failed to remove project tag"}), 500
    _audit_log(project_id, 'remove_tag', {'tag_id': tag_id})
    return jsonify({"message": "Project tag removed successfully"}), 200


# ---------------------------------------------------------------------------
# Routes — active users (Q3)
# ---------------------------------------------------------------------------
@server_projects_bp.route('/<project_id>/active-users', methods=['GET'])
@handle_route_exceptions('server_projects:get_project_active_users')
def get_project_active_users(project_id: str):
    """Members of the project's team who have pinged within 5 min.

    A user being active is a team property (the heartbeat updates every
    team_members row for that user), not a project property — so this route
    counts active users of the project's team. The frontend then narrows by
    project membership if needed.
    """
    blocked, project = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked
    users = projects_db.list_active_users(project['team_id'])
    return jsonify({'active_users': users, 'count': len(users)}), 200


# ---------------------------------------------------------------------------
# G9 — Executables tagged with the project (the project filter pipe)
# ---------------------------------------------------------------------------
@server_projects_bp.route('/<project_id>/executables', methods=['GET'])
@handle_route_exceptions('server_projects:get_project_executables')
def get_project_executables_route(project_id: str):
    """Every executable tagged with this project, grouped by type.

    Used by the G9 frontend to scope every script / testcase / virtual
    script / campaign list. Team-filtered (the inner `in_` query joins
    through the project's team so a different team cannot see this team's
    project). React-query caches this per project id; the g9-selectors
    sub-agent wires the call site.

    Response shape:
        {
          "scripts":         [{"id": "s_web_1", "name": "s_web_1"}, ...],
          "testcases":       [{"id": "tc_foo",  "name": "TC_FOO"},   ...],
          "virtual_scripts": [{"id": "vs_a",    "name": "SC_NAV_01"}, ...],
          "campaigns":       [{"id": "camp_x",  "name": "Smoke"},     ...],
          "tag_names":       ["web_app"],
          "project_id":      "..."
        }
    """
    blocked, project = _not_in_scope_or_missing(project_id)
    if blocked:
        return blocked

    payload = projects_db.get_project_executables(project_id, str(project['team_id']))
    payload['tag_names'] = [t.get('name') for t in (project.get('tags') or []) if t.get('name')]
    payload['project_id'] = project_id
    return jsonify(payload), 200