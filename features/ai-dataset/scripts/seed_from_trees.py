#!/usr/bin/env python3
"""seed_from_trees.py — TASK-27 step 4h: seed ``screen-id`` samples from the node screenshots.

Every visible screen node of a canonical app's navigation trees (root tree plus nested
subtrees; ``screen``/``menu`` only, no ``entry``/``action``, no ``hidden_in_base`` row) that
has a screenshot becomes one ``screen-id`` sample labelled with that node::

    record_sample(image, family='screen-id', team_id, device_model=<the app's first model>,
                  userinterface=<app>, node_id=<node_id>,
                  ground_truth=<the node's screen-group label>, label_source='run',
                  source_ref={'reference': 'navigation', 'tree_id', 'node_id', 'userinterface',
                              'screenshot': <object key>},
                  split=<--split, default train>, force=False)

* **Screen groups (step 4k).** Every node frame is still seeded (the stable key
  ``node_id`` is the node), but the label is the node's **screen group**
  (``lib/screen_group_scope``, overrides applied): ``{node_id: <group node id>, label:
  <group>, node: <node_id>, node_label: <label>, focus: <focused item or null>}``. An app
  whose groups cannot be derived keeps the per-node label ``{node_id, label}``, which
  ``regroup_screen_labels.py`` converts later.
* **Scope.** Only names in ``CANONICAL_USERINTERFACES`` (``lib/dataset_scope.py``); a name that
  is not there, or matches an exclusion pattern (``*_autobuild*``, ``*_copy``, ``__smoke*`` ...),
  refuses the whole run. A phone/tablet app is refused too (core drops those frames, §9).
* **Read-only on the source.** The screenshot is read from the default bucket (the object in
  ``data.screenshot``, else ``navigation/<ui>/<label>.jpg``). Trees, nodes and screenshots are
  never written.
* **Dedup.** Pass-1 dedup applies (``force=False``): a node frame within 8 bits of a sample
  already in that node's group is ``skipped-duplicate``; a group already holding 20 regular
  samples is ``skipped-cap``. The script classifies before calling ``record_sample`` so the
  report can tell them apart; ``record_sample`` checks again.
* **Idempotent.** A node row that already has a seeded sample (``source_ref.reference =
  'navigation'`` with the same userinterface and ``tree_id`` + ``node_id``, or the same
  userinterface, ``node_id`` and screenshot object) is ``skipped-exists``. ``node_id`` alone is
  not unique across apps (``home-node`` is in several), so the app is part of the key.
* **Split.** ``--split train`` (default) goes through the ``record_sample(split=)`` core hook;
  seeded frames are train-only until a human decides otherwise.

``--dry-run`` reads the tree, checks and downloads the screenshots and classifies them; it
writes nothing. A real run needs ``TRAINING_DATA_ENABLED``, a training bucket and the team's
``training_data_opt_in``, and stops before touching anything if one is missing.

Environment: the DB (``SUPABASE_*``), the default bucket (``MINIO_*`` / ``CLOUDFLARE_R2_*``) and,
for a real run, the training bucket must be in the environment; nothing loads a ``.env``.

Usage
-----
    python3 features/ai-dataset/scripts/seed_from_trees.py --team <uuid> \\
        --userinterfaces stb_tv,iad_gui,youtube-web,web_tv --dry-run
    python3 features/ai-dataset/scripts/seed_from_trees.py --team <uuid> \\
        --userinterfaces stb_tv,iad_gui,youtube-web,web_tv [--split train] [--limit N]
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
if os.path.isdir(os.path.join(_REPO_ROOT, "shared")) and _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

scope = importlib.import_module('features.ai-dataset.lib.dataset_scope')

FAMILY = 'screen-id'
REFERENCE = 'navigation'
SPLITS = ('train', 'eval', 'holdout')
OUTCOMES = ('seeded', 'would-seed', 'skipped-duplicate', 'skipped-cap', 'skipped-exists',
            'no-screenshot', 'image-missing', 'skipped-limit', 'failed')


class SeedError(Exception):
    """The run is refused as a whole."""


def parse_list(value: Optional[str]) -> List[str]:
    return [v.strip() for v in (value or '').split(',') if v.strip()]


def check_scope(names: Sequence[str]) -> None:
    if not names:
        raise SeedError('--userinterfaces needs at least one name')
    problems = [p for p in (scope.scope_refusal(n) for n in names) if p]
    if problems:
        raise SeedError('refused: ' + '; '.join(problems))


# ---- dependencies (real ones; tests pass fakes) ------------------------------------------------

class Deps:
    """Everything the seed touches. Only ``record`` writes (through core ``record_sample``)."""

    def __init__(self):
        from shared.src.lib.ai import training_samples
        from shared.src.lib.database import ai_training_samples_db as samples_db
        from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils

        self.ts = training_samples
        self.db = samples_db
        self._default = get_cloudflare_utils()   # default bucket: read only

    # source (read-only)
    def load_userinterfaces(self, team_id):
        return scope.load_userinterfaces(team_id)

    def load_trees(self, team_id, ui_ids):
        return scope.load_trees(team_id, ui_ids)

    def load_nodes(self, team_id, tree_ids):
        return scope.load_screen_nodes(team_id, tree_ids)

    def resolve(self, url):
        return self._default.resolve_remote_path(url)

    def exists(self, key):
        return bool(self._default.head_file(key).get('success'))

    def fetch(self, key) -> Optional[bytes]:
        try:
            obj = self._default.s3_client.get_object(Bucket=self._default.bucket_name, Key=key)
            return obj['Body'].read()
        except Exception as e:
            print(f'[seed] could not read {key}: {e}', file=sys.stderr)
            return None

    # dataset
    def seeded_refs(self, team_id):
        return [r.get('source_ref') or {} for r in
                self.db.get_samples_by_source_ref(team_id, 'reference', REFERENCE)]

    def enabled(self):
        return self.ts.enabled()

    def opted_in(self, team_id):
        return self.db.team_opted_in(team_id)

    def excluded_models(self):
        return self.ts.EXCLUDED_DEVICE_MODELS

    def dhash(self, image: bytes) -> Optional[str]:
        return self.ts._prepare_image(image)[1]

    def group(self, team_id, device_model, node_id):
        return self.db.get_group(team_id, FAMILY, device_model, node_id, None)

    def near_dup_bits(self):
        return self.ts.NEAR_DUP_BITS

    def group_cap(self):
        return self.ts.GROUP_CAP

    def hamming(self, a, b):
        from shared.src.lib.utils.image_hash import dhash_hamming
        return dhash_hamming(a, b)

    def informative(self, dhash):
        return self.ts.is_informative(dhash)

    def record(self, **kw):
        return self.ts.record_sample(**kw)

    def groups(self, team_id, userinterface):
        """Step 4k: the app's screen groups, or None."""
        scope_mod = importlib.import_module('features.ai-dataset.lib.screen_group_scope')
        return scope_mod.groups_for(team_id, userinterface)


