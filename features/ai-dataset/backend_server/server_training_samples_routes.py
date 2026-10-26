"""
Training Samples Review Routes (TASK-27 step 4)

Admin-only tooling to human-verify AI training samples and freeze an eval set:
- GET  /server/training-samples/list          filtered, image paths, optional balance
- GET  /server/training-samples/<id>/image    the screenshot of one sample
- POST /server/training-samples/<id>/label    human label, validated per family
- POST /server/training-samples/freeze        set eval_version on the verified eval rows
- GET  /server/training-samples/eval-counts   per family, verified eval rows not yet frozen
- GET  /server/training-samples/offtree-labels suggestions for a screen not in the tree (step 4f)
- GET  /server/training-samples/coverage      canonical-app coverage of the dataset (step 4h)
- GET  /server/training-samples/screen-groups the screen groups of one app (step 4k)

The per-family label schemas (``LABEL_SCHEMAS``) live in ``lib/label_schema.py`` since
step 4i and are re-exported here: the list route hands the page a ``proposed_label``
already in that shape, so the page never maps a model answer itself. The label write is
``lib/label_write.apply_label``, shared with the step 4i teacher importer.

Step 4i (AI triage): the list route's ``triage=needs_human`` is the "Needs you" view,
a human answer marks a triaged row ``resolved``, ``eval-counts`` also returns the
AI-verified (agreed) counts, and ``freeze`` accepts ``eval-vN-ai`` (human + agreed).
"""

import importlib
import logging
import re
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Blueprint, Response, jsonify, request

from backend_server.src.lib.auth_middleware import require_permission, require_user_auth
from backend_server.src.lib.utils.route_handlers import (
    handle_route_exceptions,
    require_team_id_from_args,
    require_team_id_from_body_or_args,
)
from shared.src.lib.ai import training_samples
from shared.src.lib.database import ai_training_samples_db as samples_db
from shared.src.lib.utils import cloudflare_utils

# The feature folder has a hyphen, so its lib is imported by name.
dataset_coverage = importlib.import_module('features.ai-dataset.lib.dataset_coverage')  # step 4h
label_schema = importlib.import_module('features.ai-dataset.lib.label_schema')          # step 4i
label_write = importlib.import_module('features.ai-dataset.lib.label_write')            # step 4i
triage_db = importlib.import_module('features.ai-dataset.lib.triage_db')                # step 4i
comparators = importlib.import_module('features.ai-dataset.lib.comparators')            # step 5
screen_group_scope = importlib.import_module('features.ai-dataset.lib.screen_group_scope')  # step 4k
langfuse_scores = importlib.import_module('features.ai-dataset.lib.langfuse_scores')    # 2026-10-04

server_training_samples_bp = Blueprint('server_training_samples', __name__,
                                       url_prefix='/server/training-samples')

logger = logging.getLogger(__name__)

FREEZE_MIN_ROWS = 200          # TASK-27 §8: an eval family needs 200+ human-verified rows
LIST_MAX_LIMIT = 200
BALANCE_POOL = 1000            # rows fetched before a balanced round-robin
BALANCE_KEYS = ('device_model',)
# Step 4f: starter suggestions for a screen-id frame showing a screen not in the tree.
OFFTREE_STARTER_LABELS = ('popup', 'error / no signal', 'loading / black', 'dialog', 'tip')
# eval-vN (human only) or eval-vN-ai (step 4i: human + AI-agreed, a pilot).
_VERSION_RE = re.compile(r'^eval-v[0-9]+(-ai)?$')
AI_VERSION_SUFFIX = '-ai'
AI_FREEZE_MIN_ROWS = 50        # step 4i: default minimum of an eval-vN-ai pilot freeze
TRIAGE_FILTERS = ('needs_human',)

# Label shapes and their checks live in lib/label_schema.py (step 4i: shared with the
# teacher importer); re-exported here, the names the route and its tests use.
LABEL_SCHEMAS = label_schema.LABEL_SCHEMAS
AV_FAULT_TYPES = label_schema.AV_FAULT_TYPES
NO_BANNER = label_schema.NO_BANNER
validate_label = label_schema.validate_label
normalize_label = label_schema.normalize_label
label_from_model_answer = label_schema.label_from_model_answer
_text = label_schema._text


