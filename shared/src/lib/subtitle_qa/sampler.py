"""Cue-driven sampling: dense around subtitle cue edges, sparse elsewhere."""
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from .srt import Cue

EDGE_OFFSETS = (-0.5, -0.25, 0.25, 0.5)


@dataclass(frozen=True)
class Sample:
    t: float
    reason: str  # cue_start | cue_end | mid_cue | sparse | scene


def plan_samples(cues: Sequence[Cue], duration: float, sparse_step: float = 5.0,
                 scene_times: Iterable[float] = ()) -> List[Sample]:
    """Sample times (seconds, 0.05 s grid). Dense at cue edges (4 samples per edge),
    one mid-cue sample per cue, every `sparse_step` s elsewhere, plus scene changes."""
    picked = {}

    def add(t: float, reason: str):
        t = round(t * 20) / 20.0
        if 0.0 <= t < duration and t not in picked:
            picked[t] = reason

    for c in cues:
        for o in EDGE_OFFSETS:
            add(c.start + o, 'cue_start')
            add(c.end + o, 'cue_end')
        add((c.start + c.end) / 2.0, 'mid_cue')
    t = 0.0
    while t < duration:
        # skip sparse points that already have a sample within 1 s
        if not any((t + d) in picked for d in (-1.0, -0.5, 0.0, 0.5, 1.0)):
            add(t, 'sparse')
        t += sparse_step
    for s in scene_times:
        add(s, 'scene')
    return [Sample(t, picked[t]) for t in sorted(picked)]
