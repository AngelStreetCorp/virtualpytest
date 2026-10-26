"""Ticket model (TASK-96 "Ticket model and workflow"): the enums every layer shares.

One list per axis, validated on the server, mirrored by the form (frontend/ticketModel.ts) and by the
Zammad custom attributes that `setup_zammad.py` creates. Keys are stable ASCII; labels are the UI's job.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

TICKET_TYPES = ('incident', 'bug', 'request', 'question')
#: Types that carry a severity; Request and Question have none.
SEVERITY_TYPES = ('incident', 'bug')
SEVERITIES = ('blocker', 'major', 'minor')
FREQUENCIES = ('always', 'frequent', 'random', 'once')
#: Set by the reporter (default P1); required on every type.
PRIORITIES = ('P0', 'P1', 'P2')
DEFAULT_PRIORITY = 'P1'
#: priority -> Zammad's built-in ticket priority id (1 low, 2 normal, 3 high).
ZAMMAD_PRIORITY_ID = {'P0': 3, 'P1': 2, 'P2': 1}

#: family -> categories (the Family -> Category dropdowns).
FAMILIES: Dict[str, Tuple[str, ...]] = {
    'platform': ('server', 'host', 'device', 'service'),
    'scripting': ('script', 'campaign', 'virtual_script', 'testcase'),
    'monitoring': ('heatmap', 'timeline', 'incident'),
    'dashboards': ('grafana', 'report'),
    'ai': ('agent',),
}

#: (family, category) -> Zammad group. Category-level only where a family splits (Platform: Device).
_FAMILY_GROUPS = {
    'platform': 'Hosts & System',
    'scripting': 'Scripts',
    'monitoring': 'Hosts & System',
    'dashboards': 'Dashboards',
    'ai': 'Platform',
}
_CATEGORY_GROUPS = {('platform', 'device'): 'Devices'}
#: Every group a ticket can land in (setup_zammad.py checks they exist).
ALL_GROUPS = frozenset(_FAMILY_GROUPS.values()) | frozenset(_CATEGORY_GROUPS.values())

# Workflow statuses stored in support_tickets.status.
STATUSES = ('new', 'accepted', 'assigned', 'in_progress', 'need_info', 'fixed', 'delivered',
            'reopened', 'closed', 'duplicate', 'wont_fix')
STATUS_NEW = 'new'
STATUS_CLOSED = 'closed'
#: What "Closed" counts: the three terminal statuses.
CLOSED_STATUSES = ('closed', 'duplicate', 'wont_fix')

#: Reporter-facing status (one word the requester sees) per workflow status.
REPORTER_STATUS = {
    'new': 'open', 'accepted': 'open', 'assigned': 'open', 'reopened': 'open',
    'in_progress': 'in_progress', 'fixed': 'in_progress',
    'need_info': 'waiting',
    'delivered': 'delivered',
    'closed': 'closed', 'duplicate': 'closed', 'wont_fix': 'closed',
}

#: Zammad ticket state name -> our status. The custom states are created by setup_zammad.py.
ZAMMAD_STATE_TO_STATUS = {
    'new': 'new',
    'open': 'accepted',
    'accepted': 'accepted',
    'assigned': 'assigned',
    'in progress': 'in_progress',
    'need info': 'need_info',
    'pending reminder': 'need_info',
    'pending close': 'need_info',
    'fixed': 'fixed',
    'delivered': 'delivered',
    'reopened': 'reopened',
    'closed': 'closed',
    'duplicate': 'duplicate',
    "won't fix": 'wont_fix',
    'merged': 'duplicate',
    'removed': 'closed',
}
STATUS_TO_ZAMMAD_STATE = {
    'new': 'new', 'accepted': 'accepted', 'assigned': 'assigned', 'in_progress': 'in progress',
    'need_info': 'need info', 'fixed': 'fixed', 'delivered': 'delivered', 'reopened': 'reopened',
    'closed': 'closed', 'duplicate': 'duplicate', 'wont_fix': "won't fix",
}
#: Custom Zammad states to create: name -> state type name (new, open, pending reminder, closed).
CUSTOM_ZAMMAD_STATES = {
    'accepted': 'open', 'assigned': 'open', 'in progress': 'open', 'need info': 'pending reminder',
    'fixed': 'open', 'delivered': 'open', 'reopened': 'open', 'duplicate': 'closed', "won't fix": 'closed',
}


def map_status(zammad_state: Optional[str]) -> str:
    return ZAMMAD_STATE_TO_STATUS.get((zammad_state or '').strip().lower(), 'accepted')


def reporter_status(status: Optional[str]) -> str:
    return REPORTER_STATUS.get(status or '', 'open')


def group_for(family: str, category: str) -> str:
    group = _CATEGORY_GROUPS.get((family, category)) or _FAMILY_GROUPS.get(family)
    if not group:
        raise ValueError(f'unknown family: {family}')
    return group
