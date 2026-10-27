"""
AI training-sample capture (TASK-27).

Hooks call ``record_sample(...)`` when they have a frame worth keeping and
``attach_ground_truth(...)`` when the correct answer becomes known. Both are
no-ops unless ``TRAINING_DATA_ENABLED`` is set, a training bucket is configured,
and the team has ``teams.training_data_opt_in``. Neither ever raises.

Dedup runs in two passes (TASK-27 §6):
  pass 1 ``should_keep`` — before upload, stable keys only: near-duplicate hash
         within ``NEAR_DUP_BITS`` in the group is skipped, and a group holds at
         most ``GROUP_CAP`` regular samples. ``force=True`` (failure hooks) skips both;
         ``skip_cap=True`` (alert frames, step 4d) keeps the near-duplicate check and
         skips only the cap. Step 4j: a low-information hash (``is_informative``
         false: black, no-signal colour bars, flat loading screens) is never a
         near-duplicate of anything, and nothing is a near-duplicate of it; such a
         frame always goes through a cap, even with ``skip_cap=True``.
  pass 2 ``attach_ground_truth`` — when the label arrives: recompute
         ``is_failure`` and flag ``label_conflict``.

Conflicts (§6 rule 6): a near-identical frame with a different label in the same
group. For ``screen-id`` (step 4d) the check also spans the whole
``(team_id, family, device_model)``, so look-alike screens stored under different
nodes (Home vs TV Guide) are caught, and **both** rows are flagged. Step 4j: a
low-information hash is never compared (never flagged, never a partner), and
``focus`` has no conflicts at all (two frames of one menu that differ only by the
highlight are exactly what that family labels).

The split (§8) is decided once at insert from the stable keys plus the first 16
bits of the dHash, never from the label. ``av-fault`` rows that carry an
``alert_id`` hash the alert instead (step 4d), so one alert's frames share a split.
"""

import hashlib
import fnmatch
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import cv2
import numpy as np

from shared.src.lib.database import ai_training_samples_db as samples_db
from shared.src.lib.utils import cloudflare_utils
from shared.src.lib.utils.image_hash import dhash_hamming, dhash_hex, dhash_popcount
from shared.src.lib.utils import cv2_io

logger = logging.getLogger(__name__)

FAMILIES = ('screen-id', 'focus', 'menu', 'banner', 'av-fault', 'content-type', 'other')
LABEL_SOURCES = ('run', 'human', 'teacher', 'none')

# Phones and tablets are never collected (TASK-27 §9): their automation verifies through the DOM, so
# no vision model answers phone screens, and their frames can show personal data.
EXCLUDED_DEVICE_MODELS = frozenset({
    'android_mobile', 'cloud_android_mobile', 'runner_android_mobile', 'phone_agent',
    'ios', 'ios_mobile', 'ios_phone', 'cloud_ios_mobile',
    'android_tablet', 'runner_android_tablet',  # same DOM-based automation, same privacy risk
})

# Userinterfaces never collected, matched with fnmatch on the name (owner decisions):
# - game showcases (TASK-33: 2048, Tetris, Flappy Bird, Pokémon), 2026-10-03: not TV / app screens;
# (The stb4 acceptance pipeline's temporary trees ARE collected: owner, 2026-10-04, their frames
# are filed under stb-<operator> by features/ai-dataset/scripts/fold_temp_trees.py.)
EXCLUDED_USERINTERFACE_PATTERNS = ('game2048-*', 'tetris-*', 'flappy-*', 'pokemon-*')

DHASH_GRID = 16          # same as ImageHelpers.FP_DHASH_GRID -> 256-bit hash
DHASH_BITS = 256
NEAR_DUP_BITS = 8        # §6 rule 2: within this many bits = near-duplicate
GROUP_CAP = 20           # §6 rule 3: regular samples per group
# Step 4j: a dHash with fewer set bits than this carries no identity. Same threshold as
# ``ImageHelpers.FP_REGION_MIN_BITS`` (backend_host/.../verification/image_helpers.py),
# where the fingerprint matcher already ignores such regions. Black frames, no-signal
# colour bars (darker left to right) and flat loading screens hash to 0-4 set bits, so
# "within NEAR_DUP_BITS" would make all of them the same image.
LOW_INFO_BITS = 20
MAX_LONG_SIDE = 1280
JPEG_QUALITY = 85

