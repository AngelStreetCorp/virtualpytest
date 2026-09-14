"""
AI User Interface Database Operations

CRUD + history/rollback helpers for the AI-learned UI knowledge base
(see docs/agent/navigation/AI_USERINTERFACE.md and setup/db/schema/033_ai_userinterface.sql).

Distinct from `userinterface_db.py` which serves the production `userinterfaces`
table consumed by navigation_trees / scripts. These two systems share nothing.

Schema-enforced rules echoed in the helpers below:
- `verified_against` is NOT NULL on every sub-row append. Helpers raise
  ValueError if a caller forgets it (clearer than waiting for a Supabase 400).
- Sub-row "deletes" set superseded_at/by/reason; rows are never destroyed.
- Parent updates auto-bump `current_version` and write a snapshot to
  `ai_userinterfaces_history` so revert is one call.
"""

from datetime import date, datetime, timezone
from fnmatch import fnmatchcase
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sub-row tables exposed for soft-supersede operations and for the read bundle.
# Layer 2-4 (transitions/verifications/tasks) replace the legacy flows table.
_SUB_TABLES = {
    'screens':         'ai_userinterface_screens',
    'transitions':     'ai_userinterface_transitions',
    'verifications':   'ai_userinterface_verifications',
    'tasks':           'ai_userinterface_tasks',
    'quirks':          'ai_userinterface_quirks',
    'known_hardware':  'ai_userinterface_known_hardware',
    'fingerprints':    'ai_userinterface_fingerprints',
}

# verifications/tasks don't have a superseded_at column (write-then-replace
# semantics, not append-only). get_ai_userinterface must only filter by
# superseded_at on the tables that actually have it.
_SOFT_DELETE_TABLES = {'screens', 'transitions', 'quirks', 'known_hardware', 'fingerprints'}

_FINGERPRINT_TYPES = ('software_version_glob', 'foreground_package', 'url_host')


def get_supabase():
    """Get the Supabase client instance (matches sibling _db modules)."""
    return get_supabase_client()


# ===========================================================================
# READ
# ===========================================================================

def list_ai_userinterfaces(team_id: str, category: Optional[str] = None) -> List[Dict]:
    """List parent rows (no sub-rows). Optionally filter by category."""
    supabase = get_supabase()
    if not team_id:
        print('[@db:ai_userinterface_db:list_ai_userinterfaces] ERROR: team_id required')
        return []
    try:
        q = supabase.table('ai_userinterfaces').select('*').eq('team_id', team_id)
        if category:
            q = q.eq('category', category)
        q = q.order('ui_id')
        result = q.execute()
        return result.data or []
    except Exception as e:
        print(f'[@db:ai_userinterface_db:list_ai_userinterfaces] EXCEPTION: {type(e).__name__}: {e}')
        return []