# ---- pure helpers -------------------------------------------------------------------------------

def existing_keys(refs: Sequence[Dict[str, Any]]):
    """Idempotency keys of the samples already seeded."""
    by_tree, by_image = set(), set()
    for ref in refs:
        if not isinstance(ref, dict) or ref.get('reference') != REFERENCE:
            continue
        ui, node = ref.get('userinterface'), ref.get('node_id')
        by_tree.add((ui, ref.get('tree_id'), node))
        if ref.get('screenshot'):
            by_image.add((ui, node, ref['screenshot']))
    return by_tree, by_image


def classify(dhash: str, group: Sequence[Any], pending: Sequence[str], near_bits: int, cap: int,
             hamming, informative) -> Optional[str]:
    """Pass 1 of §6 as ``should_keep`` applies it: 'skipped-duplicate', 'skipped-cap' or None.
    ``pending`` holds the hashes this run already seeded (or, dry run, would seed) for the group.
    Step 4j: a low-information hash (``informative`` false, e.g. a black poweroff screen) is
    never a near-duplicate, on either side; the cap still applies to it."""
    hashes = [h for _i, h, _t, _f in group if h] + list(pending)
    if informative(dhash) and any(informative(h) and hamming(dhash, h) <= near_bits for h in hashes):
        return 'skipped-duplicate'
    regular = sum(1 for _i, _h, _t, failure in group if not failure) + len(pending)
    return 'skipped-cap' if regular >= cap else None