# §8: 85 / 10 / 5 over 100 buckets
_SPLITS = ((85, 'train'), (95, 'eval'), (100, 'holdout'))
SPLITS = tuple(name for _upper, name in _SPLITS)
STABLE_KEY_NAMES = ('team_id', 'family', 'device_model', 'node_id', 'focus_label')
# Step 4d: families whose conflict check spans the whole (team, family, device_model),
# not only the per-node dedup group. The rows scanned are capped, newest first.
# Step 4j: ``focus`` stays listed for the scope only; it is in CONFLICT_FREE_FAMILIES, so
# it never gets a conflict.
CROSS_NODE_FAMILIES = ('screen-id', 'focus')
CROSS_NODE_LIMIT = 2000
# Step 4j: families with no conflict check at all. Two frames of one ``focus`` menu differ
# only by the highlight, so near-identical frames with different labels are expected.
CONFLICT_FREE_FAMILIES = frozenset({'focus'})

_TRUTHY = ('1', 'true', 'yes', 'on')

ImageInput = Union[np.ndarray, bytes, str]


def enabled() -> bool:
    """Master switch on and a training bucket configured."""
    if os.environ.get('TRAINING_DATA_ENABLED', '').strip().lower() not in _TRUTHY:
        return False
    return cloudflare_utils.training_storage_configured()


def stable_keys(team_id: str, family: str, device_model: str,
                node_id: Optional[str] = None, focus_label: Optional[str] = None) -> Dict[str, Any]:
    """The §4 stable keys as a dict (the shape ``assign_split`` / ``should_keep`` take)."""
    return {'team_id': team_id, 'family': family, 'device_model': device_model,
            'node_id': node_id, 'focus_label': focus_label}


def _key_values(keys: Union[Mapping[str, Any], Sequence[Any]]) -> list:
    if isinstance(keys, Mapping):
        return [keys.get(name) for name in STABLE_KEY_NAMES]
    return list(keys)


def assign_split(stable_keys: Union[Mapping[str, Any], Sequence[Any]], dhash: str,
                 source_ref: Optional[Mapping[str, Any]] = None) -> str:
    """Deterministic split from ``(team_id, family, device_model, node_id, focus_label, dhash[:4])``.

    Pure. The label is deliberately not an input: near-identical frames share the
    tuple and so land in the same split, and the split never changes later.

    Step 4d: an ``av-fault`` sample whose ``source_ref`` carries ``alert_id`` hashes
    ``(team_id, family, device_model, alert_id)`` instead. Freeze and black frames are
    near-uniform, so ``dhash[:4]`` collapsed them into a handful of keys (all in
    train); per alert, the frames of one alert share a split and alerts spread
    85/10/5. Rows inserted before step 4d keep the split they got: the split is
    never recomputed and there is no migration.
    """
    values = _key_values(stable_keys)
    alert_id = source_ref.get('alert_id') if isinstance(source_ref, Mapping) else None
    if len(values) > 1 and values[1] == 'av-fault' and alert_id:
        parts = values[:3] + ['alert', alert_id]
    else:
        parts = values + [(dhash or '')[:4]]
    material = '\x1f'.join('' if p is None else str(p) for p in parts)
    bucket = int(hashlib.sha256(material.encode('utf-8')).hexdigest()[:8], 16) % 100
    for upper, name in _SPLITS:
        if bucket < upper:
            return name
    return 'holdout'


def is_informative(dhash: Optional[str]) -> bool:
    """Step 4j: True when ``dhash`` has at least ``LOW_INFO_BITS`` set bits. A
    low-information hash (black, colour bars, flat frames) is never compared for
    near-duplicates or conflicts. An empty or malformed hash is not informative."""
    try:
        return dhash_popcount(dhash or '') >= LOW_INFO_BITS
    except (TypeError, ValueError):
        return False


def _near_dup(a: Optional[str], b: Optional[str]) -> bool:
    """Both hashes informative and within ``NEAR_DUP_BITS``."""
    return is_informative(a) and is_informative(b) and dhash_hamming(a, b) <= NEAR_DUP_BITS