def proposed_label(row: Dict[str, Any]) -> Any:
    """What ``y`` writes: the row's own ground truth if any, else the mapped model answer."""
    return _proposal(row)[0]


def guess_source(row: Dict[str, Any]) -> Optional[str]:
    """Where ``proposed_label`` came from: the row's label source ('run', 'human',
    'teacher'), 'model' for a mapped model answer, or None when there is no guess."""
    return _proposal(row)[1]


def _proposal(row: Dict[str, Any]):
    if row.get('ground_truth') is not None:
        source = row.get('label_source')
        return row['ground_truth'], (source if source in ('run', 'human', 'teacher') else None)
    label = label_from_model_answer(row.get('family'), row.get('model_answer'))
    return label, ('model' if label is not None else None)


# ---- list helpers -------------------------------------------------------------------

def round_robin(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    """Interleave rows across ``key`` values, keeping each value's own order."""
    buckets: 'OrderedDict[Any, List[Dict[str, Any]]]' = OrderedDict()
    for row in rows:
        buckets.setdefault(row.get(key), []).append(row)
    out: List[Dict[str, Any]] = []
    queues = [list(b) for b in buckets.values()]
    while queues:
        for q in queues:
            out.append(q.pop(0))
        queues = [q for q in queues if q]
    return out


def _attach_image_paths(rows: List[Dict[str, Any]]) -> None:
    """Give every row the app route that serves its screenshot.

    The screenshot is not fetched from the training bucket by the browser: the
    public host in front of that bucket only answers the allow-listed egress
    IPs, so every ``<img>`` got a 403 HTML page (BUG-0775). The server reads
    the object over the LAN and serves it (``GET .../<id>/image``).
    """
    for row in rows:
        row['image_path'] = (
            f"/server/training-samples/{row['id']}/image" if row.get('object_key') else None
        )


def _attach_conflict_partners(team_id: str, rows: List[Dict[str, Any]]) -> None:
    """Step 4d: give each ``label_conflict`` row ``conflict_partner`` = ``{id, ground_truth}``
    of one near-identical row with a different label (None when none is found any more).

    ``screen-id`` / ``focus`` look across the whole ``(family, device_model)``, the other
    families within the row's own dedup group, the same scopes the flag was set with.
    Step 4j: a ``focus`` row or a low-information hash never has a partner (None)."""
    cache: Dict[Any, List[Any]] = {}
    for row in rows:
        row['conflict_partner'] = None
        truth = row.get('ground_truth')
        if not row.get('label_conflict') or truth is None or not row.get('dhash'):
            continue
        family, model = row.get('family'), row.get('device_model')
        if family in training_samples.CROSS_NODE_FAMILIES:
            key = (family, model)
            if key not in cache:
                cache[key] = samples_db.get_labelled_hashes(team_id, family, model,
                                                            training_samples.CROSS_NODE_LIMIT)
            candidates = cache[key]
        else:
            candidates = [(i, h, t) for i, h, t, _f in
                          samples_db.get_group(team_id, family, model, row.get('node_id'),
                                               row.get('focus_label'))]
        ids = training_samples._cross_node_conflicts(candidates, row['id'], row['dhash'], truth, family)
        if ids:
            partner_truth = next((t for i, _h, t in candidates if i == ids[0]), None)
            row['conflict_partner'] = {'id': ids[0], 'ground_truth': partner_truth}


def _bool_arg(name: str) -> Optional[bool]:
    raw = (request.args.get(name) or '').strip().lower()
    if raw in ('1', 'true', 'yes'):
        return True
    if raw in ('0', 'false', 'no'):
        return False
    return None


def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(request.args.get(name, default))))
    except (TypeError, ValueError):
        return default


# ---- routes -------------------------------------------------------------------------

