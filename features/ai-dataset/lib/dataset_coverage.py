"""Dataset coverage of the canonical apps (TASK-27 step 4h).

One function, ``build_coverage``, used by the ``/server/training-samples/coverage`` route and
by ``scripts/coverage_report.py``. The maths (``app_coverage``, ``summarize``) is pure; the
readers are read-only and team-scoped.

Definitions (``k`` defaults to 3):

* **visible screens** of an app: distinct ``node_id`` of its visible screen nodes
  (``dataset_scope.is_visible_screen``) in its root tree and nested subtrees. ``node_rows``
  also reports the row count (a nested subtree repeats its parent node).
* a **labelled** ``screen-id`` sample of a screen: a row of that app (``userinterface``)
  whose ``ground_truth.node_id`` is that screen. The label, not the row's ``node_id``
  column, decides: failed-verification rows carry ``node_id = null`` and get the screen
  from the human. Pass-1 dedup already refused near-identical frames, so each stored row is
  one **distinct** sample.
* **≥1** / **≥k**: screens with at least 1 / at least ``k`` labelled samples.
* **eval-verified**: ``split='eval'`` and ``label_source='human'`` rows of the app.
* **off-tree labels**: distinct labels of ``{node_id: null, label}`` answers (a screen not in
  the tree). **stale labels**: ``ground_truth.node_id`` values not in the tree any more.
* **missing screens**: visible screens with no labelled sample; **thin screens**: 1..k-1.
* **exhaustiveness**: screens with ≥k samples / visible screens, summed over the apps.

``focus`` is counted per app like ``screen-id`` rows (any labelled row). ``banner`` rows
carry no userinterface (they come from zap events), so they are counted per platform by
their ``device_model``.

**Step 4k: screens are screen groups.** A "screen" is a screen group of the app
(``lib/screen_group_scope``, core ``screen_groups``: Home with any tab focused is one screen)
that holds at least one visible screen node; ``screens``, ``≥1``, ``≥k``, missing and thin count
groups. A labelled sample counts for the group of its node (``ground_truth.node``, or
``ground_truth.node_id`` on a pre-4k label). Per group, ``states`` lists its visible nodes
(its focus states) with their own sample counts, and ``states_covered`` how many have ≥1;
``groups`` lists every group of the app (group -> member nodes) for the panel. ``node_screens``
keeps the distinct visible node count. An app whose groups cannot be derived counts each
node as its own group (the step 4h numbers).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

try:  # imported as features.ai-dataset.lib.dataset_coverage (route, scripts, tests)
    from . import dataset_scope as scope
except ImportError:  # pragma: no cover - loaded as a top-level module
    import dataset_scope as scope  # type: ignore

DEFAULT_K = 3
MAX_K = 50
COUNTED_FAMILIES = ('screen-id', 'focus', 'banner')
SAMPLE_COLUMNS = ('family, userinterface, device_model, ground_truth, label_source, split, '
                  'eval_version, reference:source_ref->>reference')


def clamp_k(value: Any, default: int = DEFAULT_K) -> int:
    try:
        return max(1, min(MAX_K, int(value)))
    except (TypeError, ValueError):
        return default


def is_labelled(row: Dict[str, Any]) -> bool:
    return row.get('ground_truth') is not None and row.get('label_source') not in (None, 'none')


def is_eval_verified(row: Dict[str, Any]) -> bool:
    return row.get('split') == 'eval' and row.get('label_source') == 'human'


def _pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


# ---- pure maths ----------------------------------------------------------------------------

def _singletons(screens: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    return {nid: {'node_id': nid, 'label': label, 'members': [{'node_id': nid, 'label': label, 'focus': None}]}
            for nid, label in screens.items()}


def app_coverage(name: str, platform: str, models: Sequence[str], node_rows: Sequence[Dict[str, Any]],
                 samples: Iterable[Dict[str, Any]], k: int, groups: Any = None) -> Dict[str, Any]:
    """Coverage of one app from its visible screen node rows, its sample rows and its screen
    groups (``screen_groups.ScreenGroups``; None = every node is its own screen)."""
    screens: Dict[str, str] = {}
    for n in node_rows:
        screens.setdefault(str(n['node_id']), str(n.get('label') or n['node_id']))

    # Screen groups restricted to the visible nodes; a group with none of them is not a screen.
    raw = groups.groups if groups is not None else _singletons(screens)
    group_of: Dict[str, str] = {}
    visible_groups: Dict[str, Dict[str, Any]] = {}
    for gid, g in raw.items():
        states = [m for m in g['members'] if m['node_id'] in screens]
        if not states:
            continue
        visible_groups[gid] = {'node_id': gid, 'label': g['label'], 'states': states}
        for m in states:
            group_of[m['node_id']] = gid
    for nid, label in screens.items():   # a visible node the groups do not know: its own screen
        if nid not in group_of:
            visible_groups[nid] = {'node_id': nid, 'label': label,
                                   'states': [{'node_id': nid, 'label': label, 'focus': None}]}
            group_of[nid] = nid

    per_group: Counter = Counter()
    per_node: Counter = Counter()
    offtree, stale = set(), set()
    screen_rows = labelled = eval_verified = seeded = 0
    focus = {'rows': 0, 'labelled': 0, 'eval_verified': 0}
    for r in samples:
        if r.get('userinterface') != name:
            continue
        family = r.get('family')
        if family == 'focus':
            focus['rows'] += 1
            focus['labelled'] += 1 if is_labelled(r) else 0
            focus['eval_verified'] += 1 if is_eval_verified(r) else 0
            continue
        if family != 'screen-id':
            continue
        screen_rows += 1
        eval_verified += 1 if is_eval_verified(r) else 0
        seeded += 1 if r.get('reference') == 'navigation' else 0
        truth = r.get('ground_truth')
        if not is_labelled(r) or not isinstance(truth, dict):
            continue
        labelled += 1
        node_id = truth.get('node_id')
        if node_id is None:
            text = str(truth.get('label') or '').strip().lower()
            if text:
                offtree.add(text)
            continue
        node = str(truth['node']) if truth.get('node') is not None else str(node_id)
        if node in group_of:
            per_group[group_of[node]] += 1
            per_node[node] += 1
        elif str(node_id) in visible_groups:          # a group label whose node is not visible
            per_group[str(node_id)] += 1
        else:
            stale.add(node)

    def entry(gid):
        g = visible_groups[gid]
        states = [{'node_id': m['node_id'], 'label': m['label'], 'focus': m.get('focus'),
                   'samples': per_node.get(m['node_id'], 0)} for m in g['states']]
        return {'node_id': gid, 'label': g['label'], 'samples': per_group.get(gid, 0),
                'states': states, 'states_total': len(states),
                'states_covered': sum(1 for st in states if st['samples'] >= 1)}

    ordered = sorted(visible_groups, key=lambda gid: (visible_groups[gid]['label'].lower(), gid))
    ge1 = sum(1 for gid in visible_groups if per_group.get(gid, 0) >= 1)
    gek = sum(1 for gid in visible_groups if per_group.get(gid, 0) >= k)
    return {
        'name': name,
        'platform': platform,
        'models': list(models or []),
        'screens': len(visible_groups),
        'node_screens': len(screens),
        'node_rows': len(node_rows),
        'grouped': groups is not None,
        'screens_ge1': ge1,
        'screens_gek': gek,
        'pct_gek': _pct(gek, len(visible_groups)),
        'screen_id_rows': screen_rows,
        'screen_id_labelled': labelled,
        'seeded_rows': seeded,
        'eval_verified': eval_verified,
        'offtree_labels': sorted(offtree),
        'stale_labels': sorted(stale),
        'groups': [entry(gid) for gid in ordered],
        'missing_screens': [entry(gid) for gid in ordered if per_group.get(gid, 0) == 0],
        'thin_screens': [entry(gid) for gid in ordered if 0 < per_group.get(gid, 0) < k],
        'focus': focus,
    }


def summarize(apps: Sequence[Dict[str, Any]], samples: Iterable[Dict[str, Any]], k: int,
              not_in_scope: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Per-platform and global totals over the apps, plus banner counts per platform."""
    samples = list(samples)
    platforms: Dict[str, Dict[str, Any]] = {}
    for a in apps:
        p = platforms.setdefault(a['platform'], {'platform': a['platform'], 'apps': [], 'screens': 0,
                                                 'screens_ge1': 0, 'screens_gek': 0, 'eval_verified': 0,
                                                 'screen_id_labelled': 0})
        p['apps'].append(a['name'])
        for key in ('screens', 'screens_ge1', 'screens_gek', 'eval_verified', 'screen_id_labelled'):
            p[key] += a[key]
    banner: Dict[str, Counter] = defaultdict(Counter)
    for r in samples:
        if r.get('family') != 'banner':
            continue
        c = banner[scope.platform_of_model(r.get('device_model'))]
        c['rows'] += 1
        c['labelled'] += 1 if is_labelled(r) else 0
        c['eval_verified'] += 1 if is_eval_verified(r) else 0
    for name, p in platforms.items():
        p['pct_gek'] = _pct(p['screens_gek'], p['screens'])
        p['banner'] = dict(banner.get(name, Counter({'rows': 0, 'labelled': 0, 'eval_verified': 0})))
    screens = sum(a['screens'] for a in apps)
    gek = sum(a['screens_gek'] for a in apps)
    return {
        'k': k,
        'global': {'screens': screens,
                   'screens_ge1': sum(a['screens_ge1'] for a in apps),
                   'screens_gek': gek,
                   'eval_verified': sum(a['eval_verified'] for a in apps),
                   'exhaustiveness_pct': _pct(gek, screens)},
        'platforms': sorted(platforms.values(), key=lambda p: p['platform']),
        'apps': list(apps),
        # banner rows of platforms with no canonical app (e.g. android_tv) stay visible here
        'banner_by_platform': {name: dict(c) for name, c in sorted(banner.items())},
        'not_in_scope': list(not_in_scope),
    }


