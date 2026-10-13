"""TASK-87 §6.7: training data panel aggregation (pure)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from shared.src.lib.ai import training_report as tr  # noqa: E402


def sample(family="banner", model="stb-x", source="run", failure=False, conflict=False, rid=None):
    return {"family": family, "device_model": model, "label_source": source, "is_failure": failure,
            "label_conflict": conflict, "source_ref": {"request_id": rid} if rid else None}


def test_summary_counts_labels_conflicts_and_links():
    out = tr.summarize([sample(rid="a"), sample(source="human", failure=True), sample(source="none", failure=True),
                        sample(family="menu", conflict=True)])
    banner = next(g for g in out["groups"] if g["family"] == "banner")
    assert banner["samples"] == 3 and banner["labelled"] == 2 and banner["failures"] == 1  # unlabelled failure not counted
    assert banner["by_source"] == {"human": 1, "run": 1, "teacher": 0, "none": 1} and banner["linked"] == 1
    assert out["totals"]["samples"] == 4 and out["totals"]["conflicts"] == 1


def test_accuracy_joins_calls_and_prices_them():
    calls = {"r1": {"usage_key": "vision.banner", "profile": "gpu", "model": "qwen", "cost": 0.002},
             "r2": {"usage_key": "vision.banner", "profile": "gpu", "model": "qwen", "cost": 0.004},
             "r3": {"usage_key": "vision.banner", "profile": "claude", "model": "sonnet", "cost": None}}
    out = tr.accuracy_by_model([sample(rid="r1"), sample(rid="r2", failure=True), sample(rid="r3"),
                                sample(rid="r1", source="none"), sample(rid="missing")], calls)
    gpu = next(r for r in out if r["profile"] == "gpu")
    assert gpu["labelled"] == 2 and gpu["accuracy"] == 0.5 and gpu["avg_cost"] == pytest.approx(0.003)
    assert next(r for r in out if r["profile"] == "claude")["avg_cost"] is None
