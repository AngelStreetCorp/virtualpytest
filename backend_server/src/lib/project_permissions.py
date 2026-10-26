"""Project permission helpers (TASK-65 / BUG-0609).

The callers side of every project route answers two questions:

  1. "What is the caller's role on this project?" —
     `caller_project_role(project_id)` returns `'owner'`, `'viewer'`, or
     `None`. Admins return `None` here — they don't carry a project-scoped
     row; their editing authority is reported separately through
     `can_edit_project()`.

  2. "Can this caller write to this project?" —
     `can_edit_project(project_id)` returns `True` iff the caller is a
     team admin OR has a row in `projects_members` with `role='owner'`.

These two helpers are the single source of truth. Both the route layer
(`server_projects_routes.py`, `server_projects_in_scope_routes.py`, the
overview endpoint) and any future route module import them — they are
**never** inlined per route.

The `_caller_team_member_ids` private helper is also here because the ACL
is per team-member-row, not per Supabase auth user. The conversion
(auth.users.id → team_members.id) is cheap but non-trivial and used only
by these helpers.
"""

from flask import request

from backend_server.src.lib.auth_middleware import caller_is_admin
from shared.src.lib.database import projects_db


def _caller_team_member_ids() -> list:
    """The list of `team_members.id` rows for the current caller.

    `request.user_id` is the Supabase profile id (auth.uid); the junction
    uses `team_members.user_id`. The project ACL stores `team_members.id`,
    so we map once at the route layer.
    """
    user_id = getattr(request, 'user_id', None)
    if not user_id or user_id in ('auto_signed', 'service_api_key', 'open_mode', 'public_key'):
        return []
    return [t['id'] for t in projects_db.list_team_members_for_user(user_id)]


def _is_project_owner(project_id: str, caller_team_member_ids: list) -> bool:
    if not caller_team_member_ids:
        return False
    members = projects_db.list_project_members(project_id)
    member_ids = {m['team_member_id'] for m in members}
    if not (set(caller_team_member_ids) & member_ids):
        return False
    caller_roles = {m['role'] for m in members if m['team_member_id'] in caller_team_member_ids}
    return 'owner' in caller_roles


def can_edit_project(project_id: str) -> bool:
    """Team admin OR project owner. Returns True or False.

    Public helper — every write route that doesn't gate on a per-resource
    permission (rename / delete / add-member / remove-member / tag writes /
    link / unlink) calls this as its first check. The `server_projects`
    blueprint is the source of truth for the policy; route modules import
    this name, not the underlying helper.
    """
    if caller_is_admin():
        return True
    return _is_project_owner(project_id, _caller_team_member_ids())


def caller_project_role(project_id: str) -> str | None:
    """Caller's role on `project_id` — `'owner'`, `'viewer'`, or `None`.

    Public helper so the overview / executive endpoints can include a
    `my_role` + `can_edit` pair in their response without duplicating the
    `_is_project_owner` logic. `caller_is_admin()` returns `None` here:
    admins have no project-scoped row, and the editing rights they enjoy
    are reported separately through `can_edit_project()`.
    """
    caller_tm_ids = _caller_team_member_ids()
    if not caller_tm_ids:
        return None
    members = projects_db.list_project_members(project_id)
    roles = {m['role'] for m in members if m.get('team_member_id') in caller_tm_ids}
    if 'owner' in roles:
        return 'owner'
    if 'viewer' in roles:
        return 'viewer'
    return None


# ---------------------------------------------------------------------------
# Backward-compat re-exports
# ---------------------------------------------------------------------------
# The legacy route module `server_projects_routes` exposed the same two
# public helpers under the leading-underscore private prefix
# (`_can_edit_project`). Some tests / scripts import the old name. Keep
# the alias so the move doesn't break those callers. Remove once all
# imports are migrated.
_can_edit_project = can_edit_project