def get_ai_userinterface(
    ui_id: str, team_id: str,
    include_superseded: bool = False,
    variant_id: Optional[str] = None,
) -> Optional[Dict]:
    """
    Fetch a parent row plus all active sub-rows (or all rows if
    include_superseded=True). Returns None if not found.

    If `variant_id` is provided:
      - the effective `ui_pack_markdown` returned on the parent is the
        variant-specific compiled pack (from parent.ui_pack_markdown_variants[variant_id])
        if one exists; otherwise the default ui_pack_markdown;
      - transitions are filtered so variant-specific rows SHADOW the default
        rows for the same (from_screen, item_label) pair. Transitions with
        a different variant_id are hidden.

    Returned shape:
        {
          'parent': {...ai_userinterfaces row..., 'effective_variant_id': <str or None>},
          'screens': [...], 'transitions': [...], 'verifications': [...],
          'tasks': [...], 'quirks': [...], 'known_hardware': [...], 'fingerprints': [...]
        }
    """
    supabase = get_supabase()
    if not (ui_id and team_id):
        print('[@db:ai_userinterface_db:get_ai_userinterface] ERROR: ui_id and team_id required')
        return None
    try:
        parent_q = (
            supabase.table('ai_userinterfaces').select('*')
            .eq('team_id', team_id).eq('ui_id', ui_id).limit(1).execute()
        )
        if not parent_q.data:
            return None
        parent = parent_q.data[0]

        # Variant-aware pack resolution
        parent['effective_variant_id'] = variant_id
        if variant_id:
            variants_map = parent.get('ui_pack_markdown_variants') or {}
            # variants_map can arrive as dict (jsonb) or as text; normalise
            if isinstance(variants_map, str):
                try:
                    import json as _json
                    variants_map = _json.loads(variants_map)
                except Exception:
                    variants_map = {}
            variant_pack = (variants_map or {}).get(variant_id)
            if variant_pack:
                parent['ui_pack_markdown'] = variant_pack
                parent['_pack_source'] = f'variant:{variant_id}'
            else:
                parent['_pack_source'] = 'variant_not_found:fallback_default'
        else:
            parent['_pack_source'] = 'default'

        out: Dict[str, Any] = {'parent': parent}
        for short, table in _SUB_TABLES.items():
            sq = (
                supabase.table(table).select('*')
                .eq('ai_userinterface_id', parent['id'])
                .eq('team_id', team_id)
            )
            if not include_superseded and short in _SOFT_DELETE_TABLES:
                sq = sq.is_('superseded_at', 'null')
            sq = sq.order('added_at')
            rows = sq.execute().data or []

            # Variant-aware shadowing for transitions: when variant_id is set,
            # variant-specific rows override the null-default row for the same
            # (from_screen, item_label). When variant_id is null, only return
            # the null-default rows (hide any variant-specific content from a
            # caller who didn't request a variant).
            if short == 'transitions':
                if variant_id:
                    # Keep: (variant matches) or (variant is null AND no variant-specific row exists for same key)
                    variant_keys = {
                        (r.get('from_screen'), r.get('item_label'))
                        for r in rows if r.get('variant_id') == variant_id
                    }
                    rows = [
                        r for r in rows
                        if r.get('variant_id') == variant_id
                        or (r.get('variant_id') is None
                            and (r.get('from_screen'), r.get('item_label')) not in variant_keys)
                    ]
                else:
                    rows = [r for r in rows if r.get('variant_id') is None]

            out[short] = rows
        return out
    except Exception as e:
        print(f'[@db:ai_userinterface_db:get_ai_userinterface] EXCEPTION: {type(e).__name__}: {e}')
        return None


# --- Fingerprint matching helpers (pure functions — unit-tested without a DB
# --- in test_ai_userinterface_resolve.py) -----------------------------------

_WILDCARD_CHARS = '*?[]'


def _pattern_literal_count(pattern: str) -> int:
    """Count of literal (non-wildcard) characters in a glob pattern."""
    return len(pattern) - sum(pattern.count(c) for c in _WILDCARD_CHARS)


def _pattern_wildcard_count(pattern: str) -> int:
    """Count of wildcard characters (*?[]) in a glob pattern."""
    return sum(pattern.count(c) for c in _WILDCARD_CHARS)


def _rank_fingerprint_matches(rows: List[Dict], value: str, glob: bool = True) -> List[Dict]:
    """
    Filter fingerprint `rows` (dicts with at least 'pattern') to those matching
    `value`, ranked most-specific first.

    Match rule: fnmatchcase(value, pattern) when glob=True (software_version_glob);
    plain equality otherwise (foreground_package / url_host).

    Ranking (deterministic — replaces the old "first row in arbitrary DB order"):
      1. Most literal characters wins (pattern length minus wildcard chars *?[]).
         'EXSTB001-FWR-PRD-04.02-*' beats 'EXSTB001-*'.
      2. Tie-break: fewest wildcard characters.
      3. Tie-break: newest row (added_at descending).
    """
    matched = [
        r for r in rows
        if (fnmatchcase(value, r['pattern']) if glob else value == r['pattern'])
    ]
    # Two stable sorts: newest-first, then specificity — full ties keep newest-first.
    matched.sort(key=lambda r: str(r.get('added_at') or r.get('created_at') or ''), reverse=True)
    matched.sort(key=lambda r: (-_pattern_literal_count(r['pattern']),
                                _pattern_wildcard_count(r['pattern'])))
    return matched


