"""Wave grouping, slot and minion type for tracked minions.

Spawns come every 30 s starting at FIRST_SPAWN_S (the MinionsSpawning event of game 8018174981 is at 31 s). A minion is
first seen some travel time after it spawns. The travel phase T (mod 30 s) is estimated from the first sightings as the
circular median of (first_seen - FIRST_SPAWN_S) mod 30, then each track's wave is the spawn grid point nearest to
first_seen - T. Within a (wave, side) the slot is the rank along the wave's lane axis (principal direction of the first
stage positions). Minion type: slot 3 on waves 3, 6, 9 ... is a cannon; slots 0-2 melee; 4-6 caster. This is a rule, not
a classifier: detection rows carry no bar width, so type is labelled mtype_source = "wave_rule".
"""
import math

FIRST_SPAWN_S = 31.0
WAVE_S = 30.0
CANNON_EVERY = 3


def _circular_median(phases):
    """Median of phases on a circle of length WAVE_S: the phase with the most neighbours within 2 s."""
    best, best_n = 0.0, -1
    for p in phases:
        n = sum(1 for q in phases if min(abs(p - q), WAVE_S - abs(p - q)) <= 2.0)
        if n > best_n:
            best, best_n = p, n
    return best


def travel_phase(first_seen):
    phases = [(t - FIRST_SPAWN_S) % WAVE_S for t in first_seen]
    return _circular_median(phases) if phases else 0.0


def wave_of(first_t, travel):
    return max(1, round((first_t - FIRST_SPAWN_S - travel) / WAVE_S) + 1)


def _lane_axis(points):
    """Unit direction of the first principal axis of 2-D points (stage px). Falls back to x when too few points."""
    if len(points) < 2:
        return (1.0, 0.0)
    mx = sum(p[0] for p in points) / len(points)
    my = sum(p[1] for p in points) / len(points)
    sxx = sum((p[0] - mx) ** 2 for p in points)
    syy = sum((p[1] - my) ** 2 for p in points)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    return (math.cos(ang), math.sin(ang))


def assign(tracks):
    """Set wave, slot and mtype on each track (dict attributes on Track objects). Returns the travel phase used."""
    travel = travel_phase([tr.first_t for tr in tracks])
    groups = {}
    for tr in tracks:
        tr.wave = wave_of(tr.first_t, travel)
        groups.setdefault((tr.wave, tr.kind), []).append(tr)
    for (wave, kind), members in groups.items():
        pts = [(tr.hist[0][1], tr.hist[0][2]) for tr in members]
        ax = _lane_axis(pts)
        order = sorted(members, key=lambda tr: tr.hist[0][1] * ax[0] + tr.hist[0][2] * ax[1])
        for slot, tr in enumerate(order):
            tr.slot = slot
            if wave % CANNON_EVERY == 0 and slot == 3:
                tr.mtype = "cannon"
            elif slot <= 2:
                tr.mtype = "melee"
            elif 4 <= slot <= 6:
                tr.mtype = "caster"
            else:
                tr.mtype = None
    return travel
