"""Screen groups: the same screen with a different element focused (TASK-27 step 4k).

In a navigation tree, "Home with tab X focused" is its own node (``home_tvguide``,
``home_apps``, ``home_replay``...), and so is "the Apps store with tile Y focused"
(``apps_netflix``, ``apps_disney``...). Navigation needs every one of those nodes. A vision
model does not: the frames are the same screen, only the highlight moves. So the
``screen-id`` answer is the **group** (``home``), and the highlighted item is a separate
question (``focus``).

The rule, derived from the tree only:

* Two nodes are in one group when an edge joins them whose default action set is **purely
  directional**: at least one ``press_key`` of LEFT / RIGHT / UP / DOWN (``DPAD_*``,
  ``KEYCODE_DPAD_*``, ``KEY_*`` and ``Arrow*`` spellings too) and nothing else but waits.
  Moving the highlight does not change the screen. Union-find over every such edge of the
  app's trees (root and nested; a node id shared by two trees is one node).
* Any other action (OK, BACK, HOME, number keys, clicks, taps, text...) leaves the screen,
  so it never joins. An edge with **no** actions (or only waits) is unknown and never joins.
* Both directions count, exactly as the navigation graph builds them: the default action set
  forward, ``action_sets[1]`` reverse. A conditional edge with no actions of its own borrows
  its sibling's (same source, same ``default_action_set_id``), as ``create_networkx_graph``
  does. Sibling shortcuts (synthetic copies) and ``hidden_in_base`` rows are ignored; entry
  nodes are never a member of any group.

The group's **name** (its representative node): among the members, the nodes entered from
outside the group by a non-directional edge (``ENTRY -> home: BACK, TVGUIDE, HOME``). When
several are (typically the reverse ``apps -> home_apps: BACK``) or none is, the **shortest
label** wins, then the alphabetically first label, then the node id. Deterministic.

**Focus** of a member: ``None`` for the representative (the screen as entered, nothing extra
focused). Otherwise the text of the node's first text verification (``waitForTextToAppear``,
``params.text``) **when no other node of the group checks the same text** (any ``|``
alternative in common): on ``stb_tv`` Home and several tabs all check ``Home|Startseite``,
which proves the screen, not the tab. Else the label after ``<group>_`` (``home_apps`` ->
``apps``), else the full node label.

**Overrides** ``{node_label: group_label}`` (per userinterface) move a node by hand after the
derivation. ``group_label`` equal to the node's own label splits the node into a group of its
own; any other node label moves the node into the derived group that holds that node (a group
name works, and so does any member: ``{'apps': 'apps_netflix'}`` puts ``apps`` with its
tiles). An override naming no node is ignored and reported in ``warnings``. Every group is
then named again by the rule above, so a group that gains its entry node takes its name.
The override data is ``SCREEN_GROUP_OVERRIDES`` below (core): the navigation hook applies
``overrides_for(<its userinterface>)`` and ``features/ai-dataset`` reads the same dict. Core
never imports the feature.

The ``screen-id`` label of a grouped node (``ScreenGroups.label_for``)::

    {"node_id": "<group node id>", "label": "home",
     "node": "<original node id>", "node_label": "home_apps", "focus": "Apps"}

``node_id`` / ``label`` are the answer; ``node`` / ``node_label`` / ``focus`` describe the
frame and are never compared by ``is_failure`` or the conflict check
(``training_samples.ANNOTATION_KEYS``). A label without ``node`` is the pre-4k form;
``regroup_label`` converts it (and is the identity on a label already grouped).

Pure: no DB, no network, no Flask. ``from_graph`` reads a networkx graph that is already
loaded (the navigation executor's unified graph).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

DIRECTIONAL_KEYS = frozenset({'LEFT', 'RIGHT', 'UP', 'DOWN'})
KEY_COMMANDS = frozenset({'press_key'})
WAIT_COMMANDS = frozenset({'wait', 'sleep'})
_KEY_PREFIXES = ('KEYCODE_', 'DPAD_', 'KEY_', 'ARROW')
ENTRY_NODE_TYPES = frozenset({'entry'})

# The human overrides, per userinterface name: ``{node_label: group_label}`` (rules in the
# module docstring). One source for the navigation hook (``overrides_for`` of the executor's
# userinterface) and the ``features/ai-dataset`` scripts, which read it from here. Pure data.
SCREEN_GROUP_OVERRIDES: Dict[str, Dict[str, str]] = {
    'stb_tv': {
        # apps -> apps_netflix is DOWN, HOME, DOWN on the live tree (HOME resets the tile
        # focus), so the rule leaves the Apps screen apart from its 15 tiles. They are one
        # screen: merge it, and the group takes the name "apps" (entered from home_apps by OK).
        'apps': 'apps_netflix',
        # The profile picker: "en" and "ge" are the same screen with another profile
        # focused. The rule joins en to profile; ge joins them here.
        'ge': 'en',
    },
}


def overrides_for(userinterface: Optional[str]) -> Dict[str, str]:
    """A copy of the overrides of one userinterface (empty when it has none)."""
    return dict(SCREEN_GROUP_OVERRIDES.get(userinterface or '', {}) or {})

DIRECTIONAL, OTHER, UNKNOWN = 'directional', 'other', 'unknown'

EdgeRecord = Tuple[str, str, List[Dict[str, Any]]]


# ---- actions -------------------------------------------------------------------------------

def _norm_key(key: Any) -> str:
    k = str(key or '').strip().upper().replace(' ', '')
    changed = True
    while changed:
        changed = False
        for prefix in _KEY_PREFIXES:
            if k.startswith(prefix) and len(k) > len(prefix):
                k, changed = k[len(prefix):], True
    return k


def action_kind(actions: Optional[Sequence[Mapping[str, Any]]]) -> str:
    """``directional`` (only directional key presses and waits, at least one press),
    ``other`` (anything else in the set) or ``unknown`` (no actions, or waits only)."""
    presses = 0
    for action in actions or []:
        if not isinstance(action, Mapping):
            return OTHER
        command = str(action.get('command') or '').strip()
        if command in WAIT_COMMANDS:
            continue
        params = action.get('params') if isinstance(action.get('params'), Mapping) else {}
        if command in KEY_COMMANDS and _norm_key(params.get('key')) in DIRECTIONAL_KEYS:
            presses += 1
            continue
        return OTHER
    return DIRECTIONAL if presses else UNKNOWN


def _default_set(action_sets: Sequence[Mapping[str, Any]], default_id: Any) -> Optional[Mapping[str, Any]]:
    sets = [s for s in action_sets or [] if isinstance(s, Mapping)]
    if not sets:
        return None
    return next((s for s in sets if s.get('id') == default_id), None) or sets[0]


# ---- adapters: DB rows and the navigation graph give the same records ---------------------------

def _is_entry(node_type: Any, label: Any) -> bool:
    return str(node_type or '').lower() in ENTRY_NODE_TYPES or str(label or '').strip().upper() == 'ENTRY'


def _parent_ref(row: Mapping[str, Any]) -> bool:
    data = row.get('data') if isinstance(row.get('data'), Mapping) else {}
    meta = row.get('metadata') if isinstance(row.get('metadata'), Mapping) else {}
    return bool(data.get('isParentReference') or meta.get('isParentReference'))


def nodes_from_rows(node_rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """``navigation_nodes`` rows (base scope: ``hidden_in_base`` rows dropped) as
    ``{node_id: {label, node_type, verifications}}``. A node id repeated in a nested tree
    (a parent reference) keeps its canonical row."""
    out: Dict[str, Dict[str, Any]] = {}
    refs: Dict[str, bool] = {}
    for row in node_rows or []:
        if row.get('hidden_in_base') is True or not row.get('node_id'):
            continue
        nid = str(row['node_id'])
        is_ref = _parent_ref(row)
        if nid in out and (is_ref or not refs[nid]):
            continue
        data = row.get('data') if isinstance(row.get('data'), Mapping) else {}
        out[nid] = {'label': str(row.get('label') or nid),
                    'node_type': row.get('node_type') or data.get('type') or 'screen',
                    'verifications': list(row.get('verifications') or [])}
        refs[nid] = is_ref
    return out


def edges_from_rows(edge_rows: Iterable[Mapping[str, Any]]) -> List[EdgeRecord]:
    """``navigation_edges`` rows as ``(source, target, actions)`` records, the way
    ``create_networkx_graph`` turns them into graph edges: the default set forward (a
    conditional edge with no actions of its own borrows its sibling's), ``action_sets[1]``
    reverse. ``hidden_in_base`` rows are dropped (base scope)."""
    rows = [e for e in edge_rows or [] if e.get('hidden_in_base') is not True
            and e.get('source_node_id') and e.get('target_node_id')]
    out: List[EdgeRecord] = []
    for e in rows:
        src, tgt = str(e['source_node_id']), str(e['target_node_id'])
        sets = [s for s in e.get('action_sets') or [] if isinstance(s, Mapping)]
        default_id = e.get('default_action_set_id')
        default = _default_set(sets, default_id)
        forward = list((default or {}).get('actions') or [])
        if not forward and default_id:
            for other in rows:
                if str(other.get('source_node_id')) != src or str(other.get('target_node_id')) == tgt:
                    continue
                if other.get('default_action_set_id') != default_id:
                    continue
                other_sets = [s for s in other.get('action_sets') or [] if isinstance(s, Mapping)]
                if other_sets and other_sets[0].get('actions'):
                    forward = list(other_sets[0]['actions'])
                    break
        if forward:
            out.append((src, tgt, forward))
        if len(sets) >= 2 and sets[1].get('actions'):
            out.append((tgt, src, list(sets[1]['actions'])))
    return out


def from_rows(node_rows: Iterable[Mapping[str, Any]], edge_rows: Iterable[Mapping[str, Any]],
              overrides: Optional[Mapping[str, str]] = None) -> 'ScreenGroups':
    """Groups of one app from its node and edge rows (all its trees)."""
    return derive(nodes_from_rows(node_rows), edges_from_rows(edge_rows), overrides)


def from_graph(graph: Any, overrides: Optional[Mapping[str, str]] = None) -> 'ScreenGroups':
    """Groups from an already-built navigation graph (``create_unified_networkx_graph``):
    its nodes, and every edge except sibling shortcuts, each with its default action set.
    Raises when ``graph`` is not a graph (the caller decides the fallback)."""
    nodes: Dict[str, Dict[str, Any]] = {}
    for nid, data in graph.nodes(data=True):
        data = data or {}
        nodes[str(nid)] = {'label': str(data.get('label') or nid),
                           'node_type': data.get('node_type') or 'screen',
                           'verifications': list(data.get('verifications') or [])}
    edges: List[EdgeRecord] = []
    for src, tgt, data in graph.edges(data=True):
        data = data or {}
        if data.get('is_sibling_shortcut'):
            continue
        default = _default_set(data.get('action_sets') or [], data.get('default_action_set_id'))
        actions = list((default or {}).get('actions') or [])
        if actions:
            edges.append((str(src), str(tgt), actions))
    return derive(nodes, edges, overrides)


# ---- the derivation ------------------------------------------------------------------------

def text_verification(verifications: Optional[Sequence[Any]]) -> Optional[str]:
    """The text of the node's first "text appears" verification, or None."""
    for v in verifications or []:
        if not isinstance(v, Mapping):
            continue
        command = str(v.get('command') or '')
        vtype = str(v.get('verification_type') or '').lower()
        if 'disappear' in command.lower():
            continue
        if vtype != 'text' and not command.startswith('waitForText'):
            continue
        params = v.get('params') if isinstance(v.get('params'), Mapping) else {}
        text = params.get('text')
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def _rep_key(nid: str, labels: Mapping[str, str]) -> Tuple[int, str, str]:
    label = labels.get(nid, nid)
    return (len(label), label.lower(), nid)


class ScreenGroups:
    """The groups of one app. ``groups`` = ``{group node id: {node_id, label, members}}``,
    members sorted as ``[{node_id, label, focus}]`` (the representative first)."""

    def __init__(self, groups: Dict[str, Dict[str, Any]], warnings: Optional[List[str]] = None):
        self.groups = groups
        self.warnings = list(warnings or [])
        self._of: Dict[str, str] = {}
        self._member: Dict[str, Dict[str, Any]] = {}
        for gid, g in groups.items():
            for m in g['members']:
                self._of[m['node_id']] = gid
                self._member[m['node_id']] = m

    def __contains__(self, node_id: Any) -> bool:
        return str(node_id) in self._of

    def group_of(self, node_id: Any) -> Optional[Dict[str, Any]]:
        gid = self._of.get(str(node_id)) if node_id is not None else None
        return self.groups.get(gid) if gid else None

    def member(self, node_id: Any) -> Optional[Dict[str, Any]]:
        return self._member.get(str(node_id)) if node_id is not None else None

    def focus_of(self, node_id: Any) -> Optional[str]:
        m = self.member(node_id)
        return m.get('focus') if m else None

    def node_by_label(self, label: Any) -> Optional[str]:
        """The node id of a member labelled ``label`` (trimmed, case-insensitive; the group
        node first, then the first member in label order), or None."""
        want = str(label or '').strip().lower()
        if not want:
            return None
        for g in sorted(self.groups.values(), key=lambda g: (g['label'].lower(), g['node_id'])):
            for m in g['members']:
                if m['label'].lower() == want:
                    return m['node_id']
        return None

    def label_for(self, node_id: Any, node_label: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The grouped ``screen-id`` label of a frame showing ``node_id``, or None when the
        node is not in any group (not a node of this app)."""
        g = self.group_of(node_id)
        if g is None:
            return None
        m = self._member[str(node_id)]
        return {'node_id': g['node_id'], 'label': g['label'], 'node': m['node_id'],
                'node_label': m['label'] or node_label, 'focus': m['focus']}

    def entries(self) -> List[Dict[str, Any]]:
        """``[{node_id, label}]`` of every group, sorted by label: the screens a prompt lists."""
        return sorted(({'node_id': g['node_id'], 'label': g['label']} for g in self.groups.values()),
                      key=lambda e: (e['label'].lower(), e['node_id']))

    def multi_member(self) -> List[Dict[str, Any]]:
        """Groups with more than one node, sorted by label (what the grouping merged)."""
        return sorted((g for g in self.groups.values() if len(g['members']) > 1),
                      key=lambda g: (g['label'].lower(), g['node_id']))

    def to_list(self) -> List[Dict[str, Any]]:
        return [dict(g, members=[dict(m) for m in g['members']])
                for g in sorted(self.groups.values(), key=lambda g: (g['label'].lower(), g['node_id']))]


def derive(nodes: Mapping[str, Mapping[str, Any]], edges: Iterable[EdgeRecord],
           overrides: Optional[Mapping[str, str]] = None) -> ScreenGroups:
    """Group ``nodes`` (``{node_id: {label, node_type, verifications}}``) over ``edges``
    (``(source, target, actions)``). Pure and deterministic."""
    labels = {nid: str(n.get('label') or nid) for nid, n in nodes.items()}
    members = [nid for nid, n in nodes.items() if not _is_entry(n.get('node_type'), n.get('label'))]
    member_set = set(members)
    edges = list(edges)

    parent = {nid: nid for nid in members}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if _rep_key(ra, labels) <= _rep_key(rb, labels):
                parent[rb] = ra
            else:
                parent[ra] = rb

    kinds = [(s, t, action_kind(acts)) for s, t, acts in edges]
    for s, t, kind in kinds:
        if kind == DIRECTIONAL and s in member_set and t in member_set and s != t:
            union(s, t)

    comps: Dict[str, List[str]] = {}
    for nid in members:
        comps.setdefault(find(nid), []).append(nid)
    comp_of = {nid: root for root, ids in comps.items() for nid in ids}

    def representative(ids: Sequence[str]) -> str:
        ids_set = set(ids)
        entered = {t for s, t, kind in kinds
                   if kind == OTHER and t in ids_set and s not in ids_set}
        pool = [nid for nid in ids if nid in entered] or list(ids)
        return min(pool, key=lambda nid: _rep_key(nid, labels))

    groups: Dict[str, List[str]] = {}
    for ids in comps.values():
        groups[representative(ids)] = list(ids)

    warnings: List[str] = []
    if overrides:
        # Derived group of each node label (the first node id in label order wins a tie).
        group_by_label: Dict[str, str] = {}
        by_label: Dict[str, List[str]] = {}
        for rep, ids in groups.items():
            for nid in ids:
                group_by_label.setdefault(labels[nid].lower(), rep)
        for nid in sorted(members, key=lambda n: (labels[n].lower(), n)):
            by_label.setdefault(labels[nid].lower(), []).append(nid)
        moves: List[Tuple[str, Optional[str]]] = []  # (node id, target derived group, None = alone)
        for node_label, group_label in sorted(overrides.items()):
            ids = by_label.get(str(node_label).strip().lower())
            if not ids:
                warnings.append(f"override {node_label!r}: no such node; ignored")
                continue
            target = str(group_label or '').strip().lower()
            for nid in ids:
                if target == labels[nid].lower():
                    moves.append((nid, None))
                elif target in group_by_label:
                    moves.append((nid, group_by_label[target]))
                else:
                    warnings.append(f"override {node_label!r} -> {group_label!r}: no node named "
                                    f"{group_label!r}; ignored")
        moved = {nid for nid, _ in moves}
        buckets: List[List[str]] = []
        index: Dict[str, int] = {}
        for rep, ids in groups.items():
            index[rep] = len(buckets)
            buckets.append([n for n in ids if n not in moved])
        for nid, target in moves:
            if target is None:
                buckets.append([nid])
            else:
                buckets[index[target]].append(nid)
        # Every group is named again by the same rule (a group that gained its entry node,
        # or lost its representative, gets the right name).
        groups = {representative(ids): ids for ids in buckets if ids}

    out: Dict[str, Dict[str, Any]] = {}
    for rep, ids in groups.items():
        group_label = labels[rep]
        ordered = [rep] + sorted((n for n in ids if n != rep), key=lambda n: (labels[n].lower(), n))
        texts = {nid: text_verification((nodes.get(nid) or {}).get('verifications')) for nid in ordered}
        mems = []
        for nid in ordered:
            focus = None
            if nid != rep:
                own = _focus_text(nid, texts)
                focus = own if own else _label_focus(labels[nid], group_label)
            mems.append({'node_id': nid, 'label': labels[nid], 'focus': focus})
        out[rep] = {'node_id': rep, 'label': group_label, 'members': mems}
    return ScreenGroups(out, warnings)


def _alternatives(text: Optional[str]) -> set:
    return {a.strip().lower() for a in (text or '').split('|') if a.strip()}


def _focus_text(nid: str, texts: Mapping[str, Optional[str]]) -> Optional[str]:
    """The member's text verification, when it names what is focused on it: only when no
    other node of the group (the representative included) checks the same text. A text
    shared across the group ("Home|Startseite" on Home and several tabs, or "Home" as one
    of its alternatives) is a check of the screen, not of the focus."""
    own = _alternatives(texts.get(nid))
    if not own:
        return None
    for other, text in texts.items():
        if other != nid and own & _alternatives(text):
            return None
    return texts[nid]


def _label_focus(label: str, group_label: str) -> Optional[str]:
    prefix = f"{group_label}_"
    if label.lower().startswith(prefix.lower()) and len(label) > len(prefix):
        return label[len(prefix):]
    return label


# ---- labels ------------------------------------------------------------------------------

GROUP_KEYS = ('node', 'node_label', 'focus')


def is_grouped(label: Any) -> bool:
    """A ``screen-id`` label in the step-4k form (it names the original ``node``)."""
    return isinstance(label, Mapping) and 'node' in label


def regroup_label(label: Any, groups: Optional[ScreenGroups]) -> Any:
    """``label`` in the step-4k group form, or ``label`` unchanged when it cannot be grouped
    (not a dict, a screen not in the tree, or a node no longer in the app).

    The original node is ``label['node']`` when present, else ``label['node_id']`` (the
    pre-4k form). A ``focus`` already on the label is kept while its group is unchanged (a
    human may have corrected it); otherwise the member's derived focus is used. Idempotent."""
    if groups is None or not isinstance(label, Mapping) or label.get('node_id') is None:
        return label
    original = label.get('node') if label.get('node') is not None else label.get('node_id')
    grouped = groups.label_for(original, label.get('node_label') or label.get('label'))
    if grouped is None:
        return label
    if 'focus' in label and str(label.get('node_id')) == str(grouped['node_id']):
        grouped['focus'] = label.get('focus')
    return grouped
