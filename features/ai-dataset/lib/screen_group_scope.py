"""Screen groups of the dataset's apps (TASK-27 step 4k): the feature side of core
``shared/src/lib/ai/screen_groups.py``.

* ``SCREEN_GROUP_OVERRIDES`` / ``overrides_for``: re-exported from core
  ``shared/src/lib/ai/screen_groups.py``, where the human override data lives, so the
  navigation hook and these scripts group with the same overrides.
* ``load_app_graph`` / ``groups_for``: read one app's whole tree hierarchy (root and nested,
  the same DB path as the navigation executor and the review dropdown) and derive its
  groups. Read-only and team-scoped.
* ``GroupCache``: one derivation per (team, userinterface) per process.
* ``screen_entries``: the ``[{node_id, label}]`` a ``screen-id`` prompt lists (group names).

The one place the scripts (``score_eval``, ``triage_batch``, ``export_dataset``,
``seed_from_trees``, ``regroup_screen_labels``, ``recompute_conflicts``), the coverage and the
``/screen-groups`` route get their groups from.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple  # noqa: F401

from shared.src.lib.ai import screen_groups as core_groups

# Step 4k: the override data lives in core (one source for the navigation hook and these
# scripts); this module only re-exports it.
SCREEN_GROUP_OVERRIDES = core_groups.SCREEN_GROUP_OVERRIDES
overrides_for = core_groups.overrides_for


def load_app_graph(team_id: str, userinterface: str) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """``(node rows, edge rows)`` of the userinterface's whole tree hierarchy, or None when
    it has no userinterface or no root tree. Read-only."""
    from shared.src.lib.database.navigation_trees_db import (
        get_complete_tree_hierarchy, get_root_tree_for_interface)
    from shared.src.lib.database.userinterface_db import get_userinterface_by_name

    ui = (get_userinterface_by_name(userinterface, team_id)
          or get_userinterface_by_name(userinterface, team_id, mode='prod'))
    root = get_root_tree_for_interface(ui['id'], team_id) if ui else None
    if not root:
        return None
    hierarchy = get_complete_tree_hierarchy(root['id'], team_id)
    if not hierarchy.get('success'):
        return None
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    for tree in hierarchy.get('all_trees_data') or []:
        nodes.extend(tree.get('nodes') or [])
        edges.extend(tree.get('edges') or [])
    return nodes, edges


def groups_for(team_id: str, userinterface: Optional[str],
               overrides: Optional[Mapping[str, str]] = None,
               loader: Optional[Callable[[str, str], Any]] = None) -> Optional[core_groups.ScreenGroups]:
    """The screen groups of one app (``SCREEN_GROUP_OVERRIDES`` applied unless ``overrides``
    is given), or None when the app has no tree."""
    if not userinterface:
        return None
    graph = (loader or load_app_graph)(team_id, userinterface)
    if not graph:
        return None
    nodes, edges = graph
    return core_groups.from_rows(nodes, edges,
                                 overrides if overrides is not None else overrides_for(userinterface))


class GroupCache:
    """``groups_for`` once per (team, userinterface)."""

    def __init__(self, fn: Optional[Callable[[str, str], Optional[core_groups.ScreenGroups]]] = None):
        self._fn = fn or groups_for
        self._cache: Dict[Tuple[str, str], Optional[core_groups.ScreenGroups]] = {}

    def get(self, team_id: str, userinterface: Optional[str]) -> Optional[core_groups.ScreenGroups]:
        if not userinterface:
            return None
        key = (str(team_id), userinterface)
        if key not in self._cache:
            self._cache[key] = self._fn(team_id, userinterface)
        return self._cache[key]


def screen_entries(groups: Optional[core_groups.ScreenGroups]) -> Optional[List[Dict[str, Any]]]:
    """``[{node_id, label}]`` of the groups (what a ``screen-id`` prompt lists), or None."""
    if groups is None:
        return None
    return groups.entries() or None


def describe(groups: Optional[core_groups.ScreenGroups]) -> List[str]:
    """Readable lines, ``group -> member, member ...``: multi-member groups first, then the
    single screens on one line, then any override warning."""
    if groups is None:
        return ['(no tree)']
    lines = []
    for g in groups.multi_member():
        members = ', '.join(f"{m['label']}" + (f" [{m['focus']}]" if m['focus'] and m['focus'] != m['label'] else '')
                            for m in g['members'][1:])
        lines.append(f"{g['label']} ({len(g['members'])}) -> {members}")
    single = sorted(g['label'] for g in groups.groups.values() if len(g['members']) == 1)
    lines.append(f"single screens ({len(single)}): {', '.join(single)}")
    lines.extend(f"WARNING {w}" for w in groups.warnings)
    return lines