def not_in_scope_entry(ui: Dict[str, Any], node_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    pattern = scope.excluded_pattern(ui['name'])
    return {'name': ui['name'], 'models': list(ui.get('models') or []),
            'platform': scope.platform_of(ui['name'], ui.get('models')),
            'screens': len({n['node_id'] for n in node_rows}),
            'reason': f"excluded ({pattern})" if pattern else 'not in the canonical list'}


def compute(userinterfaces: Sequence[Dict[str, Any]], trees: Sequence[Dict[str, Any]],
            nodes: Sequence[Dict[str, Any]], samples: Sequence[Dict[str, Any]], k: int,
            groups_by_app: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Pure: the whole report from already-loaded rows (``groups_by_app``: app name ->
    ``ScreenGroups`` or None, step 4k)."""
    apps, others = [], []
    for ui in sorted(userinterfaces, key=lambda u: u['name']):
        rows = scope.app_screen_nodes(ui, trees, nodes)
        if scope.scope_refusal(ui['name']) is None:
            apps.append(app_coverage(ui['name'], scope.platform_of(ui['name'], ui.get('models')),
                                     ui.get('models') or [], rows, samples, k,
                                     (groups_by_app or {}).get(ui['name'])))
        else:
            others.append(not_in_scope_entry(ui, rows))
    present = {a['name'] for a in apps}
    report = summarize(apps, samples, k, others)
    # A canonical app the team does not have is reported, not silently dropped.
    report['canonical_missing'] = sorted(set(scope.CANONICAL_USERINTERFACES) - present)
    return report


# ---- readers ---------------------------------------------------------------------------------

def load_samples(team_id: str) -> List[Dict[str, Any]]:
    """The team's ``screen-id`` / ``focus`` / ``banner`` rows, only the columns counted."""
    import json

    rows = scope._paged(lambda: scope._client().table('ai_training_samples').select(SAMPLE_COLUMNS)
                        .eq('team_id', team_id).in_('family', list(COUNTED_FAMILIES)).order('id'))
    for r in rows:
        if isinstance(r.get('ground_truth'), str):
            try:
                r['ground_truth'] = json.loads(r['ground_truth'])
            except ValueError:
                pass
    return rows


def build_coverage(team_id: str, k: int = DEFAULT_K, *,
                   load_uis: Optional[Callable] = None, load_trees: Optional[Callable] = None,
                   load_nodes: Optional[Callable] = None,
                   load_sample_rows: Optional[Callable] = None,
                   load_groups: Optional[Callable] = None) -> Dict[str, Any]:
    """The coverage report of one team (read-only). ``load_groups(team_id, app name)`` gives
    an app's screen groups (step 4k; default ``screen_group_scope.groups_for``)."""
    if not team_id:
        raise ValueError('team_id is required')
    k = clamp_k(k)
    uis = (load_uis or scope.load_userinterfaces)(team_id)
    trees = (load_trees or scope.load_trees)(team_id, [u['id'] for u in uis])
    tree_ids = [t['id'] for t in trees]
    nodes = (load_nodes(team_id, tree_ids) if load_nodes
             else scope.load_screen_nodes(team_id, tree_ids, with_screenshot=False))
    samples = (load_sample_rows or load_samples)(team_id)
    if load_groups is None:
        try:
            from . import screen_group_scope
        except ImportError:  # pragma: no cover - loaded as a top-level module
            import screen_group_scope  # type: ignore
        load_groups = screen_group_scope.groups_for
    groups_by_app = {}
    for ui in uis:
        if scope.scope_refusal(ui['name']) is None:
            try:
                groups_by_app[ui['name']] = load_groups(team_id, ui['name'])
            except Exception as e:  # coverage still renders, per node
                print(f"[dataset_coverage] no screen groups for {ui['name']}: {e}")
                groups_by_app[ui['name']] = None
    report = compute(uis, trees, nodes, samples, k, groups_by_app)
    report['team_id'] = team_id
    return report