@server_training_samples_bp.route('/list', methods=['GET'])
@require_user_auth
@require_permission('ai.training:view')
@handle_route_exceptions('server_training_samples:list')
def list_training_samples():
    """Samples for review, hardest first, each with ``image_path`` and ``proposed_label``.

    Query: team_id (required), family, split, label_source (comma list), is_failure,
    label_conflict (the "Confusable pairs" view), device_model, limit, offset,
    balance=device_model. Conflict rows also carry ``conflict_partner``.
    """
    team_id, err = require_team_id_from_args()
    if err:
        return err
    family = request.args.get('family') or None
    if family and family not in LABEL_SCHEMAS:
        return jsonify({'success': False, 'error': f"unknown family '{family}'"}), 400
    split = request.args.get('split') or None
    if split and split not in ('train', 'eval', 'holdout'):
        return jsonify({'success': False, 'error': f"unknown split '{split}'"}), 400
    label_sources = [s.strip() for s in (request.args.get('label_source') or '').split(',') if s.strip()]
    bad = [s for s in label_sources if s not in training_samples.LABEL_SOURCES]
    if bad:
        return jsonify({'success': False, 'error': f"unknown label_source {bad}"}), 400
    balance = request.args.get('balance') or None
    if balance and balance not in BALANCE_KEYS:
        return jsonify({'success': False, 'error': f"balance must be one of {list(BALANCE_KEYS)}"}), 400
    triage = request.args.get('triage') or None
    if triage and triage not in TRIAGE_FILTERS:
        return jsonify({'success': False, 'error': f"triage must be one of {list(TRIAGE_FILTERS)}"}), 400

    limit = _int_arg('limit', 50, 1, LIST_MAX_LIMIT)
    offset = _int_arg('offset', 0, 0, 10_000_000)
    filters = dict(family=family, split=split, label_sources=label_sources or None,
                   is_failure=_bool_arg('is_failure'),
                   device_model=request.args.get('device_model') or None,
                   label_conflict=_bool_arg('label_conflict'))

    if triage == 'needs_human':
        # Step 4i "Needs you": the AI teacher's disagreements, conflicts, low-confidence
        # answers and spot-checks, spot-checks last. Its own order, so no balance.
        rows, total = triage_db.list_needs_human(team_id, family=family, split=split,
                                                 device_model=filters['device_model'],
                                                 limit=limit, offset=offset)
    elif balance:
        pool, total = samples_db.list_samples(team_id, limit=BALANCE_POOL, offset=0, **filters)
        rows = round_robin(pool, balance)[offset:offset + limit]
    else:
        rows, total = samples_db.list_samples(team_id, limit=limit, offset=offset, **filters)

    _attach_image_paths(rows)
    _attach_conflict_partners(team_id, rows)
    for row in rows:
        row['proposed_label'], row['guess_source'] = _proposal(row)
        row['triage'] = triage_db.triage_of(row)
    return jsonify({'success': True, 'samples': rows, 'total': total,
                    'limit': limit, 'offset': offset, 'schemas': LABEL_SCHEMAS})


# A review screenshot is a few hundred KB; anything near this is not one.
IMAGE_MAX_BYTES = 20 * 1024 * 1024