def _literal_prefix(pattern: str) -> str:
    """Pattern text up to (not including) the first wildcard char."""
    for i, c in enumerate(pattern):
        if c in _WILDCARD_CHARS:
            return pattern[:i]
    return pattern


def _prefix_overlap(value: str, pattern: str) -> int:
    """Common-prefix length between `value` and the pattern's literal prefix."""
    n = 0
    for a, b in zip(value, _literal_prefix(pattern)):
        if a != b:
            break
        n += 1
    return n


def resolve_ai_userinterface(
    team_id: str, fingerprint_type: str, value: str
) -> Optional[Dict]:
    """
    Map a runtime fingerprint to a UI.

    For fingerprint_type='software_version_glob' the registered `pattern`
    is a glob (fnmatch syntax) matched against `value`. For exact-match
    types (foreground_package, url_host) we compare equality.

    When several patterns match, the most specific one wins (see
    _rank_fingerprint_matches). The returned parent row carries a '_resolve'
    key describing the decision:
        {'matched_pattern': str,
         'also_matched': [{'ui_id', 'pattern'}, ...],   # the losing matches
         'ambiguous': bool}                              # losers point at a DIFFERENT UI

    Returns the parent ai_userinterfaces row, or None on no match. Use
    resolve_ai_userinterface_verbose when the caller needs near-miss
    diagnostics for the no-match case.
    """
    return resolve_ai_userinterface_verbose(team_id, fingerprint_type, value)['matched']


def resolve_ai_userinterface_verbose(
    team_id: str, fingerprint_type: str, value: str
) -> Dict:
    """
    Same resolution as resolve_ai_userinterface, but never silent on no-match.

    Returns:
        {'matched': <parent row with '_resolve', or None>,
         'near_misses': [{'ui_id', 'pattern', 'overlap_chars'}, ...]}  # up to 3

    near_misses is only populated when nothing matched: the registered patterns
    whose literal prefix overlaps `value` the most, so the caller can see WHY
    nothing matched (typo in a glob, version bumped past the pattern, ...).
    """
    out: Dict[str, Any] = {'matched': None, 'near_misses': []}
    supabase = get_supabase()
    if fingerprint_type not in _FINGERPRINT_TYPES:
        print(f'[@db:ai_userinterface_db:resolve_ai_userinterface_verbose] ERROR: bad fingerprint_type {fingerprint_type!r}')
        return out
    if not (team_id and value):
        return out
    try:
        fp_q = (
            supabase.table('ai_userinterface_fingerprints')
            .select('id, ai_userinterface_id, pattern, added_at')
            .eq('team_id', team_id).eq('fingerprint_type', fingerprint_type)
            .is_('superseded_at', 'null').execute()
        )
        rows = fp_q.data or []
        matches = _rank_fingerprint_matches(
            rows, value, glob=(fingerprint_type == 'software_version_glob')
        )

        if not matches:
            # Near-miss diagnostics: closest literal-prefix overlap first;
            # tie-break by pattern text for determinism.
            scored = sorted(rows, key=lambda r: (-_prefix_overlap(value, r['pattern']), r['pattern']))[:3]
            if scored:
                slug_q = (
                    supabase.table('ai_userinterfaces').select('id, ui_id')
                    .in_('id', list({r['ai_userinterface_id'] for r in scored}))
                    .eq('team_id', team_id).execute()
                )
                slugs = {p['id']: p['ui_id'] for p in (slug_q.data or [])}
                out['near_misses'] = [
                    {'ui_id': slugs.get(r['ai_userinterface_id']),
                     'pattern': r['pattern'],
                     'overlap_chars': _prefix_overlap(value, r['pattern'])}
                    for r in scored
                ]
            return out

        best = matches[0]
        parents_q = (
            supabase.table('ai_userinterfaces').select('*')
            .in_('id', list({r['ai_userinterface_id'] for r in matches}))
            .eq('team_id', team_id).execute()
        )
        by_id = {p['id']: p for p in (parents_q.data or [])}
        parent = by_id.get(best['ai_userinterface_id'])
        if not parent:
            return out
        parent = dict(parent)
        parent['_resolve'] = {
            'matched_pattern': best['pattern'],
            'also_matched': [
                {'ui_id': (by_id.get(r['ai_userinterface_id']) or {}).get('ui_id'),
                 'pattern': r['pattern']}
                for r in matches[1:]
            ],
            # Ambiguous only when a losing pattern points at a DIFFERENT UI.
            # Several patterns for the same UI all matching is redundancy, not ambiguity.
            'ambiguous': len({r['ai_userinterface_id'] for r in matches}) > 1,
        }
        out['matched'] = parent
        return out
    except Exception as e:
        print(f'[@db:ai_userinterface_db:resolve_ai_userinterface_verbose] EXCEPTION: {type(e).__name__}: {e}')
        return out


