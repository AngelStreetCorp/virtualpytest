"""Phase 1, ON THE SERVER: pick the screen-id samples, download their frames, and write the
candidate screen groups of each app with the checks and reference images of every member node.

Read-only on ai_training_samples, navigation_* and verifications_references; every read is
team-scoped. No OCR, no matching: the server is small (2 CPU, 1.9 GB), files are streamed one by one.

Bundle layout::

    rows.jsonl                 selected samples (+ frames/<id>.jpg)
    export_meta.json           counts, skipped_no_tree per app
    ui/<ui>/groups.json        groups -> members -> verifications (+ reference_file, area), seed
    ui/<ui>/seed/<node>.jpg    the node's seeded reference frame
    ui/<ui>/refs/<name>.jpg    reference images used by image verifications
"""
from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import LAB_TEAM, load_lib

SETS = ('agreed', 'disputed', 'human', 'open')
# 'open' (TASK-27, 2026-10-04): what the Sonnet second pass would take (untriaged, or needs_human
# for disagrees_with_run / conflict / low_confidence); triage_batch.py import-jev settles from it.
OPEN_REASONS = ('disagrees_with_run', 'conflict', 'low_confidence')
FAMILY = 'screen-id'
PAGE_SIZE = 500
MAX_ROWS = 20000
SEED_REFERENCE = 'navigation'
IMAGE_COMMANDS = ('waitForImageToAppear', 'waitForImageToDisappear')
TEXT_COMMAND = 'waitForTextToAppear'
TRIAGE_KEYS = ('status', 'reason', 'teacher_label', 'teacher_answer', 'first_pass')


# ---- selection (pure) ------------------------------------------------------------------------

def triage_of(row: Mapping[str, Any]) -> Dict[str, Any]:
    value = row.get('triage')
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def set_of(row: Mapping[str, Any]) -> Optional[str]:
    """``human`` (label_source human), ``agreed`` (triage agreed) or ``disputed`` (triage excluded,
    disagrees_with_run). A human label wins when a row is also triaged."""
    triage = triage_of(row)
    if row.get('label_source') == 'human':
        return 'human'
    if triage.get('status') == 'agreed':
        return 'agreed'
    if triage.get('status') == 'excluded' and triage.get('reason') == 'disagrees_with_run':
        return 'disputed'
    if row.get('eval_version'):
        return None
    if not triage.get('status') or (triage.get('status') == 'needs_human' and triage.get('reason') in OPEN_REASONS):
        return 'open'
    return None


def select_sets(rows: Sequence[Mapping[str, Any]], sets: Sequence[str], has_tree: Callable[[Optional[str]], bool],
                limit: Optional[int] = None) -> Tuple[List[Tuple[str, Mapping[str, Any]]], Dict[str, int], Counter]:
    """``(selected [(set, row)], skipped_no_tree {ui: n}, taken per set)``. A row whose app has no
    groups (a deleted temporary tree) is skipped and counted, like score_eval.py."""
    selected: List[Tuple[str, Mapping[str, Any]]] = []
    skipped: Dict[str, int] = {}
    taken: Counter = Counter()
    for row in rows:
        name = set_of(row)
        if name not in sets or (limit and taken[name] >= limit):
            continue
        if not has_tree(row.get('userinterface')):
            ui = row.get('userinterface') or '(none)'
            skipped[ui] = skipped.get(ui, 0) + 1
            continue
        selected.append((name, row))
        taken[name] += 1
    return selected, skipped, taken


