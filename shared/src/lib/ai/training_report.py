"""
Training data panel of Monitoring → AI usage (TASK-87 §6.7). Pure aggregation over ``ai_training_samples``
rows (TASK-27) and the ``ai_calls`` rows their ``source_ref.request_id`` points at.

It counts and scores; it builds no training jobs. ``is_failure`` is TASK-27's own verdict
(the model answer differs from the ground truth), so production accuracy = 1 - failures / labelled.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

LABEL_SOURCES = ("human", "run", "teacher", "none")


def request_id_of(sample: dict) -> Optional[str]:
    ref = sample.get("source_ref")
    return ref.get("request_id") if isinstance(ref, dict) and ref.get("request_id") else None


def summarize(samples: Iterable[dict]) -> dict:
    """Samples per family and device model: total, labelled, by label source, failures, label conflicts."""
    groups: dict[tuple[str, str], dict] = {}
    total = {"samples": 0, "labelled": 0, "failures": 0, "conflicts": 0, "linked": 0}
    for s in samples:
        key = (s.get("family") or "other", s.get("device_model") or "—")
        g = groups.setdefault(key, {"family": key[0], "device_model": key[1], "samples": 0, "labelled": 0,
                                    "failures": 0, "conflicts": 0, "linked": 0,
                                    "by_source": {src: 0 for src in LABEL_SOURCES}})
        source = s.get("label_source") if s.get("label_source") in LABEL_SOURCES else "none"
        for bucket in (g, total):
            bucket["samples"] += 1
            bucket["labelled"] += source != "none"
            bucket["failures"] += bool(s.get("is_failure")) and source != "none"
            bucket["conflicts"] += bool(s.get("label_conflict"))
            bucket["linked"] += request_id_of(s) is not None
        g["by_source"][source] += 1
    return {"totals": total, "groups": sorted(groups.values(), key=lambda g: (-g["samples"], g["family"]))}


def accuracy_by_model(samples: Iterable[dict], calls_by_request: dict[str, dict]) -> list[dict]:
    """Production accuracy per (usage, profile, model): labelled samples whose call is known, with the
    average cost of that profile's priced calls next to it ("cheapest model that is accurate enough")."""
    rows: dict[tuple, dict] = {}
    for s in samples:
        rid = request_id_of(s)
        call = calls_by_request.get(rid) if rid else None
        if call is None or (s.get("label_source") or "none") == "none":
            continue
        key = (call.get("usage_key") or "?", call.get("profile") or "?", call.get("model") or "?")
        r = rows.setdefault(key, {"usage": key[0], "profile": key[1], "model": key[2], "labelled": 0, "failures": 0,
                                  "_cost": 0.0, "_priced": 0})
        r["labelled"] += 1
        r["failures"] += bool(s.get("is_failure"))
        if call.get("cost") is not None:
            r["_cost"] += float(call["cost"])
            r["_priced"] += 1
    out = []
    for r in rows.values():
        r["accuracy"] = round(1 - r["failures"] / r["labelled"], 4)
        r["avg_cost"] = round(r.pop("_cost") / r["_priced"], 6) if r["_priced"] else None
        r.pop("_priced")
        out.append(r)
    return sorted(out, key=lambda r: (-r["labelled"], r["usage"], r["profile"]))