def get_ai_userinterface_history(ai_userinterface_id: str, team_id: str) -> List[Dict]:
    """All version snapshots for a UI, oldest first."""
    supabase = get_supabase()
    try:
        result = (
            supabase.table('ai_userinterfaces_history').select('*')
            .eq('ai_userinterface_id', ai_userinterface_id)
            .eq('team_id', team_id)
            .order('version_number')
            .execute()
        )
        return result.data or []
    except Exception as e:
        print(f'[@db:ai_userinterface_db:get_ai_userinterface_history] EXCEPTION: {type(e).__name__}: {e}')
        return []


# ===========================================================================
# PARENT CRUD (with auto-history)
# ===========================================================================

def _snapshot_parent(parent_row: Dict, modification_type: str, modified_by: str,
                     changes_summary: Optional[str], restored_from_version: Optional[int]) -> bool:
    """Insert a row into ai_userinterfaces_history capturing the current parent state."""
    supabase = get_supabase()
    try:
        supabase.table('ai_userinterfaces_history').insert({
            'ai_userinterface_id': parent_row['id'],
            'team_id':              parent_row['team_id'],
            'version_number':       parent_row['current_version'],
            'modification_type':    modification_type,
            'modified_by':          modified_by,
            'snapshot':             parent_row,
            'changes_summary':      changes_summary,
            'restored_from_version': restored_from_version,
        }).execute()
        return True
    except Exception as e:
        print(f'[@db:ai_userinterface_db:_snapshot_parent] EXCEPTION: {type(e).__name__}: {e}')
        return False


def create_ai_userinterface(data: Dict, team_id: str, created_by: str) -> Optional[Dict]:
    """
    Create a new parent row + initial history snapshot.

    Required `data` keys: ui_id, category, version. Plus the category-specific
    field (operator for stb; app for android-*; domain for web) — the DB CHECK
    will reject otherwise.

    Optional `data.userinterface_id`: uuid of the linked PRODUCTION
    `userinterfaces` row (same team). Soft link — no FK; see the migration
    20260716_ai_userinterface_linkage.sql for why.
    """
    supabase = get_supabase()
    if not (team_id and created_by):
        raise ValueError('team_id and created_by are required')
    for k in ('ui_id', 'category', 'version'):
        if not data.get(k):
            raise ValueError(f'data.{k} is required')

    insert_data = {
        'ui_id':                  data['ui_id'],
        'category':               data['category'],
        'operator':               data.get('operator'),
        'app':                    data.get('app'),
        'app_package':            data.get('app_package'),
        'domain':                 data.get('domain'),
        'version':                data['version'],
        'middleware_version':     data.get('middleware_version'),
        'identifying_cues':       data.get('identifying_cues'),
        'navigation_primitives':  data.get('navigation_primitives'),
        'hardware_deltas':        data.get('hardware_deltas'),
        'unknown_todo':           data.get('unknown_todo'),
        'last_verified':          data.get('last_verified'),
        'userinterface_id':       data.get('userinterface_id'),
        'current_version':        1,
        'team_id':                team_id,
    }
    try:
        result = supabase.table('ai_userinterfaces').insert(insert_data).execute()
        if not result.data:
            return None
        parent = result.data[0]
        _snapshot_parent(parent, 'create', created_by,
                         f'Initial creation by {created_by}', None)
        return parent
    except Exception as e:
        print(f'[@db:ai_userinterface_db:create_ai_userinterface] EXCEPTION: {type(e).__name__}: {e}')
        return None