@server_training_samples_bp.route('/<sample_id>/image', methods=['GET'])
@require_user_auth
@require_permission('ai.training:view')
@handle_route_exceptions('server_training_samples:image')
def get_training_sample_image(sample_id):
    """The screenshot of one sample, served by the server.

    The images live in the training bucket. The browser cannot fetch them by
    itself: the public host in front of that bucket answers only the
    allow-listed egress IPs, so every ``<img>`` got a 403 HTML page, which
    Chromium then blocked as an opaque response (BUG-0775). The server reads
    the object over the LAN and serves it, so the review page works for every
    user of the app.

    The object key is read from the database, never taken from the request, so
    a caller cannot ask for another team's image.
    """
    team_id, err = require_team_id_from_args()
    if err:
        return err
    row = samples_db.get_sample(sample_id, team_id)
    if not row:
        return jsonify({'success': False, 'error': 'Sample not found'}), 404
    object_key = row.get('object_key')
    if not object_key:
        return jsonify({'success': False, 'error': 'This sample has no screenshot'}), 404
    try:
        storage = cloudflare_utils.get_training_storage()
    except Exception as e:
        logger.warning(f"[training_review] training storage unavailable: {e}")
        return jsonify({'success': False, 'error': 'Training storage is not configured on this server'}), 503
    try:
        obj = storage.s3_client.get_object(Bucket=storage.bucket_name, Key=object_key)
        content_type = str(obj.get('ContentType') or 'image/jpeg')
        if not content_type.lower().startswith('image/'):
            # Never serve stored HTML or script as a same-origin document.
            return jsonify({'success': False, 'error': 'The stored object is not an image'}), 415
        # Bounded read: one more byte than the cap tells us the object is too large.
        body = obj['Body'].read(IMAGE_MAX_BYTES + 1)
        if len(body) > IMAGE_MAX_BYTES:
            return jsonify({'success': False, 'error': 'The screenshot is too large to serve'}), 413
    except Exception as e:
        logger.warning(f"[training_review] could not read {object_key}: {e}")
        return jsonify({'success': False, 'error': 'The screenshot could not be read from the training storage'}), 502
    return Response(body, mimetype=content_type, headers={
        'Cache-Control': 'private, max-age=300',
        'X-Content-Type-Options': 'nosniff',
    })


def resolved_triage(old: Dict[str, Any], family: str, ground_truth: Any, now: str) -> Dict[str, Any]:
    """Step 4i: the triage record after a human answered a triaged row. Keeps the teacher
    answer and records whether the human agreed with it (the per-batch error rate of
    TASK-27 section 7). Pure."""
    record = dict(old)
    teacher = old.get('teacher_label')
    agreed = None
    if isinstance(teacher, dict) and isinstance(ground_truth, dict) and family in comparators.COMPARATORS:
        agreed = comparators.compare(family, ground_truth, teacher)[0]
    if old.get('status') != 'resolved':
        record.update(prior_status=old.get('status'), prior_reason=old.get('reason'))
    record.update(status='resolved', resolved_at=now, human_agreed_with_teacher=agreed)
    return record


@server_training_samples_bp.route('/<sample_id>/label', methods=['POST'])
@require_user_auth
@require_permission('ai.training:review')
@handle_route_exceptions('server_training_samples:label')
def label_training_sample(sample_id):
    """Write a human label. Body: {team_id, ground_truth, label_source: 'human'}.

    Works whether or not capture (TRAINING_DATA_ENABLED) is on: review of rows
    already stored must not depend on the capture switch. The write is
    ``lib/label_write.apply_label`` (what ``training_samples.attach_ground_truth`` does
    minus its ``enabled()`` gate), the same path the step 4i teacher importer uses.

    A failed-verification ``screen-id`` sample (step 4d) has no ``node_id`` in its
    model answer, so any screen written here makes it ``is_failure=true``: the
    verifier failed on that frame.

    Step 4i: a row the AI teacher triaged (any ``triage`` record) becomes
    ``triage.status='resolved'``; the human label replaces a teacher one.

    2026-10-04: when the row has ``source_ref.trace_id`` (a real AI call), a
    ``verdict_human`` score (the model answer matches this label) goes on that Langfuse
    trace, off the request path (``lib/langfuse_scores``).
    """
    team_id, err = require_team_id_from_body_or_args()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if data.get('label_source', 'human') != 'human':
        return jsonify({'success': False, 'error': "label_source must be 'human'"}), 400
    if 'ground_truth' not in data:
        return jsonify({'success': False, 'error': 'ground_truth is required'}), 400
    ground_truth = data['ground_truth']

    row = samples_db.get_sample(sample_id, team_id)
    if not row:
        return jsonify({'success': False, 'error': 'sample not found'}), 404
    if row.get('eval_version'):
        return jsonify({'success': False, 'error': f"sample is frozen in {row['eval_version']}; "
                                                   f"its label cannot change"}), 409
    problem = validate_label(row['family'], ground_truth)
    if problem:
        return jsonify({'success': False, 'error': problem}), 400
    ground_truth = normalize_label(row['family'], ground_truth)

    result = label_write.apply_label(team_id, row, ground_truth, 'human')
    if not result['ok']:
        # The freeze trigger raises inside update_label: re-read to tell a freeze that
        # landed after our check from any other failure.
        again = samples_db.get_sample(sample_id, team_id)
        if again and again.get('eval_version'):
            return jsonify({'success': False, 'error': f"sample is frozen in {again['eval_version']}; "
                                                       f"its label cannot change"}), 409
        return jsonify({'success': False, 'error': 'label update failed'}), 500

    triage = None
    old_triage = triage_db.triage_of(row)
    if old_triage:
        triage = resolved_triage(old_triage, row['family'], ground_truth,
                                 datetime.now(timezone.utc).isoformat(timespec='seconds'))
        if not triage_db.resolve_triage(team_id, str(sample_id), triage):
            logger.warning(f"[training_review] {sample_id}: label saved, triage not marked resolved")
    # 2026-10-04: a sample from a real AI call (source_ref.trace_id) gets a verdict_human
    # score on its Langfuse trace, in a daemon thread; skipped without a trace or tracing.
    langfuse_scores.score_verdict_async(row, ground_truth, langfuse_scores.SCORE_HUMAN,
                                        langfuse_scores.human_comment(ground_truth))
    return jsonify({'success': True, 'id': str(sample_id), 'ground_truth': ground_truth,
                    'label_source': 'human', 'is_failure': result['is_failure'],
                    'label_conflict': result['label_conflict'], 'triage': triage})


