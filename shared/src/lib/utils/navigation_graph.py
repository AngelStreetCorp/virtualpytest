"""
NetworkX Graph Management for Navigation Trees
Handles building and managing NetworkX graphs from navigation data.

Variant resolution (per-variant full-override model — see docs/agent/navigation/VARIANT.md):
    A "variant" is a single user-chosen name (e.g. 'example-v2-en') registered
    in `userinterface_variants`. Per-variant overrides live ON the variant row,
    in `node_overrides` / `edge_overrides` JSONB maps keyed by node_id / edge_id.
    Base navigation_nodes / navigation_edges rows stay pure; variant-only rows
    are flagged via the boolean column `hidden_in_base` on those tables.

    Each override entry FULLY REPLACES the base content for that row when the
    variant is active. There is no patch / param-merge layer; the entry either
    supplies a full `verifications` array (nodes) or a full `action_sets` array
    (edges), or it disables the row, or it is absent (fall-through to base).

    At graph build time the resolver receives the override maps directly:

      resolve_node_variant(node, variant_node_overrides) where
        - variant_node_overrides is None              → base run. Respect
          node['hidden_in_base']: skip the row when true.
        - variant_node_overrides is a dict, no entry  → fall through to base.
        - entry has `disabled: true`                  → skip the row.
        - entry has `verifications` list              → replace base verifications.

    Same shape for resolve_edge_variant with `action_sets` replacing
    `verifications`.

    KPI carve-out: the action_sets override fully replaces base actions /
    verifications, but `kpi_references` / `use_verifications_for_kpi` INHERIT
    from the matching base action_set (by `id`) unless the variant override
    explicitly sets its own. A variant is normally authored to change how an
    edge is traversed, not what to measure; without this, an override created
    before the base gained a KPI reference would silently drop KPI measurement
    for that variant ("No KPI measurements recorded"). See resolve_edge_variant.

    Node override entries may also carry `position: {x, y}` — a per-variant
    CANVAS layout override (e.g. two menu screens whose on-screen order is
    swapped between variants). It is a pure editor concern: this resolver and
    create_networkx_graph NEVER read position (the executable graph is keyed by
    node_id + edges, not coordinates), so it changes nothing about execution and
    is intentionally NOT applied here. It lives only in the frontend resolver
    (frontend/src/utils/navigation/variantResolver.ts). See
    docs/agent/navigation/VARIANT.md "Per-variant node position".

    Each resolved row carries `__variant_state = {active: bool, applied_match: str | None}`.
    `applied_match` is the literal `'base-hidden'` for rows skipped because of
    `hidden_in_base`, `'<variant>'` when a variant entry applied (cosmetic), or
    None when the row rendered base data unchanged.

    Edges whose source or target node was disabled by variant resolution are
    auto-skipped — authors only need to disable the node, the connecting edges
    drop out automatically.
"""

import copy
import networkx as nx
from typing import Any, Dict, List, Optional


# ==============================================================================
# VARIANT OVERRIDE RESOLVER
# ==============================================================================
# Pure helper, no NetworkX dependency, so the frontend can mirror in TS.