# ---- run ----------------------------------------------------------------------------------------

def seed_app(team_id: str, ui: Dict[str, Any], trees, nodes, deps, split: str, dry_run: bool,
             done_tree: set, done_image: set, budget: List[Optional[int]]) -> Dict[str, Any]:
    name = ui['name']
    models = list(ui.get('models') or [])
    device_model = scope.device_model_for(models)
    report: Dict[str, Any] = {'userinterface': name, 'device_model': device_model, 'models': models,
                              'counts': Counter(), 'notes': [], 'items': []}
    if len(models) > 1:
        report['notes'].append(f"{len(models)} device models {models}: samples use the first, '{device_model}'")
    if not device_model:
        raise SeedError(f"'{name}' has no device model")
    if device_model in deps.excluded_models():
        raise SeedError(f"'{name}' is a {device_model} app: phone/tablet frames are not collected (§9)")

    rows = scope.app_screen_nodes(ui, trees, nodes)
    groups_fn = getattr(deps, 'groups', None)
    groups = groups_fn(team_id, name) if groups_fn else None
    report['groups'] = len(groups.groups) if groups is not None else None
    report['node_rows'] = len(rows)
    report['screens'] = len({r['node_id'] for r in rows})
    pending: Dict[str, List[str]] = {}
    for node in rows:
        node_id, label, tree_id = str(node['node_id']), str(node.get('label') or node['node_id']), node['tree_id']
        item = {'node_id': node_id, 'label': label, 'tree_id': tree_id}
        report['items'].append(item)

        def done(outcome, **extra):
            item.update(outcome=outcome, **extra)
            report['counts'][outcome] += 1

        keys = scope.screenshot_keys(node, name, deps.resolve)
        if not keys:
            done('no-screenshot')
            continue
        if (name, tree_id, node_id) in done_tree:
            done('skipped-exists')
            continue
        key = next((k for k in keys if deps.exists(k)), None)
        if key is None:
            done('image-missing', tried=keys)
            continue
        if (name, node_id, key) in done_image:
            done('skipped-exists', key=key)
            continue
        if budget[0] is not None and budget[0] <= 0:
            done('skipped-limit', key=key)
            continue
        if budget[0] is not None:
            budget[0] -= 1

        image = deps.fetch(key)
        dhash = deps.dhash(image) if image else None
        if not dhash:
            done('image-missing', tried=[key])
            continue
        skip = classify(dhash, deps.group(team_id, device_model, node_id), pending.get(node_id, []),
                        deps.near_dup_bits(), deps.group_cap(), deps.hamming, deps.informative)
        if skip:
            done(skip, key=key)
            continue
        if dry_run:
            pending.setdefault(node_id, []).append(dhash)
            done('would-seed', key=key)
            continue
        sample_id = deps.record(
            image=image, family=FAMILY, team_id=team_id, device_model=device_model,
            userinterface=name, node_id=node_id,
            ground_truth=(groups.label_for(node_id, label) if groups is not None else None)
            or {'node_id': node_id, 'label': label}, label_source='run',
            source_ref={'reference': REFERENCE, 'tree_id': tree_id, 'node_id': node_id,
                        'userinterface': name, 'screenshot': key},
            split=split, force=False)
        if sample_id:
            pending.setdefault(node_id, []).append(dhash)
            done_tree.add((name, tree_id, node_id))
            done_image.add((name, node_id, key))
            done('seeded', key=key, sample_id=sample_id)
        else:
            done('failed', key=key)
    report['counts'] = dict(report['counts'])
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='TASK-27 step 4h: seed screen-id samples from the '
                                            'navigation node screenshots of the canonical apps.')
    p.add_argument('--team', required=True, help='team id')
    p.add_argument('--userinterfaces', required=True,
                   help=f"comma-separated canonical apps ({', '.join(scope.CANONICAL_USERINTERFACES)})")
    p.add_argument('--split', default='train', choices=SPLITS,
                   help='split of every seeded sample (default train)')
    p.add_argument('--dry-run', action='store_true', help='read and classify only, write nothing')
    p.add_argument('--limit', type=int, default=None,
                   help='attempt at most N node screenshots in total (after the skipped-exists filter)')
    p.add_argument('--json', action='store_true', help='also print the full report as JSON')
    return p


