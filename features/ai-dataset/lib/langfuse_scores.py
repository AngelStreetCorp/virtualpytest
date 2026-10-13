"""Verdicts and eval runs to Langfuse (TASK-27, owner decision 2026-10-04).

The dataset (device frames + tree labels), its review and its triage stay ours. What
Langfuse does better, comparing models and prompts over time on the traces it already
holds, is fed from here instead of a page of our own:

* **Verdicts on production traces.** A sample whose ``source_ref.trace_id`` is set came from
  a real AI call (today ``banner`` and ``content-type``). When it gets a verdict, a BOOLEAN
  score goes on that trace: ``verdict_human`` (review label route) or ``verdict_ai``
  (``triage_batch.py import``, rows it decides), value = the model's answer
  (``model_answer``, mapped to the label shape) matches the verdict under the family
  comparator. The score id is derived from (trace, name), so a new verdict replaces the
  previous one. ``screen-id`` / ``focus`` / ``av-fault`` samples come from navigation and
  alerts, have no trace and are skipped.
* **Eval runs as dataset runs.** ``score_eval.py`` upserts a dataset per family
  (``vpt-eval-<family>``, ``vpt-eval-<family>-<eval-vN>`` for a frozen set), one item per
  scored sample, links each scored call's trace to its item under a run named after the
  result file (``run_id``) and scores it ``correct`` (plus ``focus_correct`` for a grouped
  ``screen-id`` row with a focus, on the same trace).

Langfuse v2 SDK only (``langfuse>=2.0.0,<3``); the client is core ``tracing.get_client()``.
Nothing here ever raises into its caller: a Langfuse error is a logged warning, a
disabled tracing or a missing trace id is a no-op.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCORE_HUMAN = 'verdict_human'
SCORE_AI = 'verdict_ai'
SCORE_CORRECT = 'correct'
SCORE_FOCUS = 'focus_correct'
DATASET_PREFIX = 'vpt-eval-'
COMMENT_MAX = 300
# Fixed namespace: the same (trace, score name) always gives the same score id (an upsert).
_SCORE_NS = uuid.UUID('6f1c3a52-8f0e-4d4b-9d3e-27a1b0c5e927')


def _load_lib(name: str):
    try:
        return importlib.import_module(f'features.ai-dataset.lib.{name}')
    except Exception:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'{name}.py')
        spec = importlib.util.spec_from_file_location(f'ai_dataset_{name}', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


label_schema = _load_lib('label_schema')
comparators = _load_lib('comparators')


def tracing_enabled() -> bool:
    try:
        from shared.src.lib.ai import tracing
        return tracing.enabled()
    except Exception:
        return False


def get_client():
    """Core ``tracing.get_client()``, or None (tracing off, SDK missing, import error)."""
    try:
        from shared.src.lib.ai import tracing
        return tracing.get_client()
    except Exception as e:
        logger.warning(f"[langfuse_scores] no Langfuse client: {e}")
        return None


def trace_id_of(row: Optional[Dict[str, Any]]) -> Optional[str]:
    ref = (row or {}).get('source_ref')
    if isinstance(ref, str):
        try:
            ref = json.loads(ref)
        except ValueError:
            return None
    value = ref.get('trace_id') if isinstance(ref, dict) else None
    return str(value) if value else None


def short_text(value: Any, limit: int = COMMENT_MAX) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def score_id(trace_id: str, name: str) -> str:
    return str(uuid.uuid5(_SCORE_NS, f'{trace_id}:{name}'))


def model_verdict(family: str, model_answer: Any, truth: Any) -> Optional[Tuple[bool, str]]:
    """``(the model's answer matches truth, detail)`` under the family comparator, or None
    when the family has no comparator or the truth is not a label object. An answer that
    does not map to the label shape scores wrong (``unparsed answer``)."""
    if family not in comparators.COMPARATORS or not isinstance(truth, dict):
        return None
    parsed = label_schema.label_from_model_answer(family, model_answer)
    return comparators.compare(family, truth, parsed if isinstance(parsed, dict) else None)


def post_score(client, trace_id: str, name: str, value: bool, comment: Optional[str] = None,
               id: Optional[str] = None) -> Optional[str]:
    """One BOOLEAN score (1/0) on ``trace_id``. Returns the score id, None on failure. Never
    raises. The SDK queues it and sends it from its own thread (``flush`` to wait)."""
    if client is None or not trace_id:
        return None
    sid = id or score_id(trace_id, name)
    try:
        client.score(id=sid, trace_id=trace_id, name=name, value=1.0 if value else 0.0,
                     data_type='BOOLEAN', comment=short_text(comment) if comment else None)
        return sid
    except Exception as e:
        logger.warning(f"[langfuse_scores] score {name} on trace {trace_id} failed: {e}")
        return None


def score_verdict(row: Dict[str, Any], truth: Any, name: str, comment: Optional[str] = None,
                  client=None) -> Optional[str]:
    """Score the row's trace with whether its model answer matches ``truth``. Synchronous
    (the caller flushes). None when skipped: no trace id, tracing off, no comparator."""
    try:
        trace_id = trace_id_of(row)
        if not trace_id:
            return None
        verdict = model_verdict(row.get('family'), row.get('model_answer'), truth)
        if verdict is None:
            return None
        client = client or get_client()
        if client is None:
            return None
        ok, detail = verdict
        return post_score(client, trace_id, name, ok, f"{comment} | {detail}" if comment else detail)
    except Exception as e:
        logger.warning(f"[langfuse_scores] {name} on sample {(row or {}).get('id')} failed: {e}")
        return None


def score_verdict_async(row: Dict[str, Any], truth: Any, name: str, comment: Optional[str] = None,
                        client=None) -> Optional[threading.Thread]:
    """``score_verdict`` off the request path (daemon thread). None, and no thread, when
    there is nothing to send (no trace id, tracing off). Never raises."""
    try:
        if not trace_id_of(row) or (client is None and not tracing_enabled()):
            return None
        thread = threading.Thread(target=score_verdict, args=(row, truth, name, comment, client),
                                  name='langfuse-verdict', daemon=True)
        thread.start()
        return thread
    except Exception as e:
        logger.warning(f"[langfuse_scores] {name} not started: {e}")
        return None


def human_comment(ground_truth: Any) -> str:
    return f"human: {short_text(ground_truth, 200)}"


def ai_comment(teacher_model: str, label: Any, status: str) -> str:
    return f"teacher {teacher_model} ({status}): {short_text(label, 200)}"


def flush(client) -> None:
    if client is None:
        return
    try:
        client.flush()
    except Exception as e:
        logger.warning(f"[langfuse_scores] flush failed: {e}")


# ---- eval runs -> dataset runs ------------------------------------------------------------------

def dataset_name(family: str, eval_version: Optional[str] = None) -> str:
    return f"{DATASET_PREFIX}{family}" + (f"-{eval_version}" if eval_version else '')


def item_id(dataset: str, sample_id: str) -> str:
    """A Langfuse item id is unique across the whole project, and one sample can be in two
    datasets (human eval rows and a frozen version): the dataset name prefixes the sample id."""
    return f"{dataset}:{sample_id}"


def _link(client, run_name: str, item: str, trace_id: str, metadata: Dict[str, Any],
          description: str) -> None:
    """``POST /api/public/dataset-run-items`` through the v2 SDK's API client (what
    ``DatasetItemClient.link`` sends, without fetching the dataset first)."""
    from langfuse.api.resources.dataset_run_items.types.create_dataset_run_item_request import (
        CreateDatasetRunItemRequest,
    )
    client.client.dataset_run_items.create(request=CreateDatasetRunItemRequest(
        runName=run_name, runDescription=description, metadata=metadata,
        datasetItemId=item, traceId=trace_id))


def push_eval_run(result: Dict[str, Any], rows: List[Dict[str, Any]],
                  question_for: Callable[[Dict[str, Any]], Optional[str]], client=None,
                  log: Callable[[str], None] = lambda s: None) -> Dict[str, Any]:
    """Upsert the family's dataset and its items, link every traced sample to its item under
    the run ``result['run_id']`` and score it. Returns counts; never raises (a failure is in
    ``errors`` and logged). ``question_for(row)`` is the prompt the row was asked."""
    family, version = result.get('family'), result.get('eval_version')
    frozen = result.get('source') == 'eval-version'
    dataset = dataset_name(family, version if frozen else None)
    run_name = result.get('run_id')
    summary: Dict[str, Any] = {'dataset': dataset, 'run': run_name, 'items': 0, 'linked': 0,
                               'scores': 0, 'no_trace': 0, 'errors': []}
    client = client or get_client()
    if client is None:
        summary['errors'].append('tracing off')
        return summary
    by_id = {str(r.get('id')): r for r in rows}
    run_meta = {k: result.get(k) for k in ('profile', 'profile_id', 'endpoint', 'model', 'usage_key',
                                           'source', 'eval_version', 'labels', 'git_commit', 'created_at')}
    run_meta['model_reported'] = result.get('model_reported')
    run_meta['accuracy'] = (result.get('summary') or {}).get('accuracy')
    description = f"score_eval {family}: profile {result.get('profile')} ({result.get('model')}), fallback disabled"
    try:
        client.create_dataset(name=dataset, description=f"TASK-27 eval rows of {family}"
                              + (f" frozen in {version}" if frozen else ' (human-verified)'),
                              metadata={'family': family, 'eval_version': version, 'team_id': result.get('team_id')})
    except Exception as e:
        summary['errors'].append(f'dataset: {e}')
        logger.warning(f"[langfuse_scores] dataset {dataset} not created: {e}")
        return summary
    for sample in result.get('samples') or []:
        sid = str(sample.get('id'))
        row = by_id.get(sid) or {}
        item = item_id(dataset, sid)
        try:
            client.create_dataset_item(
                dataset_name=dataset, id=item,
                input={'object_key': row.get('object_key'), 'userinterface': sample.get('userinterface'),
                       'question': question_for(row) if row else None},
                expected_output=sample.get('truth'),
                metadata={'sample_id': sid, 'split': row.get('split'), 'eval_version': row.get('eval_version'),
                          'device_model': sample.get('device_model')})
            summary['items'] += 1
            trace_id = sample.get('trace_id')
            if not trace_id:
                summary['no_trace'] += 1
                continue
            _link(client, run_name, item, trace_id, run_meta, description)
            summary['linked'] += 1
            if post_score(client, trace_id, SCORE_CORRECT, bool(sample.get('correct')), sample.get('detail')):
                summary['scores'] += 1
            focus = sample.get('focus')
            if focus is not None:
                note = f"{focus.get('detail')} (focus call trace {focus.get('trace_id')})"
                if post_score(client, trace_id, SCORE_FOCUS, bool(focus.get('correct')), note):
                    summary['scores'] += 1
        except Exception as e:
            summary['errors'].append(f'{sid}: {e}')
            log(f"[langfuse_scores] sample {sid}: {e}")
    flush(client)
    if summary['errors']:
        logger.warning(f"[langfuse_scores] run {run_name}: {len(summary['errors'])} Langfuse errors, "
                       f"first: {summary['errors'][0]}")
    return summary