def resolve_node_variant(
    node: Dict[str, Any],
    variant_node_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a copy of `node` with variant resolution applied.

    Adds `__variant_state` = { active: bool, applied_match: str | None }.
    When the active variant supplies a `verifications` override, the returned
    node carries that full list; otherwise the base verifications stay.

    Args:
        node: navigation_nodes row dict (with `node_id`, `verifications`,
            `hidden_in_base`, ...).
        variant_node_overrides: a variant's `node_overrides` JSONB map keyed by
            node_id, OR None for a base run.

    Pass `variant_node_overrides=None` for a base run: respect the row's
    `hidden_in_base` flag; otherwise the row renders with its base data.
    """
    out = dict(node)

    # Resolved screen fingerprint for Localize: base lives in data.fingerprint;
    # a variant may override it below (a node looks different per variant/locale).
    out['__fingerprint'] = (out.get('data') or {}).get('fingerprint')

    if variant_node_overrides is None:
        if out.get('hidden_in_base') is True:
            out['__variant_state'] = {'active': False, 'applied_match': 'base-hidden'}
            return out
        out['__variant_state'] = {'active': True, 'applied_match': None}
        return out

    node_id = out.get('node_id')
    entry = variant_node_overrides.get(node_id) if node_id else None

    if entry is None:
        out['__variant_state'] = {'active': True, 'applied_match': None}
        return out
    if entry.get('disabled'):
        out['__variant_state'] = {'active': False, 'applied_match': '<variant>'}
        return out

    # A variant may render a node differently: it can override the screen
    # fingerprint (Localize), the screenshot, and the DOM. Absence of any field
    # falls through to base (set above). `__fingerprint` is the Localize-resolved
    # value; we also overlay data.{fingerprint,screenshot,dom} so display and
    # runtime read the variant view.
    overlay: Dict[str, Any] = {}
    if isinstance(entry.get('fingerprint'), dict):
        out['__fingerprint'] = copy.deepcopy(entry['fingerprint'])
        overlay['fingerprint'] = copy.deepcopy(entry['fingerprint'])
    if entry.get('screenshot'):
        overlay['screenshot'] = entry['screenshot']
        if entry.get('screenshot_timestamp') is not None:
            overlay['screenshot_timestamp'] = entry['screenshot_timestamp']
    if entry.get('dom') is not None:
        overlay['dom'] = copy.deepcopy(entry['dom'])
    if overlay:
        out['data'] = {**(out.get('data') or {}), **overlay}

    # Empty list → fall-through. An empty override would mask the base row's
    # structural data and produces self-perpetuating empties when the editor
    # re-reads the variant entry. Only non-empty lists count as a real override.
    override = entry.get('verifications')
    if isinstance(override, list) and len(override) > 0:
        out['verifications'] = copy.deepcopy(override)
        out['__variant_state'] = {'active': True, 'applied_match': '<variant>'}
        return out

    out['__variant_state'] = {'active': True, 'applied_match': '<variant>'}
    return out


def resolve_edge_variant(
    edge: Dict[str, Any],
    variant_edge_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a copy of `edge` with variant resolution applied.

    When the active variant supplies an `action_sets` override, the returned
    edge carries that full list; otherwise the base action_sets stay.

    Args:
        edge: navigation_edges row dict (with `edge_id`, `action_sets`,
            `hidden_in_base`, ...).
        variant_edge_overrides: a variant's `edge_overrides` JSONB map keyed
            by edge_id, OR None for a base run.
    """
    out = dict(edge)

    if variant_edge_overrides is None:
        if out.get('hidden_in_base') is True:
            out['__variant_state'] = {'active': False, 'applied_match': 'base-hidden'}
            return out
        out['__variant_state'] = {'active': True, 'applied_match': None}
        return out

    edge_id = out.get('edge_id')
    entry = variant_edge_overrides.get(edge_id) if edge_id else None

    if entry is None:
        out['__variant_state'] = {'active': True, 'applied_match': None}
        return out
    if entry.get('disabled'):
        out['__variant_state'] = {'active': False, 'applied_match': '<variant>'}
        return out

    # Empty list → fall-through (see resolve_node_variant).
    override = entry.get('action_sets')
    if isinstance(override, list) and len(override) > 0:
        resolved_action_sets = copy.deepcopy(override)
        # KPI references inherit from base unless the variant EXPLICITLY sets
        # its own. The `action_sets` override fully replaces base actions /
        # verifications by design, but a variant override is usually authored
        # to change *how the edge is traversed*, not *what to measure* — and an
        # override created (or replicated) before the base gained a KPI
        # reference silently carries an empty `kpi_references` + no
        # `use_verifications_for_kpi`, which drops KPI measurement entirely for
        # that variant (no row queued → "No KPI measurements recorded"). So per
        # action_set (matched by stable `id`), when the override defines neither
        # a non-empty `kpi_references` nor `use_verifications_for_kpi=True`,
        # backfill both fields from the matching base action_set. A variant that
        # DOES set either keeps full control (variant-specific KPI is honoured).
        base_by_id = {
            (a or {}).get('id'): a
            for a in (out.get('action_sets') or [])
            if (a or {}).get('id')
        }
        for action_set in resolved_action_sets:
            if not isinstance(action_set, dict):
                continue
            has_explicit_kpi = (
                bool(action_set.get('kpi_references'))
                or bool(action_set.get('use_verifications_for_kpi'))
            )
            if has_explicit_kpi:
                continue
            base_set = base_by_id.get(action_set.get('id'))
            if not base_set:
                continue
            base_refs = base_set.get('kpi_references')
            base_use_verif = base_set.get('use_verifications_for_kpi')
            if base_refs:
                action_set['kpi_references'] = copy.deepcopy(base_refs)
            if base_use_verif:
                action_set['use_verifications_for_kpi'] = True
        out['action_sets'] = resolved_action_sets
        out['__variant_state'] = {'active': True, 'applied_match': '<variant>'}
        return out

    out['__variant_state'] = {'active': True, 'applied_match': '<variant>'}
    return out


# ==============================================================================
# VARIANT COMPOSITION (apply a LIST of variants at once)
# ==============================================================================
# See docs/agent/navigation/VARIANT.md "Composition". A run can apply several variants
# (e.g. example-v1 = [active-standby], example-v1+ = [no-tvshop]). Composition is a
# PRE-PASS: it merges N per-variant override maps into ONE merged map, which the
# existing resolver then consumes unchanged. Everything downstream (cache key,
# execution_results.variant, metrics) treats the composition as a single
# canonical string (sorted, '+'-joined).
#
# Design notes:
#   * Ordering is canonical (variants sorted by name) so [a,b] and [b,a] yield
#     the SAME merged map, cache entry, and metrics scope. "Last wins" on a
#     content conflict therefore means "the lexicographically-last variant's
#     content wins" — deterministic and order-independent. Content conflicts are
#     a modeling smell; the caller-side linter is what surfaces them.
#   * `disable` is a hard veto: if any applied variant disables a row, the row is
#     removed regardless of what another variant says (a removed screen stays
#     removed).
#   * Visibility is additive AND backward-compatible with the legacy
#     "disable-on-all-other-variants" convention for variant-only rows, via the
#     `cross_disabled_ids` set (rows disabled by SOME variant of the UI =
#     legacy/"old-style" rows). For such a hidden row, an applied variant that
#     has NO entry is treated as its owner (legacy fall-through = visible). For a
#     hidden row that NO variant disables ("new-style", authored for
#     composition), it stays hidden unless an applied variant has a non-disabled
#     entry. This makes compose([X]) byte-for-byte equivalent to the old single-
#     variant raw-map path, so no data migration is required.


def parse_variant_list(value: Any) -> List[str]:
    """Normalize a variant selector into an ordered, de-duplicated component list.

    Accepts a list/tuple of names, or a string with components separated by
    `+` and/or `,` (e.g. 'active-standby+no-tvshop' or 'a, b'). Each component
    is trimmed and lowercased; empty components and the literal 'base' (the UI
    label for "no variant") are dropped. Order is preserved (first occurrence).
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw = [str(v) for v in value]
    else:
        raw = str(value).replace('+', ',').split(',')

    seen = set()
    out: List[str] = []
    for item in raw:
        name = item.strip().lower()
        if not name or name == 'base':
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def canonical_variant_name(value: Any) -> Optional[str]:
    """Return the canonical composite string for a variant selector, or None.

    Sorts components so [a,b] and [b,a] collapse to the same key, then joins
    with '+'. Returns None for a base run (no components). This string is what
    flows through the cache key, execution_results.variant and the metrics
    scope — a single variant just returns its own name.
    """
    components = sorted(parse_variant_list(value))
    if not components:
        return None
    return '+'.join(components)


def _compose_overrides(
    applied_maps: List[Dict[str, Any]],
    hidden_ids: set,
    cross_disabled_ids: set,
    content_key: str,
) -> Dict[str, Any]:
    """Merge per-variant override maps into one resolver-ready map.

    Args:
        applied_maps: each variant's override map (node_overrides or
            edge_overrides), in CANONICAL (sorted-by-name) order.
        hidden_ids: ids of rows with hidden_in_base=true (across all trees).
        cross_disabled_ids: ids of rows that carry a {disabled:true} entry in
            ANY variant of the UI — i.e. legacy "disable-on-others" rows.
        content_key: 'verifications' for nodes, 'action_sets' for edges.

    Returns a map keyed by row id where each value is `{disabled: true}` (row
    removed), `{<content_key>: [...]}` (row gets variant content), or the id is
    absent (row falls through to base, active).
    """
    candidate_ids = set()
    for m in applied_maps:
        candidate_ids.update(m.keys())
    candidate_ids.update(hidden_ids)

    merged: Dict[str, Any] = {}
    for rid in candidate_ids:
        disabled_by_any = False
        enabled_by_any = False
        absent_count = 0
        content = None  # last non-empty (in canonical order) wins

        for m in applied_maps:
            entry = m.get(rid)
            if not entry:
                absent_count += 1
                continue
            if entry.get('disabled'):
                disabled_by_any = True
                continue
            candidate = entry.get(content_key)
            if isinstance(candidate, list) and len(candidate) > 0:
                content = candidate  # last (in canonical order) wins
                enabled_by_any = True
            elif entry.get('enabled') is True:
                enabled_by_any = True
            else:
                # Present but a no-op ({} / {enabled: false}) → behaves like an
                # absent entry: it neither removes nor adds the row.
                absent_count += 1

        is_hidden = rid in hidden_ids
        if disabled_by_any:
            visible = False
        elif enabled_by_any:
            visible = True
        elif is_hidden:
            # No explicit enable. Legacy rows (disabled somewhere) treat an
            # absent applied variant as the owner → visible; new-style hidden
            # rows stay hidden unless explicitly enabled.
            visible = (rid in cross_disabled_ids) and absent_count > 0
        else:
            visible = True  # base-visible row, untouched

        if not visible:
            merged[rid] = {'disabled': True}
        elif content is not None:
            merged[rid] = {content_key: content}
        # else: visible with base content → no entry (resolver falls through)

    return merged


def compose_node_overrides(
    applied_maps: List[Dict[str, Any]],
    hidden_node_ids: set,
    cross_disabled_node_ids: set,
) -> Dict[str, Any]:
    """Compose node_overrides maps. See _compose_overrides."""
    return _compose_overrides(applied_maps, hidden_node_ids, cross_disabled_node_ids, 'verifications')


def compose_edge_overrides(
    applied_maps: List[Dict[str, Any]],
    hidden_edge_ids: set,
    cross_disabled_edge_ids: set,
) -> Dict[str, Any]:
    """Compose edge_overrides maps. See _compose_overrides."""
    return _compose_overrides(applied_maps, hidden_edge_ids, cross_disabled_edge_ids, 'action_sets')


def detect_composition_conflicts(
    applied: List[Dict[str, Any]],
    content_key_node: str = 'verifications',
    content_key_edge: str = 'action_sets',
) -> List[Dict[str, Any]]:
    """Lint a candidate composition: report rows touched by >1 variant with
    incompatible intents.

    `applied` is a list of `{name, node_overrides, edge_overrides}` dicts (the
    variant rows being composed). Returns a list of conflict descriptors:
    `{kind: 'content'|'visibility', scope: 'node'|'edge', id, variants: [...]}`.
    - content: two+ variants both supply non-empty content for the same row
      (last-sorted-wins applies, but the author probably didn't intend it).
    - visibility: one variant enables/content-overrides a row another disables
      (disable hard-veto wins, so the enabling variant is silently dropped).
    Disjoint touches and identical disables are NOT conflicts.
    """
    conflicts: List[Dict[str, Any]] = []

    def _scan(scope: str, key: str):
        ids = set()
        for v in applied:
            ids.update((v.get(f'{scope}_overrides') or {}).keys())
        for rid in ids:
            content_owners = []
            disablers = []
            enablers = []
            for v in applied:
                entry = (v.get(f'{scope}_overrides') or {}).get(rid)
                if not entry:
                    continue
                if entry.get('disabled'):
                    disablers.append(v['name'])
                    continue
                enablers.append(v['name'])
                candidate = entry.get(key)
                if isinstance(candidate, list) and len(candidate) > 0:
                    content_owners.append(v['name'])
            if len(content_owners) > 1:
                conflicts.append({
                    'kind': 'content', 'scope': scope, 'id': rid,
                    'variants': sorted(content_owners),
                })
            if disablers and enablers:
                conflicts.append({
                    'kind': 'visibility', 'scope': scope, 'id': rid,
                    'variants': sorted(set(disablers + enablers)),
                })

    _scan('node', content_key_node)
    _scan('edge', content_key_edge)
    return conflicts


def create_networkx_graph(
    nodes: List[Dict],
    edges: List[Dict],
    variant_node_overrides: Optional[Dict[str, Any]] = None,
    variant_edge_overrides: Optional[Dict[str, Any]] = None,
) -> nx.DiGraph:
    """
    Create NetworkX directed graph from navigation nodes and edges.

    Args:
        nodes: List of navigation nodes from database.
        edges: List of navigation edges from database.
        variant_node_overrides: Variant `node_overrides` map (keyed by node_id),
            OR None for a base run.
        variant_edge_overrides: Variant `edge_overrides` map (keyed by edge_id),
            OR None for a base run.

    Returns:
        NetworkX directed graph.
    """
    is_base = variant_node_overrides is None and variant_edge_overrides is None
    print(
        f"[@navigation:graph:create_networkx_graph] Creating graph with "
        f"{len(nodes)} nodes and {len(edges)} edges "
        f"(variant={'base' if is_base else 'overrides supplied'})"
    )

    # Create directed graph for navigation flow
    G = nx.DiGraph()
    disabled_node_ids = set()

    # Add nodes with their data - NEW NORMALIZED FORMAT ONLY
    for node in nodes:
        node_id = node.get('node_id')
        if not node_id:
            print(f"[@navigation:graph:create_networkx_graph] Warning: Node without node_id found, skipping")
            continue

        # Apply variant overlay (no-op when overrides=None and not hidden_in_base).
        resolved_node = resolve_node_variant(node, variant_node_overrides)
        variant_state = resolved_node.get('__variant_state', {'active': True, 'applied_match': None})
        if not variant_state.get('active', True):
            disabled_node_ids.add(node_id)
            print(f"[@navigation:graph:create_networkx_graph] Skipping node {node_id} ({node.get('label')}) — disabled by variant {variant_state.get('applied_match')}")
            continue

        # NEW NORMALIZED FORMAT - direct database fields
        node_data = resolved_node.get('data', {})
        label = resolved_node.get('label', '')

        # Entry point detection - node_type='entry' OR label='ENTRY'
        node_type_value = resolved_node.get('node_type', 'screen')
        is_entry_point = (
            node_type_value == 'entry' or
            label.upper() == 'ENTRY'
        )

        print(f"[@navigation:graph:create_networkx_graph] Adding node: {label} ({node_id})")

        verifications = resolved_node.get('verifications', [])

        G.add_node(node_id, **{
            'label': label,
            'node_type': node_type_value,
            'description': node_data.get('description', ''),
            'screenshot_url': node_data.get('screenshot', ''),
            'is_entry_point': is_entry_point,
            'is_exit_point': node_data.get('is_exit_point', False),
            'has_children': node_data.get('has_children', False),
            'child_tree_id': node_data.get('child_tree_id'),
            'metadata': node_data,
            'verifications': verifications,  # Resolved (variant-aware) verifications
            '__fingerprint': resolved_node.get('__fingerprint'),  # Localize: variant-resolved screen fingerprint
            'variant_state': variant_state,  # {active, applied_match}
            'verification_pass_condition': resolved_node.get('verification_pass_condition') or node_data.get('verification_pass_condition', 'all')
        })

    print(f"[@navigation:graph:create_networkx_graph] Added {len(G.nodes)} nodes to graph (skipped {len(disabled_node_ids)} disabled by variant)")
    
    # Add edges with actions as attributes
    edges_added = 0
    edges_skipped = 0
    
    print(f"[@navigation:graph:create_networkx_graph] ===== ADDING EDGES WITH ACTIONS =====")
    
    for edge in edges:
        # NEW NORMALIZED FORMAT ONLY
        source_id = edge.get('source_node_id')
        target_id = edge.get('target_node_id')

        if not source_id or not target_id:
            print(f"[@navigation:graph:create_networkx_graph] Warning: Edge without source/target found, skipping. Available keys: {list(edge.keys())}")
            edges_skipped += 1
            continue

        # Skip edges that touch a node we already removed by variant.
        if source_id in disabled_node_ids or target_id in disabled_node_ids:
            print(f"[@navigation:graph] Skipping edge {source_id} → {target_id} — endpoint disabled by variant")
            edges_skipped += 1
            continue

        # Check if nodes exist
        if source_id not in G.nodes or target_id not in G.nodes:
            print(f"[@navigation:graph:create_networkx_graph] Warning: Edge references non-existent nodes {source_id} -> {target_id}, skipping")
            edges_skipped += 1
            continue

        # Apply edge variant overlay (no-op when overrides=None and not hidden_in_base).
        resolved_edge = resolve_edge_variant(edge, variant_edge_overrides)
        edge_variant_state = resolved_edge.get('__variant_state', {'active': True, 'applied_match': None})
        if not edge_variant_state.get('active', True):
            print(f"[@navigation:graph:create_networkx_graph] Skipping edge {source_id} → {target_id} — disabled by variant {edge_variant_state.get('applied_match')}")
            edges_skipped += 1
            continue
        edge = resolved_edge  # use resolved view from here on

        # NEW ONLY: action_sets structure
        edge_data = edge.get('data', {})
        action_sets = edge.get('action_sets')
        if action_sets is None:
            raise ValueError(f"Edge {edge.get('edge_id')} missing action_sets")
        
        default_action_set_id = edge.get('default_action_set_id')
        if not default_action_set_id:
            raise ValueError(f"Edge {edge.get('edge_id')} missing default_action_set_id")
        
        # Handle empty action_sets for initial setup
        if not action_sets:
            # Empty navigation config - create placeholder edge for initial setup
            actions_list = []
            retry_actions_list = []
            failure_actions_list = []
            default_set = None
            print(f"[@navigation:graph:create_networkx_graph] Adding EMPTY edge {source_id} → {target_id}: Initial setup (no actions yet)")
        else:
            # Find default action set
            default_set = next(
                (s for s in action_sets if s['id'] == default_action_set_id),
                None
            )
            
            if not default_set:
                raise ValueError(f"Edge {edge.get('edge_id')} default action set '{default_action_set_id}' not found")
            
            # Extract actions from default set for pathfinding
            actions_list = default_set.get('actions', [])
            retry_actions_list = default_set.get('retry_actions') or []
            failure_actions_list = default_set.get('failure_actions') or []
            
            # Check if this edge has any valid actions (forward or reverse)
            has_forward_actions = bool(actions_list)
            has_reverse_actions = False
            
            # Check if reverse action set (index 1) has actions
            if len(action_sets) >= 2:
                reverse_set = action_sets[1]
                reverse_actions = reverse_set.get('actions', [])
                has_reverse_actions = bool(reverse_actions)
            
            # Check if this is a conditional edge (shares action_set_id with siblings from same source)
            # Conditional edges might not have actions populated but should be in graph for pathfinding
            is_conditional_edge = False
            if default_action_set_id:
                # Check if other edges from same source share this action_set_id
                for other_edge in edges:
                    other_source = other_edge.get('source_node_id')
                    other_target = other_edge.get('target_node_id')
                    if other_source == source_id and other_target != target_id:
                        other_action_sets = other_edge.get('action_sets', [])
                        if other_action_sets:
                            other_default_id = other_edge.get('default_action_set_id')
                            if other_default_id == default_action_set_id:
                                is_conditional_edge = True
                                break
            
            # Skip edges only if no actions AND not conditional
            # Conditional edges need graph representation even without actions (siblings have the actions)
            if not has_forward_actions and not has_reverse_actions and not is_conditional_edge:
                print(f"[@navigation:graph:create_networkx_graph] SKIPPING edge {source_id} → {target_id}: No actions defined")
                edges_skipped += 1
                continue
            elif not has_forward_actions and not has_reverse_actions and is_conditional_edge:
                print(f"[@navigation:graph:create_networkx_graph] Including CONDITIONAL edge {source_id} → {target_id}: Shares action_set_id with siblings")
        
        # Get node labels for logging
        source_node_data = G.nodes[source_id]
        target_node_data = G.nodes[target_id]
        source_label = source_node_data.get('label', source_id)
        target_label = target_node_data.get('label', target_id)
        
        # Log detailed edge information with action_sets
        print(f"[@navigation:graph:create_networkx_graph] Adding Edge: {source_label} → {target_label}")
        print(f"[@navigation:graph:create_networkx_graph]   Source ID: {source_id}")
        print(f"[@navigation:graph:create_networkx_graph]   Target ID: {target_id}")
        print(f"[@navigation:graph:create_networkx_graph]   Action Sets ({len(action_sets)}):")
        
        for i, action_set in enumerate(action_sets):
            set_id = action_set.get('id', 'unknown')
            set_label = action_set.get('id', 'Unknown')
            is_default = set_id == default_action_set_id
            default_marker = ' [DEFAULT]' if is_default else ''
            print(f"[@navigation:graph:create_networkx_graph]     {i+1}. {set_label} ({set_id}){default_marker}")
            
            set_actions = action_set.get('actions', [])
            for j, action in enumerate(set_actions):
                command = action.get('command', 'unknown')
                params = action.get('params', {})
                params_str = ', '.join([f"{k}={v}" for k, v in params.items()]) if params else 'no params'
                print(f"[@navigation:graph:create_networkx_graph]       - {j+1}. {command}({params_str})")
        
        print(f"[@navigation:graph:create_networkx_graph]   Default Actions ({len(actions_list)}): {[a.get('command') for a in actions_list]}")
        print(f"[@navigation:graph:create_networkx_graph]   Default Retry Actions ({len(retry_actions_list)}): {[a.get('command') for a in retry_actions_list]}")
        print(f"[@navigation:graph:create_networkx_graph]   Default Failure Actions ({len(failure_actions_list)}): {[a.get('command') for a in failure_actions_list]}")
        
        # Create forward edge if it has actions OR if it's a conditional edge
        # Conditional edges need graph representation for pathfinding (multiple destinations, same action)
        if has_forward_actions or is_conditional_edge:
            # ✅ CONDITIONAL EDGE: Populate actions from sibling if this edge has none
            actual_action_sets = action_sets if action_sets else []
            if is_conditional_edge and not has_forward_actions:
                print(f"[@navigation:graph:create_networkx_graph] Conditional edge detected - looking up sibling actions")
                
                # Find sibling edge with same action_set_id that HAS actions
                for other_edge in edges:
                    other_source = other_edge.get('source_node_id')
                    other_target = other_edge.get('target_node_id')
                    
                    if other_source == source_id and other_target != target_id:
                        other_action_sets = other_edge.get('action_sets', [])
                        if other_action_sets and len(other_action_sets) > 0:
                            other_default_id = other_edge.get('default_action_set_id')
                            if other_default_id == default_action_set_id:
                                # Found sibling with actions. Borrow ONLY the
                                # executable parts (actions/retry/failure) — NOT
                                # the whole action_set object. The sibling object
                                # carries the MAIN edge's own `label`
                                # (e.g. "apps_oneplus → oneplus_home"); copying it
                                # wholesale overwrote this conditional edge's own
                                # label, so every consumer keyed by action_set
                                # label (validation-sequence builder, KPI
                                # action_set_map, metrics attribution) lost this
                                # branch — it resolved to the main's label instead
                                # of "apps_oneplus → oneplus_profile". Point-to-
                                # point goto reads the graph by traversal (not by
                                # label) so it still worked, which is why the
                                # frontend goto succeeded while KPI/validation
                                # reported "action set not found". Regression from
                                # the conditional main-vs-sibling rework (siblings
                                # emptied + share the main's id, borrow at runtime).
                                sibling_forward = other_action_sets[0]
                                if sibling_forward.get('actions'):
                                    own_forward = copy.deepcopy(action_sets[0]) if action_sets else copy.deepcopy(sibling_forward)
                                    own_forward['actions'] = sibling_forward.get('actions', [])
                                    own_forward['retry_actions'] = sibling_forward.get('retry_actions', [])
                                    own_forward['failure_actions'] = sibling_forward.get('failure_actions', [])
                                    # Also inherit the owner's KPI measurement intent so the
                                    # sibling can be KPI-measured the SAME way as the main —
                                    # _resolve_kpi_references reads use_verifications_for_kpi off
                                    # this action_set and then times against THIS step's own
                                    # target node. (Frozen kpi_references are NOT borrowed: they
                                    # snapshot the main's screen and would never pass on the
                                    # sibling's. The sibling keeps its own kpi_references, if any.)
                                    if not own_forward.get('kpi_references'):
                                        own_forward['use_verifications_for_kpi'] = bool(
                                            sibling_forward.get('use_verifications_for_kpi', False)
                                        )
                                    # Keep this edge's OWN reverse action_set (index 1)
                                    # alongside the borrowed forward, so the edge carries
                                    # the same [forward, reverse] shape as a normal edge.
                                    # Without it, conditional edges expose only the forward
                                    # set, so KPI measurement reads action_sets[1] as absent
                                    # → sibling_action_set_id empty → the reverse leg is
                                    # never measured (expected_reverse=0), even though the
                                    # reverse navigation runs and the executor queues its KPI.
                                    actual_action_sets = [own_forward]
                                    if len(action_sets) > 1 and action_sets[1]:
                                        actual_action_sets.append(action_sets[1])
                                    actions_list = own_forward.get('actions', [])
                                    retry_actions_list = own_forward.get('retry_actions', [])
                                    failure_actions_list = own_forward.get('failure_actions', [])

                                    # Get sibling label for logging
                                    other_target_data = G.nodes.get(other_target, {})
                                    other_target_label = other_target_data.get('label', other_target)
                                    print(f"[@navigation:graph:create_networkx_graph] ✅ Borrowing actions from sibling: {source_label} → {other_target_label} (keeping own label '{own_forward.get('label')}')")
                                    print(f"[@navigation:graph:create_networkx_graph] Sibling has {len(actions_list)} main actions")
                                    break
                
                if not actual_action_sets:
                    print(f"[@navigation:graph:create_networkx_graph] ⚠️ No sibling actions found - conditional edge may be incomplete")
            
            if is_conditional_edge and not has_forward_actions:
                print(f"[@navigation:graph:create_networkx_graph] Creating FORWARD edge (conditional): {source_label} → {target_label} [action_set_id: {default_action_set_id}]")
            else:
                print(f"[@navigation:graph:create_networkx_graph] Creating FORWARD edge: {source_label} → {target_label}")
            
            G.add_edge(source_id, target_id, **{
                'edge_id': edge.get('edge_id'),
                # Per-direction final_wait_time + threshold ride along inside
                # each action_set entry — no edge-level copy.
                'action_sets': actual_action_sets,  # Use populated action_sets (from sibling if conditional)
                'default_action_set_id': default_action_set_id,
                'edge_type': edge.get('edge_type', 'navigation'),
                'weight': 1,
                'is_forward_edge': True,
                'is_conditional': is_conditional_edge  # Mark conditional edges for executor
            })
            edges_added += 1
        else:
            print(f"[@navigation:graph:create_networkx_graph] SKIPPING forward edge {source_label} → {target_label}: No forward actions and not conditional")
        
        # Create reverse edge if action set index 1 has valid actions
        if has_reverse_actions:
            reverse_set = action_sets[1]
            reverse_actions = reverse_set.get('actions', [])
            reverse_edge_id = f"{edge.get('edge_id')}_reverse"
            print(f"[@navigation:graph:create_networkx_graph] Creating REVERSE edge: {target_label} → {source_label}")
            print(f"[@navigation:graph:create_networkx_graph]   Reverse Actions ({len(reverse_actions)}): {[a.get('command') for a in reverse_actions]}")
            
            G.add_edge(target_id, source_id, **{
                'edge_id': reverse_edge_id,
                'action_sets': [reverse_set],  # Only include the reverse action set
                'default_action_set_id': reverse_set.get('id'),
                'edge_type': edge.get('edge_type', 'navigation'),
                'weight': 1,
                'is_reverse_edge': True  # Mark as reverse for debugging
            })
            edges_added += 1
        else:
            print(f"[@navigation:graph:create_networkx_graph] No reverse edge created for {target_label} → {source_label}: No reverse actions")
        
        print(f"[@navigation:graph:create_networkx_graph] -----")
    
    print(f"[@navigation:graph:create_networkx_graph] ===== GRAPH CONSTRUCTION COMPLETE =====")
    print(f"[@navigation:graph:create_networkx_graph] Successfully created graph with {len(G.nodes)} nodes and {len(G.edges)} edges")
    print(f"[@navigation:graph:create_networkx_graph] Edge processing summary: {edges_added} added, {edges_skipped} skipped")
    
    # ✅ PRE-COMPUTE SIBLING RELATIONSHIPS for conditional edges
    print(f"[@navigation:graph:create_networkx_graph] ===== COMPUTING SIBLING RELATIONSHIPS =====")
    sibling_count = 0
    
    for source_id, target_id, edge_data in G.edges(data=True):
        # Only process conditional edges (they need sibling lookup)
        if not edge_data.get('is_conditional'):
            continue
        
        # Get this edge's action_set_id
        action_sets = edge_data.get('action_sets', [])
        if not action_sets:
            continue
        
        action_set_id = action_sets[0].get('id')
        if not action_set_id:
            continue
        
        # Find all sibling edges (same source, same action_set_id, different target)
        sibling_node_ids = []
        for _, other_target, other_edge_data in G.edges(source_id, data=True):
            # Skip self
            if other_target == target_id:
                continue
            
            # Check if shares same action_set_id
            other_action_sets = other_edge_data.get('action_sets', [])
            if other_action_sets:
                other_action_set_id = other_action_sets[0].get('id')
                if other_action_set_id == action_set_id:
                    sibling_node_ids.append(other_target)
        
        # Store sibling list on the edge
        if sibling_node_ids:
            edge_data['sibling_node_ids'] = sibling_node_ids
            sibling_count += 1
            source_label = G.nodes[source_id].get('label', source_id)
            target_label = G.nodes[target_id].get('label', target_id)
            sibling_labels = [G.nodes[sid].get('label', sid) for sid in sibling_node_ids]
            print(f"[@navigation:graph:create_networkx_graph] Edge {source_label} → {target_label} has {len(sibling_node_ids)} sibling(s): {sibling_labels}")
    
    print(f"[@navigation:graph:create_networkx_graph] Pre-computed siblings for {sibling_count} conditional edges")
    
    # Log all possible transitions summary
    print(f"[@navigation:graph:create_networkx_graph] ===== ALL POSSIBLE TRANSITIONS SUMMARY =====")
    for i, (from_node, to_node, edge_data) in enumerate(G.edges(data=True), 1):
        from_info = G.nodes[from_node]
        to_info = G.nodes[to_node]
        from_label = from_info.get('label', from_node)
        to_label = to_info.get('label', to_node)
        actions = edge_data.get('actions', [])
        action_summary = f"{len(actions)} actions" if actions else "no actions"
        primary_action = edge_data.get('go_action', 'none')
        
        print(f"[@navigation:graph:create_networkx_graph] Transition {i:2d}: {from_label} → {to_label} (primary: {primary_action}, {action_summary})")
    
    print(f"[@navigation:graph:create_networkx_graph] ===== END TRANSITIONS SUMMARY =====")
    
    return G

# NEW: Unified graph creation for nested trees

def create_unified_networkx_graph(
    all_trees_data: List[Dict],
    variant_node_overrides: Optional[Dict[str, Any]] = None,
    variant_edge_overrides: Optional[Dict[str, Any]] = None,
) -> nx.DiGraph:
    """
    Create unified NetworkX graph from multiple navigation trees with cross-tree edges.

    Args:
        all_trees_data: List of tree data dicts containing tree_info, nodes, and edges.
        variant_node_overrides: Variant's `node_overrides` map (keyed by node_id),
            OR None for a base run. Applied per tree.
        variant_edge_overrides: Variant's `edge_overrides` map (keyed by edge_id),
            OR None for a base run. Applied per tree.

    Returns:
        Unified NetworkX directed graph with cross-tree connections.
    """
    is_base = variant_node_overrides is None and variant_edge_overrides is None
    print(
        f"[@navigation:graph:create_unified_networkx_graph] Creating unified graph with "
        f"{len(all_trees_data)} trees (variant={'base' if is_base else 'overrides supplied'})"
    )
    
    # Create unified directed graph
    unified_graph = nx.DiGraph()
    
    # Track tree relationships for cross-tree edges
    tree_hierarchy = {}
    parent_child_map = {}  # parent_node_id -> child_tree_id
    
    # Phase 1: Add all nodes and edges from individual trees
    total_nodes = 0
    total_edges = 0
    
    for tree_data in all_trees_data:
        tree_id = tree_data.get('tree_id')
        tree_info = tree_data.get('tree_info', {})
        nodes = tree_data.get('nodes', [])
        edges = tree_data.get('edges', [])
        
        if not tree_id:
            print(f"[@navigation:graph:create_unified_networkx_graph] Warning: Tree data missing tree_id, skipping")
            continue
        
        print(f"[@navigation:graph:create_unified_networkx_graph] Processing tree: {tree_info.get('name', tree_id)} ({len(nodes)} nodes, {len(edges)} edges)")
        
        # Store tree hierarchy info
        tree_hierarchy[tree_id] = {
            'tree_id': tree_id,
            'name': tree_info.get('name', ''),
            'parent_tree_id': tree_info.get('parent_tree_id'),
            'parent_node_id': tree_info.get('parent_node_id'),
            'tree_depth': tree_info.get('tree_depth', 0),
            'is_root_tree': tree_info.get('is_root_tree', False)
        }
        
        # Map parent node to child tree
        if tree_info.get('parent_node_id'):
            parent_child_map[tree_info.get('parent_node_id')] = tree_id
        
        # Create individual tree graph (variant resolution happens here per tree)
        tree_graph = create_networkx_graph(
            nodes,
            edges,
            variant_node_overrides=variant_node_overrides,
            variant_edge_overrides=variant_edge_overrides,
        )
        
        # Add tree context to all nodes
        for node_id, node_data in tree_graph.nodes(data=True):
            node_data['tree_id'] = tree_id
            node_data['tree_name'] = tree_info.get('name', '')
            node_data['tree_depth'] = tree_info.get('tree_depth', 0)
            # Same node_id can appear in multiple trees as a "parent-reference"
            # row (the home node shown inside its own subtree, etc). NetworkX
            # last-write-wins would let a parent-ref overwrite the canonical
            # row's tree_id, which then misroutes node_metrics writes via
            # `to_tree_id`. Always prefer the canonical row.
            new_is_parent_ref = bool((node_data.get('metadata') or {}).get('isParentReference'))
            if node_id in unified_graph.nodes:
                existing_is_parent_ref = bool(
                    (unified_graph.nodes[node_id].get('metadata') or {}).get('isParentReference')
                )
                if new_is_parent_ref or not existing_is_parent_ref:
                    continue
            unified_graph.add_node(node_id, **node_data)
        
        # Add tree context to all edges  
        for from_node, to_node, edge_data in tree_graph.edges(data=True):
            edge_data['tree_id'] = tree_id
            edge_data['tree_name'] = tree_info.get('name', '')
            unified_graph.add_edge(from_node, to_node, **edge_data)
        
        total_nodes += len(tree_graph.nodes)
        total_edges += len(tree_graph.edges)
    
    print(f"[@navigation:graph:create_unified_networkx_graph] Added {total_nodes} nodes and {total_edges} edges from individual trees")
    
    # Phase 1.5: Create sibling shortcuts for web/mobile DOM navigation
    sibling_shortcuts_created = _create_sibling_shortcuts(unified_graph)
    if sibling_shortcuts_created > 0:
        print(f"[@navigation:graph:create_unified_networkx_graph] ✅ Created {sibling_shortcuts_created} sibling shortcut edges for DOM navigation")
    
    # No virtual cross-tree edges. The unified graph contains exactly the
    # edges authored in `navigation_edges` (regardless of which tree_id
    # they belong to). If the user authored a cross-tree edge — e.g.
    # `apps → apps_netflix` with tree_id = apps-subtree — pathfinding
    # already crosses the boundary through it. If no such edge exists,
    # the subtree is genuinely unreachable from the parent tree and
    # `nx.shortest_path` correctly raises NetworkXNoPath.
    #
    # The previous Phase 2 here injected a synthetic ENTER_SUBTREE edge
    # from each parent_node to an auto-picked first-iterated subtree node
    # with `weight=1`, then mirrored an EXIT_SUBTREE in reverse. With
    # weight 1 it competed with — and on hop count beat — the real edges
    # the user authored. See `docs/agent/navigation/navigation_trees.md` "Cross-tree
    # navigation" for the full rationale.
    
    # Log unified graph statistics
    print(f"[@navigation:graph:create_unified_networkx_graph] ===== UNIFIED GRAPH COMPLETE =====")
    print(f"[@navigation:graph:create_unified_networkx_graph] Total nodes: {len(unified_graph.nodes)}")
    print(f"[@navigation:graph:create_unified_networkx_graph] Total edges: {len(unified_graph.edges)}")
    print(f"[@navigation:graph:create_unified_networkx_graph] Trees included: {len(tree_hierarchy)}")
    
    # Log tree distribution
    tree_node_counts = {}
    for node_id, node_data in unified_graph.nodes(data=True):
        tree_id = node_data.get('tree_id', 'unknown')
        tree_node_counts[tree_id] = tree_node_counts.get(tree_id, 0) + 1
    
    for tree_id, node_count in tree_node_counts.items():
        tree_name = tree_hierarchy.get(tree_id, {}).get('name', tree_id)
        print(f"[@navigation:graph:create_unified_networkx_graph] Tree '{tree_name}': {node_count} nodes")

    # Expose parent menu node -> owned child tree id, so consumers (e.g. localize-dispatch) can resolve
    # a menu's OWN subtree without walking cross-tree successors (reverse ring edges point back to the
    # parent tree and would otherwise pull in unrelated nodes).
    unified_graph.graph['parent_child_map'] = parent_child_map

    return unified_graph

def get_node_info(graph: nx.DiGraph, node_id: str) -> Optional[Dict]:
    """
    Get node information from NetworkX graph
    
    Args:
        graph: NetworkX directed graph
        node_id: Node identifier
        
    Returns:
        Node information dictionary or None if not found
    """
    if node_id not in graph.nodes:
        return None
        
    return dict(graph.nodes[node_id])

def get_edge_action(graph: nx.DiGraph, from_node: str, to_node: str) -> Optional[str]:
    """
    Get navigation action between two nodes
    
    Args:
        graph: NetworkX directed graph
        from_node: Source node ID
        to_node: Target node ID
        
    Returns:
        Primary action command string or None if edge doesn't exist
    """
    if not graph.has_edge(from_node, to_node):
        return None
        
    edge_data = graph.edges[from_node, to_node]
    action_sets = edge_data.get('action_sets', [])
    default_action_set_id = edge_data.get('default_action_set_id')
    
    if action_sets and default_action_set_id:
        default_set = next((s for s in action_sets if s['id'] == default_action_set_id), None)
        if default_set:
            actions = default_set.get('actions', [])
            if actions:
                return actions[0].get('command')
    
    return None

def get_entry_points(graph: nx.DiGraph) -> List[str]:
    """
    Get all entry point nodes from the graph
    
    Args:
        graph: NetworkX directed graph
        
    Returns:
        List of entry point node IDs
    """
    entry_points = []
    for node_id, node_data in graph.nodes(data=True):
        if node_data.get('is_entry_point', False):
            entry_points.append(node_id)
    
    return entry_points

def get_exit_points(graph: nx.DiGraph) -> List[str]:
    """
    Get all exit point nodes from the graph
    
    Args:
        graph: NetworkX directed graph
        
    Returns:
        List of exit point node IDs
    """
    exit_points = []
    for node_id, node_data in graph.nodes(data=True):
        if node_data.get('is_exit_point', False):
            exit_points.append(node_id)
    
    return exit_points

def validate_graph(graph: nx.DiGraph) -> Dict:
    """
    Validate the navigation graph for potential issues
    
    Args:
        graph: NetworkX directed graph
        
    Returns:
        Validation results dictionary
    """
    issues = []
    warnings = []
    
    # Check for isolated nodes
    isolated = list(nx.isolates(graph))
    if isolated:
        warnings.append(f"Found {len(isolated)} isolated nodes: {isolated}")
    
    # Check for entry points
    entry_points = get_entry_points(graph)
    if not entry_points:
        issues.append("No entry point nodes found")
    elif len(entry_points) > 1:
        warnings.append(f"Multiple entry points found: {entry_points}")
    
    # Check for unreachable nodes
    if entry_points:
        reachable = nx.descendants(graph, entry_points[0])
        reachable.add(entry_points[0])
        unreachable = set(graph.nodes) - reachable
        if unreachable:
            warnings.append(f"Found {len(unreachable)} unreachable nodes: {list(unreachable)}")
    
    # Check for missing action sets
    missing_action_sets = []
    for from_node, to_node, edge_data in graph.edges(data=True):
        action_sets = edge_data.get('action_sets', [])
        if not action_sets:
            missing_action_sets.append(f"{from_node} -> {to_node}")
    
    if missing_action_sets:
        warnings.append(f"Found {len(missing_action_sets)} edges without action_sets")
    
    return {
        'is_valid': len(issues) == 0,
        'issues': issues,
        'warnings': warnings,
        'stats': {
            'nodes': len(graph.nodes),
            'edges': len(graph.edges),
            'entry_points': len(entry_points),
            'exit_points': len(get_exit_points(graph)),
            'isolated_nodes': len(isolated)
        }
    }


def _create_sibling_shortcuts(G: nx.DiGraph) -> int:
    """
    Create shortcut edges between sibling nodes (nodes sharing same parent)
    ONLY for edges marked with enable_sibling_shortcuts=True
    
    For web/mobile DOM navigation: Nav bars/tab bars are shared across sibling screens,
    so siblings are directly reachable using the same actions as parent → target.
    
    Example:
        home → home_tvguide [enable_sibling_shortcuts: True]
        home → home_replay [enable_sibling_shortcuts: True]
        home → home_saved [enable_sibling_shortcuts: True]
        
    Creates shortcuts:
        home_tvguide ↔ home_replay (using same action as home → home_replay)
        home_tvguide ↔ home_saved (using same action as home → home_saved)
        home_replay ↔ home_saved (using same action as home → home_saved)
    
    Args:
        G: NetworkX directed graph
        
    Returns:
        Number of sibling shortcut edges created
    """
    shortcuts_created = 0
    
    # Find all parent→child edges that opt-in to sibling sharing
    parent_children_map = {}  # parent_id → [(child_id, edge_data), ...]
    
    for from_node, to_node, edge_data in G.edges(data=True):
        # Check if this edge enables sibling shortcuts
        # Look in both edge_data directly and in action_sets
        enable_shortcuts = edge_data.get('enable_sibling_shortcuts', False)
        
        # Also check in action_sets if present (for backward compatibility)
        if not enable_shortcuts:
            action_sets = edge_data.get('action_sets', [])
            if action_sets and len(action_sets) > 0:
                # Check first action set
                enable_shortcuts = action_sets[0].get('enable_sibling_shortcuts', False)
        
        if enable_shortcuts:
            if from_node not in parent_children_map:
                parent_children_map[from_node] = []
            parent_children_map[from_node].append((to_node, edge_data))
    
    # Create shortcuts between siblings
    for parent_node, children in parent_children_map.items():
        if len(children) < 2:
            continue  # Need at least 2 children to create shortcuts
        
        parent_info = get_node_info(G, parent_node) or {}
        parent_label = parent_info.get('label', parent_node)
        
        print(f"[@navigation:graph:sibling_shortcuts] Parent '{parent_label}' has {len(children)} siblings with shortcuts enabled")
        
        # Create bidirectional shortcuts between all sibling pairs
        for i, (sibling_a, _) in enumerate(children):
            for sibling_b, edge_data_b in children[i+1:]:
                # Skip if shortcut already exists
                if G.has_edge(sibling_a, sibling_b):
                    continue
                
                sibling_a_info = get_node_info(G, sibling_a) or {}
                sibling_b_info = get_node_info(G, sibling_b) or {}
                sibling_a_label = sibling_a_info.get('label', sibling_a)
                sibling_b_label = sibling_b_info.get('label', sibling_b)
                
                # Create shortcut: sibling_a → sibling_b (reusing parent → sibling_b actions)
                shortcut_edge_data = {
                    **edge_data_b,  # Copy all edge properties from parent → sibling_b
                    'edge_id': f'sibling_shortcut_{sibling_a}_{sibling_b}',
                    'edge_type': 'SIBLING_SHORTCUT',
                    'is_sibling_shortcut': True,
                    'original_parent': parent_node,
                    'shortcut_info': f"Shortcut from {sibling_a_label} to {sibling_b_label} via shared parent {parent_label}"
                }
                
                G.add_edge(sibling_a, sibling_b, **shortcut_edge_data)
                print(f"[@navigation:graph:sibling_shortcuts]   ✅ {sibling_a_label} → {sibling_b_label}")
                shortcuts_created += 1
                
                # Create reverse shortcut: sibling_b → sibling_a
                # Find parent → sibling_a edge data
                if G.has_edge(parent_node, sibling_a):
                    edge_data_a = G.edges[parent_node, sibling_a]
                    
                    reverse_shortcut_edge_data = {
                        **edge_data_a,  # Copy all edge properties from parent → sibling_a
                        'edge_id': f'sibling_shortcut_{sibling_b}_{sibling_a}',
                        'edge_type': 'SIBLING_SHORTCUT',
                        'is_sibling_shortcut': True,
                        'original_parent': parent_node,
                        'shortcut_info': f"Shortcut from {sibling_b_label} to {sibling_a_label} via shared parent {parent_label}"
                    }
                    
                    G.add_edge(sibling_b, sibling_a, **reverse_shortcut_edge_data)
                    print(f"[@navigation:graph:sibling_shortcuts]   ✅ {sibling_b_label} → {sibling_a_label}")
                    shortcuts_created += 1
    
    return shortcuts_created 