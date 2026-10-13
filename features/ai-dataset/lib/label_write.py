"""The one label write of the AI Dataset feature (TASK-27 step 4, shared in step 4i).

``apply_label`` is what the review route's ``POST /<id>/label`` does and what the step 4i
teacher importer (``scripts/triage_batch.py import``) does for a row with no independent
label: the ``attach_ground_truth`` semantics without its ``enabled()`` capture gate
(review and triage of stored rows must not depend on the capture switch):

  * ``is_failure`` recomputed against the model answer mapped to label shape;
  * cross-node conflict pairs found, both sides flagged, stale partner flags cleared
    (core ``training_samples`` helpers);
  * never on a frozen row (``eval_version``), and never a non-human label over a
    ``human`` one (human labels always win over teacher labels).

The DB write itself is injectable: the review route writes with core
``update_label``; the importer writes the label and its triage record in one guarded
statement (``triage_db.teacher_label_writer``).
"""
from __future__ import annotations

import importlib
import importlib.util
import os
from typing import Any, Callable, Dict, Optional

from shared.src.lib.ai import training_samples
from shared.src.lib.database import ai_training_samples_db as samples_db


def _load_schema():
    try:
        return importlib.import_module('features.ai-dataset.lib.label_schema')
    except Exception:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'label_schema.py')
        spec = importlib.util.spec_from_file_location('ai_dataset_label_schema', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


label_schema = _load_schema()

Writer = Callable[[str, str, Any, str, bool, bool], bool]


class LabelRefused(Exception):
    """The label may not be written: ``reason`` is 'frozen' or 'human'."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def failure_against(row: Dict[str, Any], ground_truth: Any) -> bool:
    """``is_failure`` of ``row`` under ``ground_truth``: compare against the model answer in
    label shape, so a raw ``{'content': ...}`` answer that says the right thing is not a
    failure. A failed-verification ``screen-id`` sample has no ``node_id`` in its model
    answer, so any screen makes it a failure (the verifier failed on that frame)."""
    answer = label_schema.label_from_model_answer(row.get('family'), row.get('model_answer'))
    return training_samples._differs(answer if answer is not None else row.get('model_answer'),
                                     ground_truth)


def apply_label(team_id: str, row: Dict[str, Any], ground_truth: Any, label_source: str,
                write: Optional[Writer] = None) -> Dict[str, Any]:
    """Write ``ground_truth`` on ``row`` (a row read with ``samples_db.get_sample``).

    Returns ``{'ok', 'is_failure', 'label_conflict'}``; ``ok`` is False when ``write``
    failed (the caller decides how to report it). Raises ``LabelRefused`` on a frozen row
    or on a non-human label over a human one. ``ground_truth`` must already be validated
    and normalised (``label_schema.validate_label`` / ``normalize_label``).
    """
    sample_id = str(row['id'])
    if row.get('eval_version'):
        raise LabelRefused('frozen', f"sample is frozen in {row['eval_version']}; its label cannot change")
    if label_source != 'human' and row.get('label_source') == 'human':
        raise LabelRefused('human', 'sample has a human label; a teacher label never replaces it')
    write = write or samples_db.update_label

    is_failure = failure_against(row, ground_truth)
    former = training_samples.former_partners(team_id, row['family'], row['device_model'],
                                              sample_id, row['dhash'], row.get('ground_truth'))
    conflict, conflicting = training_samples.find_conflicts(
        team_id, row['family'], row['device_model'], row.get('node_id'), row.get('focus_label'),
        sample_id, row['dhash'], ground_truth)

    if not write(sample_id, team_id, ground_truth, label_source, is_failure, conflict):
        return {'ok': False, 'is_failure': is_failure, 'label_conflict': conflict}
    training_samples.flag_conflicts(team_id, conflicting)
    training_samples.clear_stale_partners(team_id, former, conflicting)
    return {'ok': True, 'is_failure': is_failure, 'label_conflict': conflict}