def run(argv: Optional[List[str]] = None, deps=None) -> Dict[str, Any]:
    args = build_arg_parser().parse_args(argv)
    names = parse_list(args.userinterfaces)
    check_scope(names)
    if args.limit is not None and args.limit < 1:
        raise SeedError('--limit must be >= 1')
    deps = deps or Deps()
    if not args.dry_run:
        if not deps.enabled():
            raise SeedError('capture is off here (TRAINING_DATA_ENABLED unset or no training bucket): '
                            'nothing would be stored')
        if not deps.opted_in(args.team):
            raise SeedError(f'team {args.team} has not opted in (teams.training_data_opt_in)')

    uis = {u['name']: u for u in deps.load_userinterfaces(args.team)}
    missing = [n for n in names if n not in uis]
    if missing:
        raise SeedError(f'no userinterface named {missing} in team {args.team}')
    selected = [uis[n] for n in names]
    trees = deps.load_trees(args.team, [u['id'] for u in selected])
    nodes = deps.load_nodes(args.team, [t['id'] for t in trees])
    done_tree, done_image = existing_keys(deps.seeded_refs(args.team))

    budget = [args.limit]
    apps = [seed_app(args.team, ui, trees, nodes, deps, args.split, args.dry_run, done_tree,
                     done_image, budget) for ui in selected]
    totals: Counter = Counter()
    for a in apps:
        totals.update(a['counts'])
    return {'team_id': args.team, 'split': args.split, 'dry_run': args.dry_run, 'limit': args.limit,
            'apps': apps, 'totals': dict(totals), '_json': args.json}


def print_report(result: Dict[str, Any], out=sys.stdout) -> None:
    mode = 'DRY RUN, nothing written' if result['dry_run'] else 'written'
    print(f"seed_from_trees team={result['team_id']} split={result['split']} ({mode})", file=out)
    cols = ['seeded' if not result['dry_run'] else 'would-seed', 'skipped-duplicate', 'skipped-cap',
            'skipped-exists', 'no-screenshot', 'image-missing', 'failed']
    if result.get('limit'):
        cols.append('skipped-limit')
    print(f"{'userinterface':14s} {'model':6s} {'rows':>4s} {'scr':>4s} " +
          ' '.join(f'{c:>17s}' for c in cols), file=out)
    for a in result['apps']:
        print(f"{a['userinterface']:14s} {str(a['device_model']):6s} {a['node_rows']:4d} {a['screens']:4d} " +
              ' '.join(f"{a['counts'].get(c, 0):17d}" for c in cols), file=out)
        for note in a['notes']:
            print(f'  note: {note}', file=out)
        for it in a['items']:
            if it.get('outcome') in ('image-missing', 'failed'):
                print(f"  {it['outcome']}: {it['label']} ({it['node_id']}) tried {it.get('tried') or it.get('key')}",
                      file=out)
    print('totals: ' + ', '.join(f'{k}={v}' for k, v in sorted(result['totals'].items())), file=out)


def main() -> None:
    try:
        result = run()
    except SeedError as e:
        print(f'[seed_from_trees] REFUSED: {e}', file=sys.stderr)
        sys.exit(2)
    print_report(result)
    if result.pop('_json'):
        print(json.dumps(result, indent=2, default=str))
    sys.exit(1 if result['totals'].get('failed') else 0)


if __name__ == '__main__':
    main()