def _min_rows_arg(value: Any) -> Optional[int]:
    if value is None or value == '':
        return AI_FREEZE_MIN_ROWS
    if isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


@server_training_samples_bp.route('/freeze', methods=['POST'])
@require_user_auth
@require_permission('ai.training:review')
@handle_route_exceptions('server_training_samples:freeze')
def freeze_training_eval():
    """Freeze an eval version. Body: {team_id, family, version[, min_rows]}.

    ``eval-vN`` (e.g. ``eval-v1``): human-verified rows only (split='eval',
    label_source='human', not frozen), refused below FREEZE_MIN_ROWS.
    ``eval-vN-ai`` (step 4i, e.g. ``eval-v0-ai``): a pilot of human-verified **plus**
    AI-verified rows (the AI teacher agreed with the run label, ``triage.status='agreed'``),
    refused below ``min_rows`` (default AI_FREEZE_MIN_ROWS). Its rows are frozen like any
    other: a human row frozen in ``eval-v0-ai`` can no longer enter ``eval-v1``.
    409 when the version already exists for that family.
    """
    team_id, err = require_team_id_from_body_or_args()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    family = data.get('family')
    version = (data.get('version') or '').strip()
    if family not in LABEL_SCHEMAS:
        return jsonify({'success': False, 'error': f"unknown family '{family}'"}), 400
    if not _VERSION_RE.match(version):
        return jsonify({'success': False, 'error': "version must look like 'eval-v1' or 'eval-v0-ai'"}), 400
    with_ai = version.endswith(AI_VERSION_SUFFIX)
    minimum = _min_rows_arg(data.get('min_rows')) if with_ai else FREEZE_MIN_ROWS
    if minimum is None:
        return jsonify({'success': False, 'error': 'min_rows must be a whole number >= 1'}), 400
    if samples_db.eval_version_exists(team_id, family, version):
        return jsonify({'success': False, 'error': f"{version} already exists for {family}"}), 409
    if with_ai:
        candidates = triage_db.count_ai_freeze_candidates(team_id, family)
        what = 'human- or AI-verified'
    else:
        candidates = samples_db.count_freeze_candidates(team_id, family)
        what = 'human-verified'
    if candidates < minimum:
        return jsonify({'success': False, 'candidates': candidates,
                        'error': f"{family} has {candidates} {what} eval rows; {minimum} needed"}), 400
    frozen = (triage_db.freeze_ai_eval(team_id, family, version) if with_ai
              else samples_db.freeze_eval(team_id, family, version))
    if not frozen:
        return jsonify({'success': False, 'error': 'freeze failed'}), 500
    return jsonify({'success': True, 'family': family, 'version': version, 'frozen': frozen,
                    'labels': 'human+ai' if with_ai else 'human'})