_PARENT_EDITABLE_FIELDS = {
    'identifying_cues', 'navigation_primitives', 'hardware_deltas', 'unknown_todo',
    'last_verified', 'middleware_version', 'version',
    'operator', 'app', 'app_package', 'domain',  # rare but possible
    'userinterface_id',  # soft link to the production userinterfaces row
}


def update_ai_userinterface(
    ui_id: str, fields: Dict, team_id: str, modified_by: str,
    changes_summary: str
) -> Optional[Dict]:
    """
    Apply `fields` to the parent row, bump current_version, and write a
    history snapshot with the new state. Returns the updated parent row.
    """
    supabase = get_supabase()
    if not changes_summary:
        raise ValueError('changes_summary is required (audit trail)')
    bad = set(fields) - _PARENT_EDITABLE_FIELDS
    if bad:
        raise ValueError(f'Fields not editable here: {sorted(bad)}')

    try:
        cur_q = (
            supabase.table('ai_userinterfaces').select('*')
            .eq('team_id', team_id).eq('ui_id', ui_id).limit(1).execute()
        )
        if not cur_q.data:
            print(f'[@db:ai_userinterface_db:update_ai_userinterface] No row for ui_id={ui_id}')
            return None
        current = cur_q.data[0]
        new_version = (current.get('current_version') or 0) + 1

        update_payload = dict(fields)
        update_payload['current_version'] = new_version
        update_payload['updated_at'] = datetime.now(timezone.utc).isoformat()

        result = (
            supabase.table('ai_userinterfaces').update(update_payload)
            .eq('id', current['id']).eq('team_id', team_id).execute()
        )
        if not result.data:
            return None
        new_parent = result.data[0]
        _snapshot_parent(new_parent, 'update', modified_by, changes_summary, None)
        return new_parent
    except Exception as e:
        print(f'[@db:ai_userinterface_db:update_ai_userinterface] EXCEPTION: {type(e).__name__}: {e}')
        return None


def revert_ai_userinterface(
    ui_id: str, to_version: int, team_id: str, modified_by: str, reason: str
) -> Optional[Dict]:
    """
    Restore the parent row to the state captured in history version `to_version`.
    Writes a new version (current_version + 1) with modification_type='restore'
    and restored_from_version=to_version. The intervening "wrong" versions
    remain in history for the audit trail.
    """
    supabase = get_supabase()
    if not reason:
        raise ValueError('reason is required when reverting')
    try:
        cur_q = (
            supabase.table('ai_userinterfaces').select('*')
            .eq('team_id', team_id).eq('ui_id', ui_id).limit(1).execute()
        )
        if not cur_q.data:
            return None
        current = cur_q.data[0]

        snap_q = (
            supabase.table('ai_userinterfaces_history').select('*')
            .eq('ai_userinterface_id', current['id'])
            .eq('team_id', team_id).eq('version_number', to_version)
            .limit(1).execute()
        )
        if not snap_q.data:
            print(f'[@db:ai_userinterface_db:revert_ai_userinterface] No history v{to_version} for ui_id={ui_id}')
            return None
        snap = snap_q.data[0]['snapshot']
        if snap.get('team_id') != team_id:
            print('[@db:ai_userinterface_db:revert_ai_userinterface] ERROR: snapshot team_id mismatch')
            return None

        new_version = (current.get('current_version') or 0) + 1
        restore_payload = {k: snap.get(k) for k in _PARENT_EDITABLE_FIELDS if k in snap}
        restore_payload['current_version'] = new_version
        restore_payload['updated_at'] = datetime.now(timezone.utc).isoformat()

        result = (
            supabase.table('ai_userinterfaces').update(restore_payload)
            .eq('id', current['id']).eq('team_id', team_id).execute()
        )
        if not result.data:
            return None
        new_parent = result.data[0]
        _snapshot_parent(
            new_parent, 'restore', modified_by,
            f'Restored from v{to_version}: {reason}', to_version,
        )
        return new_parent
    except Exception as e:
        print(f'[@db:ai_userinterface_db:revert_ai_userinterface] EXCEPTION: {type(e).__name__}: {e}')
        return None


