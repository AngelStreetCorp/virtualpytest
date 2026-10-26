"""Custom pages: who may do what, shared by the HTTP routes and the Atlas tools (TASK-139).

Access to a page: ``owner`` (full), ``edit`` / ``view`` (a named share), ``view`` (saved page with team
visibility). A draft (built by Atlas, not saved yet) belongs to its owner alone. Everything is scoped by
``team_id``. Writing a block needs the caller to hold the block's permission (catalogue.normalize_definition).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from backend_server.src.services.custom_pages import catalogue
from backend_server.src.services.custom_pages.catalogue import DefinitionError, Holds
from shared.src.lib.database import custom_pages_db, teams_db

STATUSES = ('draft', 'saved')
VISIBILITIES = ('private', 'team')
TITLE_MAX = catalogue.TITLE_MAX


def check_title(raw: Any) -> str:
    title = raw.strip() if isinstance(raw, str) else ''
    if not 1 <= len(title) <= TITLE_MAX:
        raise DefinitionError(f'title is required (1..{TITLE_MAX} characters)')
    return title


def access_for(page: Dict[str, Any], team_id: str, user_id: str) -> Optional[str]:
    """'owner' | 'edit' | 'view' | None."""
    if str(page.get('team_id')) != team_id:
        return None
    if page.get('owner_id') == user_id:
        return 'owner'
    if page.get('status') != 'saved':
        return None
    share = custom_pages_db.get_share(team_id, page['id'], user_id)
    if share:
        return 'edit' if share.get('can_edit') else 'view'
    return 'view' if page.get('visibility') == 'team' else None


def present(page: Dict[str, Any], access: str, holds: Holds, *, with_definition: bool = True) -> Dict[str, Any]:
    out = {
        'id': page['id'], 'title': page['title'], 'owner_id': page['owner_id'], 'status': page['status'],
        'visibility': page['visibility'], 'access': access,
        'created_at': page.get('created_at'), 'updated_at': page.get('updated_at'),
    }
    definition = page.get('definition') or {}
    out['block_count'] = len(definition.get('blocks') or [])
    if with_definition:
        out['definition'] = definition
        out['block_states'] = catalogue.block_states(definition, holds)
    return out


def list_pages(team_id: str, user_id: str, holds: Holds) -> List[Dict[str, Any]]:
    items = []
    for page in custom_pages_db.list_visible_pages(team_id, user_id):
        access = access_for(page, team_id, user_id)
        if access:
            items.append(present(page, access, holds, with_definition=False))
    return items


def get_page(team_id: str, user_id: str, page_id: str, holds: Holds) -> Optional[Dict[str, Any]]:
    page = custom_pages_db.get_page(team_id, page_id)
    access = access_for(page, team_id, user_id) if page else None
    return present(page, access, holds) if page and access else None


def create_page(team_id: str, user_id: str, holds: Holds, *, title: Any, definition: Any = None,
                status: str = 'saved') -> Dict[str, Any]:
    if status not in STATUSES:
        raise DefinitionError(f"status must be one of {', '.join(STATUSES)}")
    normalized = catalogue.normalize_definition(definition if definition is not None else catalogue.empty_definition(),
                                                holds=holds)
    page = custom_pages_db.create_page(team_id, user_id, title=check_title(title),
                                       schema_version=catalogue.SCHEMA_VERSION, definition=normalized, status=status)
    return present(page, 'owner', holds)


def update_page(team_id: str, user_id: str, page_id: str, holds: Holds, *, title: Any = None,
                definition: Any = None, ops: Any = None, status: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """None when the page does not exist or the caller cannot see it; DefinitionError(403) when view-only."""
    page = custom_pages_db.get_page(team_id, page_id)
    access = access_for(page, team_id, user_id) if page else None
    if not page or not access:
        return None
    if access == 'view':
        raise DefinitionError('you can view this page but not change it', status=403)
    changes: Dict[str, Any] = {}
    if title is not None:
        changes['title'] = check_title(title)
    if definition is not None and ops is not None:
        raise DefinitionError('send either definition or ops, not both')
    if definition is not None or ops is not None:
        base = page['definition']
        target = definition if definition is not None else catalogue.apply_ops(base, ops)
        changes['definition'] = catalogue.normalize_definition(target, previous=base, holds=holds)
        changes['schema_version'] = catalogue.SCHEMA_VERSION
    if status is not None:
        if status not in STATUSES:
            raise DefinitionError(f"status must be one of {', '.join(STATUSES)}")
        if access != 'owner':
            raise DefinitionError('only the owner can save or unsave a page', status=403)
        changes['status'] = status
    if not changes:
        raise DefinitionError('nothing to update')
    row = custom_pages_db.update_page(team_id, page_id, changes)
    return present(row, access, holds) if row else None


def delete_page(team_id: str, user_id: str, page_id: str) -> bool:
    page = custom_pages_db.get_page(team_id, page_id)
    if not page or page.get('owner_id') != user_id:
        return False
    return custom_pages_db.delete_page(team_id, page_id)


# ---------------------------------------------------------------- sharing

def holds_for_user(user_id: str) -> Optional[Holds]:
    """The permission test of another user (their role, grants, denials and team ceiling), or None if unknown."""
    from backend_server.src.routes.server_permissions_routes import _compute_effective
    from shared.src.lib.database import users_db
    user = users_db.get_user(user_id)
    if not user:
        return None
    effective = set(_compute_effective(user)['effective'])
    return lambda permission: permission in effective


def sharing_view(team_id: str, page: Dict[str, Any]) -> Dict[str, Any]:
    """Visibility, named shares and the team's members, each with how many of the page's blocks they would see locked."""
    definition = page.get('definition') or {}
    shares = {s['user_id']: s for s in custom_pages_db.list_shares(team_id, page['id'])}
    team = teams_db.get_team_members(team_id)
    holds_by_user = {str(m.get('user_id')): holds_for_user(str(m.get('user_id'))) for m in team if m.get('user_id')}
    members = []
    for m in team:
        user_id = str(m.get('user_id') or '')
        if not user_id or user_id == page['owner_id']:
            continue
        holds = holds_by_user.get(user_id)
        share = shares.get(user_id)
        members.append({
            'user_id': user_id, 'name': m.get('full_name') or m.get('email') or user_id[:8], 'email': m.get('email'),
            'role': m.get('role'), 'shared': bool(share), 'can_edit': bool(share and share.get('can_edit')),
            'locked_blocks': catalogue.locked_count(definition, holds) if holds else None,
        })
    return {
        'visibility': page['visibility'], 'status': page['status'], 'block_count': len(definition.get('blocks') or []),
        'members': members,
        'team_locked_max': max((catalogue.locked_count(definition, h) for h in holds_by_user.values() if h), default=0),
    }


def set_sharing(team_id: str, user_id: str, page_id: str, *, visibility: Any, shares: Any) -> Optional[Dict[str, Any]]:
    page = custom_pages_db.get_page(team_id, page_id)
    if not page or page.get('owner_id') != user_id:
        return None
    if visibility not in VISIBILITIES:
        raise DefinitionError(f"visibility must be one of {', '.join(VISIBILITIES)}")
    if not isinstance(shares, list):
        raise DefinitionError('shares must be a list of {user_id, can_edit}')
    members = {str(m.get('user_id')) for m in teams_db.get_team_members(team_id)}
    clean: Dict[str, Dict[str, Any]] = {}
    for item in shares:
        target = str(item.get('user_id') or '') if isinstance(item, dict) else ''
        if target not in members:
            raise DefinitionError(f'{target or "a share"} is not a member of this team')
        if target != user_id:
            clean[target] = {'user_id': target, 'can_edit': bool(item.get('can_edit'))}
    if page.get('status') != 'saved' and (clean or visibility == 'team'):
        raise DefinitionError('save the page before sharing it')
    custom_pages_db.update_page(team_id, page_id, {'visibility': visibility})
    custom_pages_db.replace_shares(team_id, page_id, list(clean.values()))
    return sharing_view(team_id, custom_pages_db.get_page(team_id, page_id))