def row_record(set_name: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    triage = triage_of(row)
    return {'id': str(row['id']), 'team_id': row.get('team_id'), 'set': set_name,
            'userinterface': row.get('userinterface'), 'device_model': row.get('device_model'),
            'node_id': row.get('node_id'), 'source_ref': row.get('source_ref'),
            'ground_truth': row.get('ground_truth'), 'label_source': row.get('label_source'),
            'triage': {k: triage.get(k) for k in TRIAGE_KEYS}, 'dhash': row.get('dhash'),
            'object_key': row.get('object_key')}


def reference_names(params: Mapping[str, Any]) -> List[str]:
    """Names to look a verification's reference up by: reference_name first, then image_path
    (extension dropped)."""
    out: List[str] = []
    for key in ('reference_name', 'image_path'):
        value = str(params.get(key) or '').strip()
        value = value.rsplit('.', 1)[0] if value.lower().endswith(('.jpg', '.jpeg', '.png')) else value
        if value and value not in out:
            out.append(value)
    return out


def pick_reference(params: Mapping[str, Any], refs_by_name: Mapping[str, Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    for name in reference_names(params):
        if name in refs_by_name:
            return refs_by_name[name]
    return None


def check_entry(verification: Mapping[str, Any], refs_by_name: Mapping[str, Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The slim record the evidence phase needs for one verification, or None for other commands."""
    command = str(verification.get('command') or '')
    params = verification.get('params') if isinstance(verification.get('params'), Mapping) else {}
    if command in IMAGE_COMMANDS:
        ref = pick_reference(params, refs_by_name)
        # The host resolves the area from the reference row (database, required); params.area is the fallback.
        area = (ref or {}).get('area') or params.get('area')
        names = reference_names(params)
        return {'command': command, 'name': (ref or {}).get('name') or (names[0] if names else ''),
                'threshold': params.get('threshold'), 'area': area, 'reference': (ref or {}).get('name')}
    if command == TEXT_COMMAND and str(params.get('text') or '').strip():
        return {'command': command, 'name': str(params['text']).strip(), 'threshold': params.get('threshold'),
                'area': params.get('area')}
    return None


# ---- I/O -------------------------------------------------------------------------------------

def fetch_rows(team_id: str, list_fn=None, sources: Sequence[str] = ('run', 'human')) -> List[Dict[str, Any]]:
    """Screen-id rows of the team with these label sources, paged like triage_batch.fetch_rows."""
    if list_fn is None:
        from shared.src.lib.database.ai_training_samples_db import list_samples as list_fn
    rows: List[Dict[str, Any]] = []
    offset = 0
    while offset < MAX_ROWS:
        page, total = list_fn(team_id, family=FAMILY, label_sources=list(sources), limit=PAGE_SIZE, offset=offset)
        rows.extend(page)
        offset += len(page)
        if not page or offset >= total:
            break
    return rows


def _write_json(path: str, value: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(value, f, indent=1, ensure_ascii=False, default=str)


def _download(fn: Callable[[], Mapping[str, Any]], dest: str) -> bool:
    if os.path.exists(dest):
        return True
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    result = fn()
    return bool(result and result.get('success')) and os.path.exists(dest)


def seed_keys(team_id: str, samples_fn=None) -> Dict[Tuple[Optional[str], str], str]:
    """``{(userinterface, node_id): object_key}`` of the seeded navigation reference frames."""
    if samples_fn is None:
        from shared.src.lib.database.ai_training_samples_db import get_samples_by_source_ref as samples_fn
    out: Dict[Tuple[Optional[str], str], str] = {}
    for row in samples_fn(team_id, 'reference', SEED_REFERENCE):
        ref = row.get('source_ref') or {}
        node = ref.get('node_id') or row.get('node_id')
        if node and row.get('object_key'):
            out.setdefault((ref.get('userinterface') or row.get('userinterface'), str(node)), row['object_key'])
    return out


def export_ui(team_id: str, ui: str, groups, bundle: str, seeds: Mapping, refs_fn, storage, cf, nodes: Mapping) -> Dict[str, int]:
    """Write ``ui/<ui>/groups.json`` and its seed and reference images. ``nodes`` is
    ``{node_id: {label, node_type, verifications}}``. Returns counts."""
    counts: Counter = Counter()
    base = os.path.join(bundle, 'ui', ui)
    refs = [r for r in (refs_fn(team_id, userinterface_name=ui).get('references') or [])
            if r.get('reference_type') == 'reference_image']
    refs_by_name = {r['name']: r for r in refs if r.get('name')}
    files: Dict[str, Optional[str]] = {}

    def ref_file(ref: Mapping[str, Any]) -> Optional[str]:
        name = ref['name']
        if name not in files:
            rel = f'refs/{name}.jpg'
            dest = os.path.join(base, rel)
            if ref.get('r2_path'):
                ok = _download(lambda: cf.download_file(ref['r2_path'], dest), dest)
            else:
                from shared.src.lib.utils.cloudflare_utils import download_reference_image
                from shared.src.lib.utils.reference_utils import reference_storage_key
                ok = _download(lambda: download_reference_image(reference_storage_key(ui, team_id), f'{name}.jpg', dest), dest)
            files[name] = rel if ok else None
            counts['refs_downloaded' if ok else 'refs_missing'] += 1
        return files[name]

    out = []
    for group in groups.to_list():
        members = []
        for m in group['members']:
            checks = []
            for v in nodes.get(m['node_id'], {}).get('verifications') or []:
                entry = check_entry(v, refs_by_name) if isinstance(v, Mapping) else None
                if entry is None:
                    continue
                if entry['command'] in IMAGE_COMMANDS:
                    entry['reference_file'] = ref_file(refs_by_name[entry['reference']]) if entry['reference'] else None
                    counts['image_checks' if entry['reference_file'] else 'image_checks_no_reference'] += 1
                else:
                    counts['text_checks'] += 1
                checks.append(entry)
            seed = None
            key = seeds.get((ui, m['node_id'])) or seeds.get((None, m['node_id']))
            if key:
                rel = f"seed/{m['node_id']}.jpg"
                dest = os.path.join(base, rel)
                if _download(lambda: storage.download_file(key, dest), dest):
                    seed = rel
                    counts['seeds'] += 1
            members.append({**m, 'checks': checks, 'seed': seed})
        out.append({**group, 'members': members})
    _write_json(os.path.join(base, 'groups.json'), out)
    return dict(counts)


def run_export(bundle: str, team_id: str = LAB_TEAM, sets: Sequence[str] = SETS, limit: Optional[int] = None,
               deps: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The whole phase. ``deps`` replaces the DB / storage callables in tests."""
    deps = dict(deps or {})
    scope = load_lib('screen_group_scope')
    if 'refs_fn' not in deps:
        from shared.src.lib.database.verifications_references_db import get_references
        from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils, get_training_storage
        deps.update(refs_fn=get_references, storage=get_training_storage(), cf=get_cloudflare_utils())
    # The 'open' set also holds unlabelled and AI-labelled rows (second-pass candidates).
    sources = ('run', 'human', 'none', 'teacher') if 'open' in sets else ('run', 'human')
    rows = fetch_rows(team_id, deps.get('list_fn'), sources)
    graphs: Dict[str, Any] = {}
    group_of: Dict[str, Any] = {}

    def has_tree(ui: Optional[str]) -> bool:
        if ui and ui not in group_of:
            graph = (deps.get('graph_fn') or scope.load_app_graph)(team_id, ui)
            graphs[ui] = graph
            group_of[ui] = scope.groups_for(team_id, ui, loader=lambda _t, _u: graph) if graph else None
        return bool(ui and group_of.get(ui))

    selected, skipped, taken = select_sets(rows, sets, has_tree, limit)
    os.makedirs(os.path.join(bundle, 'frames'), exist_ok=True)
    seeds = seed_keys(team_id, deps.get('samples_fn'))
    from shared.src.lib.ai import screen_groups as core
    ui_counts: Dict[str, Any] = {}
    for ui in sorted({r['userinterface'] for _s, r in selected}):
        nodes = core.nodes_from_rows(graphs[ui][0])
        ui_counts[ui] = export_ui(team_id, ui, group_of[ui], bundle, seeds, deps['refs_fn'], deps['storage'],
                                  deps['cf'], nodes)
    missing = 0
    with open(os.path.join(bundle, 'rows.jsonl'), 'w', encoding='utf-8') as out:
        for set_name, row in selected:
            dest = os.path.join(bundle, 'frames', f"{row['id']}.jpg")
            if not row.get('object_key') or not _download(lambda: deps['storage'].download_file(row['object_key'], dest), dest):
                missing += 1
                continue
            out.write(json.dumps(row_record(set_name, row), ensure_ascii=False, default=str) + '\n')
    meta = {'team_id': team_id, 'rows_loaded': len(rows), 'selected': dict(taken), 'frame_missing': missing,
            'skipped_no_tree': skipped, 'ui': ui_counts}
    _write_json(os.path.join(bundle, 'export_meta.json'), meta)
    return meta