def should_keep(team_id: str, family: str, stable_keys: Mapping[str, Any], dhash: str,
                force: bool = False, skip_cap: bool = False) -> bool:
    """Pass 1 of §6: keep unless a near-duplicate exists in the group or the group is full.

    ``force=True`` (failure hooks) bypasses both checks. ``skip_cap=True`` keeps the
    near-duplicate check but ignores the cap: alert frames have no node, so one group
    holds every alert of a device model and a cap of 20 would stop collection within a
    day. Failures already in the group do not count towards the cap, since they entered
    through ``force``.

    Step 4j: a low-information ``dhash`` (``is_informative`` false) is never a
    near-duplicate and never makes another frame one, so distinct blank-ish screens are
    not dropped as copies of each other. Instead it is always capped: without
    ``skip_cap`` by the usual cap; with ``skip_cap`` the group holds at most
    ``GROUP_CAP`` low-information rows (all of them, failures included), so an unplugged
    box stores 20 blank frames per group (per device model for failed checks and alerts)
    and no more. ``force`` still bypasses everything.
    """
    if force:
        return True
    group = samples_db.get_group(team_id, family, stable_keys.get('device_model'),
                                 stable_keys.get('node_id'), stable_keys.get('focus_label'))
    if is_informative(dhash):
        for _sid, other_hash, _truth, _failure in group:
            if _near_dup(dhash, other_hash):
                return False
        if skip_cap:
            return True
    elif skip_cap:
        low = sum(1 for _sid, other_hash, _t, _f in group if not is_informative(other_hash))
        return low < GROUP_CAP
    regular = sum(1 for _sid, _h, _truth, is_failure in group if not is_failure)
    return regular < GROUP_CAP


def _to_bgr(image: ImageInput) -> Optional[np.ndarray]:
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        return image
    if isinstance(image, (bytes, bytearray)):
        return cv2.imdecode(np.frombuffer(bytes(image), np.uint8), cv2.IMREAD_COLOR)
    if isinstance(image, str) and os.path.exists(image):
        return cv2_io.imread(image, cv2.IMREAD_COLOR)
    return None