@server_training_samples_bp.route('/eval-counts', methods=['GET'])
@require_user_auth
@require_permission('ai.training:view')
@handle_route_exceptions('server_training_samples:eval_counts')
def training_eval_counts():
    """Per family, eval rows not frozen: ``counts`` = human-verified (what an ``eval-vN``
    freeze takes), ``agreed_counts`` = AI-verified (step 4i: the teacher agreed with the
    run label; an ``eval-vN-ai`` freeze takes both), and the two thresholds."""
    team_id, err = require_team_id_from_args()
    if err:
        return err
    counts = {family: samples_db.count_freeze_candidates(team_id, family) for family in LABEL_SCHEMAS}
    agreed = {family: triage_db.count_agreed_eval(team_id, family) for family in LABEL_SCHEMAS}
    return jsonify({'success': True, 'counts': counts, 'agreed_counts': agreed,
                    'threshold': FREEZE_MIN_ROWS, 'ai_threshold': AI_FREEZE_MIN_ROWS})


@server_training_samples_bp.route('/offtree-labels', methods=['GET'])
@require_user_auth
@require_permission('ai.training:view')
@handle_route_exceptions('server_training_samples:offtree_labels')
def training_offtree_labels():
    """Step 4f: suggestions for the "Screen not in the tree" field of a ``screen-id``
    sample: the starter list, then the distinct labels this team already saved.
    Query: team_id (required), family (default 'screen-id')."""
    team_id, err = require_team_id_from_args()
    if err:
        return err
    family = request.args.get('family') or 'screen-id'
    if family != 'screen-id':
        return jsonify({'success': False, 'error': 'only screen-id has off-tree labels'}), 400
    saved = samples_db.get_offtree_labels(team_id, family)
    labels = list(OFFTREE_STARTER_LABELS) + [x for x in saved if x not in OFFTREE_STARTER_LABELS]
    return jsonify({'success': True, 'labels': labels})


@server_training_samples_bp.route('/coverage', methods=['GET'])
@require_user_auth
@require_permission('ai.training:view')
@handle_route_exceptions('server_training_samples:coverage')
def training_coverage():
    """Step 4h: how much of the canonical apps the dataset covers (definitions in
    ``features/ai-dataset/lib/dataset_coverage.py``). Query: team_id (required), k (default 3,
    1..50). Global exhaustiveness, per platform, per app with its missing screens, and the
    team's other userinterfaces as "not in scope". Read-only."""
    team_id, err = require_team_id_from_args()
    if err:
        return err
    k = dataset_coverage.clamp_k(request.args.get('k'), dataset_coverage.DEFAULT_K)
    report = dataset_coverage.build_coverage(team_id, k)
    return jsonify({'success': True, **report})


@server_training_samples_bp.route('/screen-groups', methods=['GET'])
@require_user_auth
@require_permission('ai.training:view')
@handle_route_exceptions('server_training_samples:screen_groups')
def training_screen_groups():
    """Step 4k: the screen groups of one app, derived from its tree (core ``screen_groups``,
    the feature's ``SCREEN_GROUP_OVERRIDES`` applied). Query: team_id, userinterface (both
    required). ``groups``: ``[{node_id, label, members: [{node_id, label, focus}]}]`` sorted
    by label, the group node first in its members; empty with ``found: false`` when the app
    has no tree. The review page lists these names as the screen answers. Read-only."""
    team_id, err = require_team_id_from_args()
    if err:
        return err
    userinterface = (request.args.get('userinterface') or '').strip()
    if not userinterface:
        return jsonify({'success': False, 'error': 'userinterface is required'}), 400
    groups = screen_group_scope.groups_for(team_id, userinterface)
    return jsonify({'success': True, 'userinterface': userinterface, 'found': groups is not None,
                    'groups': groups.to_list() if groups is not None else [],
                    'warnings': list(groups.warnings) if groups is not None else []})