# ===========================================================================
# APPEND (sub-rows). verified_against is mandatory by schema; we re-check here
# to surface a clear ValueError instead of a Supabase 400.
# ===========================================================================

def _resolve_parent_id(ui_id: str, team_id: str) -> Optional[str]:
    supabase = get_supabase()
    q = (
        supabase.table('ai_userinterfaces').select('id')
        .eq('team_id', team_id).eq('ui_id', ui_id).limit(1).execute()
    )
    return q.data[0]['id'] if q.data else None


def add_ai_userinterface_screen(
    ui_id: str, name: str, identifying_cues: Optional[str], exits: Optional[str],
    verified_against: str, team_id: str, added_by: str,
) -> Optional[Dict]:
    if not all([ui_id, name, verified_against, team_id, added_by]):
        raise ValueError('ui_id, name, verified_against, team_id, added_by are required')
    parent_id = _resolve_parent_id(ui_id, team_id)
    if not parent_id:
        return None
    supabase = get_supabase()
    try:
        result = supabase.table('ai_userinterface_screens').insert({
            'ai_userinterface_id': parent_id,
            'name':                name,
            'identifying_cues':    identifying_cues,
            'exits':               exits,
            'verified_against':    verified_against,
            'added_by':            added_by,
            'team_id':             team_id,
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f'[@db:ai_userinterface_db:add_ai_userinterface_screen] EXCEPTION: {type(e).__name__}: {e}')
        return None


def _validate_transition_actions(actions) -> List[Dict]:
    """
    Validate the `actions` array on an ai_userinterface_transitions row — same
    shape as execute_device_action.actions[]. Reject shorthand ("×", "x N",
    "repeat:N") — the agent emits these verbatim via execute_device_action.
    For action_type='infrared', reject iterator>1 (IR pulses get dropped
    without inter-call spacing).
    """
    if not isinstance(actions, list) or not actions:
        raise ValueError('actions must be a non-empty list')
    for i, a in enumerate(actions):
        if not isinstance(a, dict):
            raise ValueError(f'actions[{i}] must be an object')
        if not a.get('command'):
            raise ValueError(f'actions[{i}].command is required')
        params = a.get('params') or {}
        if not isinstance(params, dict):
            raise ValueError(f'actions[{i}].params must be an object')
        for k, v in params.items():
            if isinstance(v, str) and ('×' in v or ' x ' in f' {v} ' or v.lower().startswith('repeat')):
                raise ValueError(
                    f"actions[{i}].params.{k}={v!r} contains shorthand. "
                    f'Expand each press into its own action object.'
                )
        if params.get('action_type') == 'infrared':
            iterator = a.get('iterator', 1)
            try: iterator = int(iterator)
            except Exception: iterator = 1
            if iterator > 1:
                raise ValueError(
                    f"actions[{i}]: iterator>1 is forbidden for action_type='infrared' — "
                    f"IR pulses get dropped. Expand into {iterator} separate actions."
                )
    return actions


_VALID_VERIFICATION_KINDS = ('present', 'regex', 'value_matches')
_VALID_VERIFICATION_SEVERITIES = ('hard', 'soft')
_VALID_TRANSITION_STATUSES = ('unverified', 'deterministic', 'flaky', 'observed')


def add_ai_userinterface_transition(
    ui_id: str, from_screen: str, item_label: str, actions,
    team_id: str, added_by: str,
    to_screen: Optional[str] = None,
    verification_status: str = 'unverified',
) -> Optional[Dict]:
    """Layer 2: append one transition (edge) between screens."""
    if not all([ui_id, from_screen, item_label, team_id, added_by]):
        raise ValueError('ui_id, from_screen, item_label, team_id, added_by are required')
    if verification_status not in _VALID_TRANSITION_STATUSES:
        raise ValueError(f'verification_status must be one of {_VALID_TRANSITION_STATUSES}')
    actions = _validate_transition_actions(actions)
    parent_id = _resolve_parent_id(ui_id, team_id)
    if not parent_id:
        return None
    supabase = get_supabase()
    try:
        result = supabase.table('ai_userinterface_transitions').insert({
            'ai_userinterface_id': parent_id,
            'from_screen':         from_screen,
            'item_label':          item_label,
            'actions':             actions,
            'to_screen':           to_screen,
            'verification_status': verification_status,
            'added_by':            added_by,
            'team_id':             team_id,
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f'[@db:ai_userinterface_db:add_ai_userinterface_transition] EXCEPTION: {type(e).__name__}: {e}')
        return None


def add_ai_userinterface_verification(
    ui_id: str, screen_name: str, kind: str, selector: str,
    team_id: str, added_by: str,
    expected: Optional[str] = None, severity: str = 'hard',
) -> Optional[Dict]:
    """Layer 3: append one per-screen assertion."""
    if not all([ui_id, screen_name, kind, selector, team_id, added_by]):
        raise ValueError('ui_id, screen_name, kind, selector, team_id, added_by are required')
    if kind not in _VALID_VERIFICATION_KINDS:
        raise ValueError(f'kind must be one of {_VALID_VERIFICATION_KINDS}')
    if severity not in _VALID_VERIFICATION_SEVERITIES:
        raise ValueError(f'severity must be one of {_VALID_VERIFICATION_SEVERITIES}')
    parent_id = _resolve_parent_id(ui_id, team_id)
    if not parent_id:
        return None
    supabase = get_supabase()
    try:
        result = supabase.table('ai_userinterface_verifications').insert({
            'ai_userinterface_id': parent_id,
            'screen_name':         screen_name,
            'kind':                kind,
            'selector':            selector,
            'expected':            expected,
            'severity':            severity,
            'added_by':            added_by,
            'team_id':             team_id,
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f'[@db:ai_userinterface_db:add_ai_userinterface_verification] EXCEPTION: {type(e).__name__}: {e}')
        return None


def add_ai_userinterface_task(
    ui_id: str, task_name: str, steps_md: str,
    team_id: str, added_by: str,
    description: Optional[str] = None,
    verify_assertions: Optional[List[Dict]] = None,
    returns: Optional[List[Dict]] = None,
) -> Optional[Dict]:
    """Layer 4: append one named task (user-facing flow)."""
    if not all([ui_id, task_name, steps_md, team_id, added_by]):
        raise ValueError('ui_id, task_name, steps_md, team_id, added_by are required')
    parent_id = _resolve_parent_id(ui_id, team_id)
    if not parent_id:
        return None
    supabase = get_supabase()
    try:
        result = supabase.table('ai_userinterface_tasks').insert({
            'ai_userinterface_id': parent_id,
            'task_name':           task_name,
            'description':         description,
            'steps_md':            steps_md,
            'verify_assertions':   verify_assertions,
            'returns':             returns,
            'added_by':            added_by,
            'team_id':             team_id,
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f'[@db:ai_userinterface_db:add_ai_userinterface_task] EXCEPTION: {type(e).__name__}: {e}')
        return None


def add_ai_userinterface_quirk(
    ui_id: str, description: str, verified_against: str, team_id: str, added_by: str,
) -> Optional[Dict]:
    if not all([ui_id, description, verified_against, team_id, added_by]):
        raise ValueError('ui_id, description, verified_against, team_id, added_by are required')
    parent_id = _resolve_parent_id(ui_id, team_id)
    if not parent_id:
        return None
    supabase = get_supabase()
    try:
        result = supabase.table('ai_userinterface_quirks').insert({
            'ai_userinterface_id': parent_id,
            'description':         description,
            'verified_against':    verified_against,
            'added_by':            added_by,
            'team_id':             team_id,
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f'[@db:ai_userinterface_db:add_ai_userinterface_quirk] EXCEPTION: {type(e).__name__}: {e}')
        return None


def add_ai_userinterface_known_hardware(
    ui_id: str, model: str, hw_rev: Optional[str], verified_at,
    team_id: str, added_by: str,
) -> Optional[Dict]:
    if not all([ui_id, model, verified_at, team_id, added_by]):
        raise ValueError('ui_id, model, verified_at, team_id, added_by are required')
    parent_id = _resolve_parent_id(ui_id, team_id)
    if not parent_id:
        return None
    supabase = get_supabase()
    try:
        result = supabase.table('ai_userinterface_known_hardware').insert({
            'ai_userinterface_id': parent_id,
            'model':               model,
            'hw_rev':              hw_rev,
            'verified_at':         _date_str(verified_at),
            'added_by':            added_by,
            'team_id':             team_id,
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f'[@db:ai_userinterface_db:add_ai_userinterface_known_hardware] EXCEPTION: {type(e).__name__}: {e}')
        return None


def add_ai_userinterface_fingerprint(
    ui_id: str, fingerprint_type: str, pattern: str,
    verified_against: str, team_id: str, added_by: str,
) -> Optional[Dict]:
    if fingerprint_type not in _FINGERPRINT_TYPES:
        raise ValueError(f'fingerprint_type must be one of {_FINGERPRINT_TYPES}')
    if not all([ui_id, pattern, verified_against, team_id, added_by]):
        raise ValueError('ui_id, pattern, verified_against, team_id, added_by are required')
    parent_id = _resolve_parent_id(ui_id, team_id)
    if not parent_id:
        return None
    supabase = get_supabase()
    try:
        result = supabase.table('ai_userinterface_fingerprints').insert({
            'ai_userinterface_id': parent_id,
            'fingerprint_type':    fingerprint_type,
            'pattern':             pattern,
            'verified_against':    verified_against,
            'added_by':            added_by,
            'team_id':             team_id,
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f'[@db:ai_userinterface_db:add_ai_userinterface_fingerprint] EXCEPTION: {type(e).__name__}: {e}')
        return None


# ===========================================================================
# SOFT-DELETE (no hard deletes — the audit trail is the safety net)
# ===========================================================================

def supersede_ai_userinterface_row(
    table_short: str, row_id: str, team_id: str, superseded_by: str, superseded_reason: str,
) -> bool:
    """
    Mark a sub-row as superseded. Never DELETE.

    Only tables with a superseded_at column are eligible:
    {'screens','transitions','quirks','known_hardware','fingerprints'}.
    Verifications and tasks use write-then-replace semantics; use their
    respective CRUD routes instead.
    """
    if table_short not in _SOFT_DELETE_TABLES:
        raise ValueError(f'table_short must be one of {sorted(_SOFT_DELETE_TABLES)}')
    if not (row_id and team_id and superseded_by and superseded_reason):
        raise ValueError('row_id, team_id, superseded_by, superseded_reason are required')
    supabase = get_supabase()
    try:
        result = supabase.table(_SUB_TABLES[table_short]).update({
            'superseded_at':     datetime.now(timezone.utc).isoformat(),
            'superseded_by':     superseded_by,
            'superseded_reason': superseded_reason,
        }).eq('id', row_id).eq('team_id', team_id).execute()
        return bool(result.data)
    except Exception as e:
        print(f'[@db:ai_userinterface_db:supersede_ai_userinterface_row] EXCEPTION: {type(e).__name__}: {e}')
        return False


# ===========================================================================
# Helpers
# ===========================================================================

def _date_str(value) -> str:
    """Accept date / datetime / ISO str and normalise to YYYY-MM-DD."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