def _prepare_image(image: ImageInput):
    """Resize to <= MAX_LONG_SIDE, JPEG q85. Returns (jpeg_bytes, dhash) or (None, None)."""
    bgr = _to_bgr(image)
    if bgr is None or bgr.size == 0:
        return None, None
    h, w = bgr.shape[:2]
    scale = MAX_LONG_SIDE / float(max(h, w))
    if scale < 1.0:
        bgr = cv2.resize(bgr, (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', bgr, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    if not ok:
        return None, None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return buf.tobytes(), dhash_hex(gray, DHASH_GRID, DHASH_BITS)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def _same_value(a: Any, b: Any) -> bool:
    # '101' and 101 are the same channel: scalars compare as trimmed strings.
    if isinstance(a, (str, int, float)) and isinstance(b, (str, int, float))             and not isinstance(a, bool) and not isinstance(b, bool):
        return str(a).strip() == str(b).strip()
    return _canonical(a) == _canonical(b)


# Step 4g: label keys a human adds to describe the frame, which no model answer
# predicts. ``is_failure`` and the conflict check never compare them. A freeze strip
# labelled "still screen, not a problem" is ``{'incident_type': None, 'static_screen': True}``.
# Step 4k: a grouped ``screen-id`` label (``screen_groups``) also names the original node and
# its focus (``node``, ``node_label``, ``focus``). The answer is the group (``node_id``,
# ``label``); the focus is scored as its own question, so neither ``is_failure`` nor the
# conflict check compares them.
ANNOTATION_KEYS = frozenset({'static_screen', 'node', 'node_label', 'focus'})


def _differs(model_answer: Any, ground_truth: Any) -> bool:
    """True when the model got the labelled part wrong.

    A dict label only checks its own keys: a banner answer carries name, number,
    programme and confidence, but a numeric zap only knows the channel number.
    ``ANNOTATION_KEYS`` are never compared.
    """
    if model_answer is None or ground_truth is None:
        return False
    if isinstance(model_answer, dict) and isinstance(ground_truth, dict):
        return any(not _same_value(model_answer.get(k), v) for k, v in ground_truth.items()
                   if k not in ANNOTATION_KEYS)
    return not _same_value(model_answer, ground_truth)


def _label_key(family: Optional[str], truth: Any) -> str:
    """What two labels must share to agree. ``screen-id`` compares the node id (the
    display label may be re-cased); ``focus`` compares the focused text trimmed and
    lowercased. Every other family compares the canonical JSON, as before step 4d.

    Step 4k: a grouped ``screen-id`` label carries the **group** node id in ``node_id``
    (``screen_groups``), so two frames of Home with different tabs focused agree: the
    conflict check compares groups, and ``node``/``focus`` are never part of the key.

    Step 4f: a ``screen-id`` label for a screen not in the tree is ``{'node_id': None,
    'label': '<text>'}``; two such labels compare by the label, trimmed and lowercased,
    and never agree with a tree node. Step 4g: ``av-fault`` compares ``incident_type``
    only (``ANNOTATION_KEYS`` such as ``static_screen`` are not part of the answer)."""
    if family == 'screen-id' and isinstance(truth, dict) and truth.get('node_id') is not None:
        return 'node:' + str(truth['node_id']).strip()
    if family == 'screen-id' and isinstance(truth, dict) and 'node_id' in truth \
            and str(truth.get('label') or '').strip():
        return 'offtree:' + str(truth['label']).strip().lower()
    if family == 'focus' and isinstance(truth, dict) and truth.get('focused') is not None:
        return 'focus:' + str(truth['focused']).strip().lower()
    if family == 'av-fault' and isinstance(truth, dict) and 'incident_type' in truth:
        # Step 4g: only the fault type; a discard's {'incident_type': None} and a review's
        # {'incident_type': None, 'static_screen': True} agree.
        return 'av:' + _canonical(truth.get('incident_type'))
    return _canonical(truth)


def _has_conflict(group, sample_id: Optional[str], dhash: str, ground_truth: Any,
                  family: Optional[str] = None) -> bool:
    """§6 rule 6: a near-identical frame in the group carries a different label.
    Step 4j: never for ``CONFLICT_FREE_FAMILIES`` nor a low-information hash (either side)."""
    if ground_truth is None or family in CONFLICT_FREE_FAMILIES or not is_informative(dhash):
        return False
    own = _label_key(family, ground_truth)
    for other_id, other_hash, other_truth, _failure in group:
        if other_id == sample_id or other_truth is None or not other_hash:
            continue
        if _near_dup(dhash, other_hash) and _label_key(family, other_truth) != own:
            return True
    return False


def _cross_node_conflicts(rows, sample_id: Optional[str], dhash: str, ground_truth: Any,
                          family: str) -> List[str]:
    """Step 4d: ids of ``(id, dhash, ground_truth)`` rows near-identical to ``dhash``
    (within ``NEAR_DUP_BITS``) whose label differs. Pure. Step 4j: empty for
    ``CONFLICT_FREE_FAMILIES`` and for a low-information hash; low-information rows are
    never returned as partners."""
    if ground_truth is None or family in CONFLICT_FREE_FAMILIES or not is_informative(dhash):
        return []
    own = _label_key(family, ground_truth)
    out = []
    for other_id, other_hash, other_truth in rows:
        if other_id == sample_id or other_truth is None or not other_hash:
            continue
        if _near_dup(dhash, other_hash) and _label_key(family, other_truth) != own:
            out.append(other_id)
    return out


def find_conflicts(team_id: str, family: str, device_model: str, node_id: Optional[str],
                   focus_label: Optional[str], sample_id: Optional[str], dhash: str,
                   ground_truth: Any) -> Tuple[bool, List[str]]:
    """§6 rule 6 for one new or relabelled row: ``(its label_conflict, other ids to flag)``.

    Every family checks its own dedup group, as before. ``screen-id`` also checks the
    whole ``(team_id, family, device_model)`` (the newest ``CROSS_NODE_LIMIT`` labelled
    rows), and every conflicting row found there is returned so the caller flags it too
    (``flag_conflicts``). Other families return no ids: only the row being labelled is
    flagged, as before step 4d. Step 4j: ``focus`` and a low-information ``dhash``
    never conflict (``(False, [])`` without a DB read).
    """
    if ground_truth is None or family in CONFLICT_FREE_FAMILIES or not is_informative(dhash):
        return False, []
    group = samples_db.get_group(team_id, family, device_model, node_id, focus_label)
    conflict = _has_conflict(group, sample_id, dhash, ground_truth, family)
    others: List[str] = []
    if family in CROSS_NODE_FAMILIES:
        rows = samples_db.get_labelled_hashes(team_id, family, device_model, CROSS_NODE_LIMIT)
        others = _cross_node_conflicts(rows, sample_id, dhash, ground_truth, family)
        conflict = conflict or bool(others)
    return conflict, others


def former_partners(team_id: str, family: str, device_model: str, sample_id: str,
                    dhash: str, old_truth: Any) -> List[str]:
    """Before a relabel: the rows this sample conflicted with under its OLD label
    (``screen-id`` only, the family that flags both sides; ``focus`` has no conflicts
    since step 4j)."""
    if family not in CROSS_NODE_FAMILIES or family in CONFLICT_FREE_FAMILIES \
            or old_truth is None or not is_informative(dhash):
        return []
    rows = samples_db.get_labelled_hashes(team_id, family, device_model, CROSS_NODE_LIMIT)
    return _cross_node_conflicts(rows, sample_id, dhash, old_truth, family)


def clear_stale_partners(team_id: str, former_ids: List[str], still_conflicting: List[str]) -> List[str]:
    """After a relabel: a former partner that no longer conflicts with this sample keeps
    its flag only if it still conflicts with some other row. Recomputed per partner
    (against the DB, which already holds the new label). Returns the ids cleared.
    Never raises."""
    cleared: List[str] = []
    try:
        keep = set(still_conflicting or [])
        for pid in former_ids or []:
            if pid in keep:
                continue
            partner = samples_db.get_sample(pid, team_id)
            if not partner or not partner.get('label_conflict'):
                continue
            conflict, _ = find_conflicts(team_id, partner['family'], partner['device_model'],
                                         partner.get('node_id'), partner.get('focus_label'),
                                         pid, partner.get('dhash'), partner.get('ground_truth'))
            if not conflict:
                cleared.append(pid)
        if cleared:
            samples_db.set_label_conflict(team_id, cleared, False)
    except Exception as e:
        logger.warning(f"[training_samples] could not clear stale conflict flags: {e}")
    return cleared


def recompute_conflict_flags(rows: Sequence[Mapping[str, Any]]) -> Tuple[List[str], List[str]]:
    """Step 4j maintenance: ``label_conflict`` of every row under the current rules, as
    ``(ids to set, ids to clear)`` against each row's stored flag. Pure.

    ``rows`` are one team's rows (``id, family, device_model, node_id, focus_label,
    dhash, ground_truth, label_conflict``). A row conflicts when a near-identical
    labelled row with a different label exists in its scope: the whole
    ``(family, device_model)`` for ``screen-id``, the dedup group otherwise. Unlabelled,
    ``focus`` and low-information rows never conflict. Every row is evaluated, so a
    pair is flagged on both sides in every family (the live write flags only the
    labelled side outside ``screen-id``). Idempotent: applying the result and calling
    again returns two empty lists."""
    scopes: Dict[Tuple, List[Tuple[str, str, Any]]] = {}

    def scope_of(r):
        family = r.get('family')
        if family in CROSS_NODE_FAMILIES:
            return (family, r.get('device_model'))
        return (family, r.get('device_model'), r.get('node_id'), r.get('focus_label'))

    for r in rows:
        if r.get('ground_truth') is not None and r.get('dhash'):
            scopes.setdefault(scope_of(r), []).append((str(r['id']), r['dhash'], r['ground_truth']))
    to_set: List[str] = []
    to_clear: List[str] = []
    for r in rows:
        sid = str(r['id'])
        conflict = bool(_cross_node_conflicts(scopes.get(scope_of(r), []), sid, r.get('dhash'),
                                              r.get('ground_truth'), r.get('family')))
        if conflict and not r.get('label_conflict'):
            to_set.append(sid)
        elif not conflict and r.get('label_conflict'):
            to_clear.append(sid)
    return to_set, to_clear


def flag_conflicts(team_id: str, sample_ids: List[str]) -> None:
    """Set ``label_conflict`` on the other side of each conflict pair. Never raises."""
    if not sample_ids:
        return
    try:
        samples_db.set_label_conflict(team_id, sample_ids)
    except Exception as e:
        logger.warning(f"[training_samples] could not flag conflicting rows: {e}")


def record_sample(image: ImageInput, family: str, team_id: str, device_model: str,
                  userinterface: Optional[str] = None, node_id: Optional[str] = None,
                  focus_label: Optional[str] = None, prompt: Optional[str] = None,
                  model_answer: Any = None, ground_truth: Any = None, label_source: str = 'none',
                  source_ref: Optional[Dict[str, Any]] = None, boxes: Any = None,
                  force: bool = False, skip_cap: bool = False,
                  split: Optional[str] = None) -> Optional[str]:
    """Store one training sample. Returns its id, or None when disabled, skipped or failed.

    ``split`` (step 4h) overrides the §8 split for callers that decide it themselves,
    such as the navigation-tree seed of ``features/ai-dataset`` (train only). It must be
    one of ``SPLITS``; anything else refuses the sample. When omitted, ``assign_split``
    decides exactly as before. Never raises.
    """
    try:
        if not enabled():
            return None
        if split is not None and split not in SPLITS:
            logger.warning(f"[training_samples] refused: split={split!r} not in {SPLITS}")
            return None
        if family not in FAMILIES or label_source not in LABEL_SOURCES or not team_id or not device_model:
            logger.warning(f"[training_samples] refused: family={family} label_source={label_source} "
                           f"team_id={bool(team_id)} device_model={device_model}")
            return None
        if device_model in EXCLUDED_DEVICE_MODELS:
            return None
        if userinterface and any(fnmatch.fnmatch(userinterface, p) for p in EXCLUDED_USERINTERFACE_PATTERNS):
            return None
        if not samples_db.team_opted_in(team_id):
            return None

        jpeg, dhash = _prepare_image(image)
        if jpeg is None:
            logger.warning("[training_samples] could not decode/encode image")
            return None

        keys = stable_keys(team_id, family, device_model, node_id, focus_label)
        if not should_keep(team_id, family, keys, dhash, force=force, skip_cap=skip_cap):
            return None

        label_conflict, conflicting = find_conflicts(team_id, family, device_model, node_id,
                                                     focus_label, None, dhash, ground_truth)

        sample_id = str(uuid.uuid4())
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        object_key = f"{team_id}/{family}/{device_model}/{month}/{sample_id}.jpg"

        storage = cloudflare_utils.get_training_storage()
        storage.upload_bytes(jpeg, object_key, 'image/jpeg')

        row = {
            'id': sample_id,
            'team_id': team_id,
            'family': family,
            'object_key': object_key,
            'dhash': dhash,
            'device_model': device_model,
            'userinterface': userinterface,
            'node_id': node_id,
            'focus_label': focus_label,
            'prompt': prompt,
            'model_answer': model_answer,
            'ground_truth': ground_truth,
            'label_source': label_source,
            'is_failure': _differs(model_answer, ground_truth),
            'label_conflict': label_conflict,
            # Assigned once here and never changed (§8); old rows are not migrated.
            # An explicit ``split`` (step 4h) replaces the hash-based one.
            'split': split if split is not None else assign_split(keys, dhash, source_ref),
            'boxes': boxes,
            'source_ref': source_ref,
        }
        inserted = samples_db.insert_sample(row)
        if not inserted:
            try:
                storage.delete_file(object_key)
            except Exception:
                pass
            return None
        flag_conflicts(team_id, conflicting)
        return inserted
    except Exception as e:
        logger.warning(f"[training_samples] record_sample failed: {e}")
        return None


def attach_ground_truth(sample_id: str, team_id: str, ground_truth: Any, label_source: str) -> bool:
    """Pass 2 of §6: set the label, recompute ``is_failure``, flag ``label_conflict``.

    Returns True when the row was updated. Never raises.
    """
    try:
        if not enabled() or not sample_id or not team_id or label_source not in LABEL_SOURCES:
            return False
        row = samples_db.get_sample(sample_id, team_id)
        if not row:
            return False
        is_failure = _differs(row.get('model_answer'), ground_truth)
        former = former_partners(team_id, row['family'], row['device_model'], str(sample_id),
                                 row['dhash'], row.get('ground_truth'))
        conflict, conflicting = find_conflicts(team_id, row['family'], row['device_model'],
                                               row.get('node_id'), row.get('focus_label'),
                                               str(sample_id), row['dhash'], ground_truth)
        updated = samples_db.update_label(sample_id, team_id, ground_truth, label_source,
                                          is_failure, conflict)
        if updated:
            # This row's own flag is the recomputed `conflict` written above.
            flag_conflicts(team_id, conflicting)
            clear_stale_partners(team_id, former, conflicting)
        return updated
    except Exception as e:
        logger.warning(f"[training_samples] attach_ground_truth failed: {e}")
        return False
