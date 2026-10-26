"""Custom pages: saved block layouts a user builds by hand or by asking Atlas (TASK-139).

    GET    /server/custom-pages?team_id=               pages I may open (mine, shared with me, team-wide)
    GET    /server/custom-pages/catalogue?team_id=     blocks I may use, and the locked ones with the reason
    POST   /server/custom-pages                        {team_id, title, definition?, status?}
    GET    /server/custom-pages/<id>?team_id=          page + definition + per-block locked state for me
    PATCH  /server/custom-pages/<id>                   {team_id, title?, definition? | ops?, status?}
    DELETE /server/custom-pages/<id>?team_id=          owner only
    GET    /server/custom-pages/<id>/sharing?team_id=  owner only: visibility, team members, blocks each would see locked
    PUT    /server/custom-pages/<id>/sharing           owner only: {team_id, visibility, shares:[{user_id, can_edit}]}

A page is data (catalogue blocks), validated against ``services/custom_pages/catalogue.py`` on save and
load. Opening needs ``pages.custom:view``; create / edit / share need ``pages.custom:edit``. A block is
accepted only when the caller holds its own permission, so a page never reaches more than its author could.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from backend_server.src.lib.auth_middleware import principal_holds_permission, require_permission, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.services.analytics.scope import (
    actor_id,
    error_json,
    handle_scope_errors,
    json_body,
    require_uuid,
    resolve_team_id,
)
from backend_server.src.services.custom_pages import catalogue, service
from backend_server.src.services.custom_pages.catalogue import DefinitionError

server_custom_pages_bp = Blueprint('server_custom_pages', __name__, url_prefix='/server/custom-pages')


def _definition_errors(f):
    import functools

    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except DefinitionError as e:
            return jsonify(e.to_dict()), e.status
    return wrapped


_BODY_KEYS = {'team_id', 'title', 'definition', 'ops', 'status'}


@server_custom_pages_bp.route('', methods=['GET'])
@handle_route_exceptions('custom_pages:list')
@require_user_auth
@require_permission('pages.custom:view')
@handle_scope_errors
def list_pages():
    return jsonify({'items': service.list_pages(resolve_team_id(), actor_id(), principal_holds_permission)})


@server_custom_pages_bp.route('/catalogue', methods=['GET'])
@handle_route_exceptions('custom_pages:catalogue')
@require_user_auth
@require_permission('pages.custom:view')
@handle_scope_errors
def get_catalogue():
    resolve_team_id()
    return jsonify({**catalogue.catalogue_for(principal_holds_permission), 'grid_columns': catalogue.GRID_COLUMNS,
                    'schema_version': catalogue.SCHEMA_VERSION})


@server_custom_pages_bp.route('', methods=['POST'])
@handle_route_exceptions('custom_pages:create')
@require_user_auth
@require_permission('pages.custom:edit')
@handle_scope_errors
@_definition_errors
def create_page():
    team_id = resolve_team_id()
    body = json_body()
    unknown = set(body) - _BODY_KEYS
    if unknown:
        return error_json(f'unexpected fields: {", ".join(sorted(unknown))}', 400)
    page = service.create_page(team_id, actor_id(), principal_holds_permission, title=body.get('title'),
                               definition=body.get('definition'), status=body.get('status') or 'saved')
    return jsonify(page), 201


@server_custom_pages_bp.route('/<page_id>', methods=['GET'])
@handle_route_exceptions('custom_pages:get')
@require_user_auth
@require_permission('pages.custom:view')
@handle_scope_errors
def get_page(page_id: str):
    page = service.get_page(resolve_team_id(), actor_id(), require_uuid(page_id, 'page_id'), principal_holds_permission)
    return jsonify(page) if page else error_json('page not found', 404)


@server_custom_pages_bp.route('/<page_id>', methods=['PATCH'])
@handle_route_exceptions('custom_pages:update')
@require_user_auth
@require_permission('pages.custom:edit')
@handle_scope_errors
@_definition_errors
def update_page(page_id: str):
    team_id = resolve_team_id()
    body = json_body()
    unknown = set(body) - _BODY_KEYS
    if unknown:
        return error_json(f'unexpected fields: {", ".join(sorted(unknown))}', 400)
    page = service.update_page(team_id, actor_id(), require_uuid(page_id, 'page_id'), principal_holds_permission,
                               title=body.get('title'), definition=body.get('definition'), ops=body.get('ops'),
                               status=body.get('status'))
    return jsonify(page) if page else error_json('page not found', 404)


@server_custom_pages_bp.route('/<page_id>', methods=['DELETE'])
@handle_route_exceptions('custom_pages:delete')
@require_user_auth
@require_permission('pages.custom:edit')
@handle_scope_errors
def delete_page(page_id: str):
    if not service.delete_page(resolve_team_id(), actor_id(), require_uuid(page_id, 'page_id')):
        return error_json('page not found', 404)
    return jsonify({'deleted': True, 'id': page_id})


@server_custom_pages_bp.route('/<page_id>/sharing', methods=['GET'])
@handle_route_exceptions('custom_pages:sharing_get')
@require_user_auth
@require_permission('pages.custom:edit')
@handle_scope_errors
def get_sharing(page_id: str):
    team_id = resolve_team_id()
    page = service.get_page(team_id, actor_id(), require_uuid(page_id, 'page_id'), principal_holds_permission)
    if not page or page['access'] != 'owner':
        return error_json('page not found', 404)
    return jsonify(service.sharing_view(team_id, page))


@server_custom_pages_bp.route('/<page_id>/sharing', methods=['PUT'])
@handle_route_exceptions('custom_pages:sharing_set')
@require_user_auth
@require_permission('pages.custom:edit')
@handle_scope_errors
@_definition_errors
def set_sharing(page_id: str):
    team_id = resolve_team_id()
    body = json_body()
    view = service.set_sharing(team_id, actor_id(), require_uuid(page_id, 'page_id'),
                               visibility=body.get('visibility'), shares=body.get('shares', []))
    return jsonify(view) if view else error_json('page not found', 404)
