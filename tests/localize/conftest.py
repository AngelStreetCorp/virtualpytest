"""Local conftest for the localize-regression harness.

Pytest only auto-discovers hooks that live in a ``conftest.py`` — hooks
defined inside a test file are not registered. We keep the harness driver
in ``test_localize_regression.py`` and put the ``pytest_terminal_summary``
hook here so the per-field precision/recall summary lands in the visible
end-of-run report.

The real-classifier test (``test_localize_real_match.py``, gated by
``RUN_REAL_MATCHER=1``) registers its own session-finish + terminal-summary
hooks here too, so the per-frame diff and PR summary land in
``results/real_match_11.json`` and the visible terminal output.
"""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path


def _find_harness_module(here_file_suffix: str):
    """Resolve a test module by suffix-match on its ``__file__`` attribute.

    Pytest can load the same file under different module names depending on
    its rootdir / conftest path handling, so we scan ``sys.modules`` and
    return the first one whose ``__file__`` ends with the given suffix. Falls
    back to a plain import when the suffix doesn't match (rare — means the
    test wasn't loaded yet).
    """
    for mod in list(sys.modules.values()):
        mod_file = getattr(mod, '__file__', '') or ''
        if mod_file.endswith(here_file_suffix):
            return mod
    return None


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Append the localize-regression PR + run summary AND the real-match
    PR + run summary to the terminal summary section.

    The accumulators live in the harness modules (``_PR_TPFP`` /
    ``_RUN_SUMMARY``) as module-level mutable state. We re-resolve them at
    hook time via ``importlib`` so we always see the same instance the test
    functions wrote to (Python's import cache returns the same module object,
    so the dict identity is stable across the conftest and the test).
    """
    # ── localize-regression (mock harness) ─────────────────────────────────
    try:
        h = _find_harness_module('tests/localize/test_localize_regression.py')
        if h is None:
            h = importlib.import_module('tests.localize.test_localize_regression')
        tp_fp = h._PR_TPFP
        run_summary = h._RUN_SUMMARY
        lines = []
        if tp_fp:
            lines.append("[localize-regression] per-field precision/recall:")
            for fld in sorted(tp_fp):
                values = sorted(tp_fp[fld], key=lambda v: (v is None, v))
                for value in values:
                    counts = tp_fp[fld][value]
                    tp = counts.get('tp', 0)
                    fp = counts.get('fp', 0)
                    fn = counts.get('fn', 0)
                    precision = tp / (tp + fp) if (tp + fp) else 0.0
                    recall    = tp / (tp + fn) if (tp + fn) else 0.0
                    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
                    lines.append(
                        f"  {fld}={value!r}: P={precision:.2f} R={recall:.2f} "
                        f"F1={f1:.2f} (TP={tp} FP={fp} FN={fn})"
                    )
        lines.append(
            f"[localize-regression] run summary: "
            f"passed={run_summary['passed']} failed={run_summary['failed']} "
            f"skipped_synthetic={run_summary['skipped_synthetic']} "
            f"skipped_unreachable={run_summary['skipped_unreachable']} "
            f"warned_unlisted={run_summary['warned_unlisted']}"
        )
        terminalreporter.section("localize-regression summary", sep="-")
        for line in lines:
            terminalreporter.write_line(line)
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"[localize-regression] summary emit failed: {e}\n")

    # ── real-match (real-classifier harness) ───────────────────────────────
    try:
        h = _find_harness_module('tests/localize/test_localize_real_match.py')
        if h is None:
            return
        tp_fp = getattr(h, '_PR_TPFP', None) or {}
        run_summary = getattr(h, '_RUN_SUMMARY', None) or {}
        lines = []
        if tp_fp:
            lines.append("[real-match] per-field precision/recall:")
            for fld in sorted(tp_fp):
                values = sorted(tp_fp[fld], key=lambda v: (v is None, v))
                for v in values:
                    c = tp_fp[fld][v]
                    tp, fp, fn = c['tp'], c['fp'], c['fn']
                    precision = tp / (tp + fp) if (tp + fp) else 0.0
                    recall = tp / (tp + fn) if (tp + fn) else 0.0
                    f1 = (
                        2 * precision * recall / (precision + recall)
                        if (precision + recall) else 0.0
                    )
                    lines.append(
                        f"  {fld}={v!r}: P={precision:.2f} R={recall:.2f} "
                        f"F1={f1:.2f} (TP={tp} FP={fp} FN={fn})"
                    )
        lines.append(
            f"[real-match] run summary: "
            f"passed={run_summary.get('passed', 0)} "
            f"failed={run_summary.get('failed', 0)} "
            f"skipped_unreachable={run_summary.get('skipped_unreachable', 0)} "
            f"warned_unlisted={run_summary.get('warned_unlisted', 0)}"
        )
        terminalreporter.section("real-match summary", sep="-")
        for line in lines:
            terminalreporter.write_line(line)
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"[real-match] summary emit failed: {e}\n")


def pytest_sessionfinish(session, exitstatus):
    """Write ``results/real_match_11.json`` (per-frame diff) and
    ``results/real_match_pr.json`` (per-field P/R/F1) for the real-match
    harness. Runs even when every test was skipped so a future run has a
    baseline to diff against (the task spec's primary deliverable).

    The accumulators live on the test module (see test_localize_real_match.py).
    Resolved at hook time via ``importlib`` so we always see the same
    instance the test functions wrote to.
    """
    try:
        h = _find_harness_module('tests/localize/test_localize_real_match.py')
        if h is None:
            return
        captured = getattr(h, '_CAPTURED', None) or []
        run_summary = getattr(h, '_RUN_SUMMARY', None) or {}
        tp_fp = getattr(h, '_PR_TPFP', None) or {}

        results_dir = Path(__file__).parent / 'results'
        results_dir.mkdir(exist_ok=True)

        diff = {
            'run_at': time.time(),
            'manifest': 'manifest_real_match.json',
            'rows': list(captured),
            'run_summary': dict(run_summary),
        }
        out_path = results_dir / 'real_match_11.json'
        with out_path.open('w') as f:
            json.dump(diff, f, indent=2, default=str)

        pr = {'per_field': {}, 'run_summary': dict(run_summary)}
        for fld in sorted(tp_fp):
            pr['per_field'][fld] = {}
            for v in sorted(tp_fp[fld], key=lambda x: (x is None, x)):
                c = tp_fp[fld][v]
                tp, fp, fn = c['tp'], c['fp'], c['fn']
                precision = tp / (tp + fp) if (tp + fp) else 0.0
                recall = tp / (tp + fn) if (tp + fn) else 0.0
                f1 = (
                    2 * precision * recall / (precision + recall)
                    if (precision + recall) else 0.0
                )
                pr['per_field'][fld][str(v)] = {
                    'tp': tp, 'fp': fp, 'fn': fn,
                    'precision': round(precision, 3),
                    'recall': round(recall, 3),
                    'f1': round(f1, 3),
                }
        pr_path = results_dir / 'real_match_pr.json'
        with pr_path.open('w') as f:
            json.dump(pr, f, indent=2, default=str)
    except Exception as e:  # pragma: no cover
        import traceback
        sys.stderr.write(f"[real-match] session-finish hook failed: {e}\n{traceback.format_exc()}\n")
