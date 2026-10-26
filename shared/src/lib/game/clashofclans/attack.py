"""
Attack harness for the Clash of Clans vision-LLM player (TASK-100).

The model is too slow to deploy troops one call at a time: run e0-a389522c (2026-10-14) deployed one
Barbarian every ~11 s and lost at 0%. This module takes the battle away from the model:

* ``is_battle_screen`` / ``is_result_screen``: pixel checks on the fixed S21 layout (1170x540 image
  space), no model call.
* ``plan_deploy``: ONE narrow model question for ONE deploy point (next to the side nearest the Town Hall
  or storages, away from the defenses), or ``skip`` = tap Next for another base. The code checks the
  answer (the whole clump inside the deploy band, away from the Surrender button and the HUD, near the
  base). An invalid answer is not used: the attack waits out the timer instead of guessing.
* ``run_attack``: for each troop card left to right (Barbarians first, then Archers behind them), select
  it and tap every troop within ``CLUMP_R`` px of the point, then wait for the result screen with no
  model call and tap Return Home. Troops walk to the NEAREST building: a spread line splits the army
  and the defenses kill it one by one (owner review 2026-10-14: Defeat 46 %, gravestones all around
  the base). One clump wins fights.
* The game refuses a deploy silently - no marker, no sound, the troop count does not move - so the
  harness reads the picture after a first small batch of taps. Two signals, both free:
  the GROUND under the plan point must be open grass (``is_grass``) - a tap on a roof, a wall or a
  path deploys nothing, whatever the model says - and the COUNT BADGE of the army card must move
  (``count_changed``): a troop that left the tray changes its number. The battlefield around the
  point is NOT a signal: the fight moves all the time, so it "changes" on every tap - that false
  positive is what made the harness send 79 taps into a refused point (BUG-0720, BUG-0725).

Coordinates are model-image coordinates (1170x540). The device is reached through the same ``Device``
interface as ``llm_player.play``; taps are converted with ``to_device``.
"""

from __future__ import annotations

import base64
import io
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageChops

from .llm_player import to_device

# Layout of the S21 FE battle screen in model-image pixels (measured on run a389522c frames).
SURRENDER_BOX = (50, 385, 160, 418)      # red Surrender button; never tap inside it
RESULT_BOX = (525, 437, 648, 492)        # green Return Home button on the result screen
RESULT_TAP = (586, 464)                  # centre of RESULT_BOX
CARD_TAP = (220, 485)                    # first troop card in the tray (x19 Barbarian card)
CARD_PITCH = 72                          # tray slot pitch (run 224154 frame 004: slots at x 220, 292, 365)
CARD_TAPS = [(CARD_TAP[0] + CARD_PITCH * k, CARD_TAP[1]) for k in range(6)]
NEXT_BOX = (985, 358, 1110, 410)         # orange Next button while scouting (frame 004: 972-1123 x 351-416)
NEXT_TAP = (1047, 383)
NEXT_ORANGE_FRACTION = 0.30
MAX_SKIPS = 2                            # each Next costs a little gold
CLUMP_R = 20                             # every deploy tap lands within this many px of the plan point
TRAY_Y = 430                             # y >= TRAY_Y is the troop tray: taps only select cards
HUD_TOP_Y = 80                           # top resource / timer bar: never deploy there
BATTLE_RED_FRACTION = 0.30               # Surrender box red fraction above this = battle screen
RESULT_GREEN_FRACTION = 0.20             # Return Home box green fraction above this = result screen

TAPS_PER_PASS = 10                       # taps per card when the count could not be read
MAX_TAPS_PER_CARD = 80                   # taps per card in the single deploy wave
MAX_TOTAL_TAPS = 140                     # hard cap on the deploy taps of one battle
TAP_GAP_S = 0.15                         # between deploy taps (device time)
RESULT_TIMEOUT_S = 240.0                 # battle timer is 3 min; wait for Return Home at most this long
POLL_S = 3.0                             # screenshot poll interval while waiting for the result
MAX_CARDS = 3                            # only the first three tray slots are mapped (Barbarian, Archer, King)
MAX_DEPLOY_ATTEMPTS = 2                  # deploy again with another point when the taps deployed no troop
DEPLOY_CHECK_RATIO = 0.75                # more than this share of the army still in the tray = nothing came out
WAVE_GAP_S = 8.0                         # the tank wave walks and pulls the defenses before the next wave
OVERALL_DAMAGE_BOX = (940, 330, 1170, 430)   # the panel that appears once the battle is running
BATTLE_STARTED_DARK_FRACTION = 0.15      # dark pixels in that box: scouting 0.06-0.10, battle 0.21-1.00
PRE_BATTLE_TIMEOUT_S = 45.0              # the CoC countdown is 30 s; give up after this
PRE_BATTLE_POLL_S = 3.0
NEXT_BASE_TIMEOUT_S = 12.0               # the next base needs a moment to load before it is planned

# The deploy check: the game says nothing when it refuses a deploy (no marker, no sound, the troop
# count does not move), so the harness reads the picture. Two honest signals:
#
# * the GROUND under the plan point must be open grass. A troop only comes out on grass: the game
#   refuses a tap on a roof, a wall or a path without saying anything. Run 218ca432 (2026-10-20)
#   planned (700, 370) - the roof of the dark elixir storage - and sent 79 taps there: 0 % damage,
#   the count badge stayed at x59 for the whole battle.
# * the COUNT BADGE of the army card ("x59") must move. A troop that left the tray changes its
#   number, a refused tap leaves the number alone. Measured on the frames of run 218ca432: the
#   badge is pixel-identical while the game refuses (nothing moved in 150+ frames). Arming a card
#   also moves the badge - the card rises a pixel and the other card dims - but that animation
#   lasts 0.4 s (measured at 10 fps on the winning battle of run bcaa97d8) and the picture that
#   opens the comparison is only taken after the card has settled (CARD_SETTLE_S), so the arming
#   never falls inside the comparison.
GRASS_PATCH = 5                      # px around the point that must be grass
GRASS_MIN = 0.55                    # share of the patch that must be grass
GRASS_SEARCH_PX = 40                # how far the harness looks for open grass around the plan point
COUNT_BOXES = ((210, 448, 247, 463), (286, 448, 319, 463))   # the count badge of card 1 and card 2
COUNT_CHANGED_PX = 12               # ink pixels that must move for the count to count as changed
COUNT_DELTA = 60                    # a channel must move by this much to count as changed
COUNT_MIN_INK = 20                  # white pixels that make a number readable on the card
VERIFY_TAPS = 4                     # taps before the first check that the deploy landed
FALLBACK_TAPS = 2                   # taps before the check of a fallback point: two troops are
                                    # enough to move the number, and a refused point must not
                                    # cost the army more than it has to
CARD_SETTLE_S = 1.2                 # the card must be armed and still before the picture is taken
RETRY_PAUSE_S = 2.0                 # the game may still be busy: wait before the next point
# The points the harness tries when the game refuses the plan point.
#
# The game refuses a point silently, and the refusal is about the GROUND, not about the tap:
# measured on the runs of 19:00 and 20:00 (2026-10-20), every refused point sat between the
# buildings of the base (33 to 185 px from the Town Hall) and every point the game took sat on
# the open field around the base (140 to 355 px from the Town Hall). The old code only shifted
# the plan point by 50 px in four directions, so a plan inside the base stayed inside the base:
# 4 of the 5 defeats of those runs were "no_deploy" - every point refused, 0 % damage, the whole
# army still in the tray. The harness now offers the game a whole neighbourhood and puts the
# roomiest open ground first.
CANDIDATE_RINGS = (0, 30, 60, 90, 120, 150, 190, 230, 270)   # radii around the plan point
CANDIDATES_PER_RING = 3                                # points kept per radius, so the list spreads
                                                          # over the whole neighbourhood instead of
                                                          # filling the ring next to the plan point
CANDIDATE_TOTAL = 20                                     # points tried in one battle
CANDIDATES_PER_ATTEMPT = 10                             # points per try, so the second try is a
                                                          # different part of the field
OPEN_GROUND_PX = 40                                      # radius used to measure the open ground
OPEN_GROUND_STEP = 2                                     # px between the samples of that measure
POINT_SHIFTS = [(0, 0), (50, 0), (-50, 0), (0, 50), (0, -50)]


@dataclass
class DeployPlan:
    point: Tuple[int, int]
    reason: str = ""


@dataclass
class AttackResult:
    status: str                          # "deployed", "no_deploy", "no_valid_plan", "no_troops", "battle_ended", "timeout"
    skips: int = 0                       # bases skipped with Next before deploying
    passes: int = 0
    taps: int = 0
    troops_left: Optional[int] = None
    plan: Optional[Dict[str, Any]] = None
    result_seen: bool = False
    result_path: Optional[str] = None
    outcome: Optional[str] = None        # victory | defeat | unknown, read from the result screen
    damage_pct: Optional[int] = None
    stars: Optional[int] = None
    haiku_calls: int = 0
    cost: float = 0.0
    notes: List[str] = field(default_factory=list)


def _red(r: int, g: int, b: int) -> bool:
    return r > 150 and g < 90 and b < 90


def _green(r: int, g: int, b: int) -> bool:
    return g > 170 and r < 140 and b < 110 and g > r + 40


def _fraction(img: Image.Image, box: Tuple[int, int, int, int], pred: Callable[[int, int, int], bool]) -> float:
    px = list(img.crop(box).convert("RGB").getdata())
    return sum(1 for r, g, b in px if pred(r, g, b)) / max(1, len(px))


def is_battle_screen(img: Image.Image) -> bool:
    """True when the red Surrender button is visible in its layout box."""
    return _fraction(img, SURRENDER_BOX, _red) > BATTLE_RED_FRACTION


def _orange(r: int, g: int, b: int) -> bool:
    return r > 210 and 110 < g < 200 and b < 90


def is_next_visible(img: Image.Image) -> bool:
    """True when the orange Next button (scouting, before the first deploy) is visible."""
    return _fraction(img, NEXT_BOX, _orange) > NEXT_ORANGE_FRACTION


def is_result_screen(img: Image.Image) -> bool:
    """True when the green Return Home button is visible in its layout box."""
    return _fraction(img, RESULT_BOX, _green) > RESULT_GREEN_FRACTION


def _dark(r: int, g: int, b: int) -> bool:
    return max(r, g, b) < 110


def is_battle_started(img: Image.Image) -> bool:
    """True when the battle is running, not still counting down.

    The dark "Overall Damage" panel appears in the bottom-right as soon as the battle starts. While the
    game is still scouting ("Battle starts in: 29s") that box holds the orange Next button and grass:
    measured on run 33caf775 (scouting 0.06-0.10, battle 0.21-1.00 of dark pixels, threshold 0.15).
    Taps during the countdown do not deploy a single troop, so the harness waits for this panel."""
    return _fraction(img, OVERALL_DAMAGE_BOX, _dark) > BATTLE_STARTED_DARK_FRACTION


def decode(b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(b64)))


# HUD boxes (model-image pixels) that a deploy tap must never land in: top-left loot, top-right resource
# bar, bottom-right "Overall Damage" panel. The Surrender box is checked with a 20 px margin.
HUD_BOXES = [(0, 0, 260, 140), (880, 0, 1170, 90), (940, 330, 1170, 430)]
# Deploy points must stay near the base: run 1db8e986 lost a battle on a line at the far-left edge (x=120),
# 500 px from the village. The village centre is about (620, 280) in every frame we have.
BASE_CENTRE = (620, 280)
BASE_RADIUS = 340


def _in_box(x: float, y: float, box: Tuple[int, int, int, int], margin: int = 0) -> bool:
    x0, y0, x1, y1 = box
    return x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin


def _in_deploy_band(x: float, y: float) -> bool:
    if not (0 <= x < 1170 and 0 <= y < 540):
        return False
    if y >= TRAY_Y or y <= HUD_TOP_Y:
        return False
    if _in_box(x, y, SURRENDER_BOX, margin=20):
        return False
    return not any(_in_box(x, y, b) for b in HUD_BOXES)


CLUMP_OFFSETS = [(0, 0), (10, 0), (-10, 0), (0, 10), (0, -10), (8, 8), (-8, 8), (8, -8), (-8, -8),
                 (20, 0), (-20, 0), (0, 20), (0, -20), (14, 14), (-14, 14), (14, -14), (-14, -14)]


def validate_point(p: Tuple[int, int]) -> Optional[str]:
    """Return None when the point is usable, else the reason it is not. The whole clump counts, not only
    the centre: a point next to the HUD would put half the taps on it."""
    for dx, dy in CLUMP_OFFSETS:
        x, y = p[0] + dx, p[1] + dy
        if not _in_deploy_band(x, y):
            return "point outside the deploy band"
        if ((x - BASE_CENTRE[0]) ** 2 + (y - BASE_CENTRE[1]) ** 2) ** 0.5 > BASE_RADIUS:
            return "point too far from the base"
    return None


def nudge_point(p: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    """A rejected point, moved toward the base centre 10 px at a time (up to 120 px): the first usable point,
    or None. Live run bc03b5a7/9f2ced10: 12 rejected points became usable after 10-80 px."""
    dx, dy = BASE_CENTRE[0] - p[0], BASE_CENTRE[1] - p[1]
    dist = (dx * dx + dy * dy) ** 0.5
    if dist == 0:
        return None
    for step in range(1, 13):
        q = (round(p[0] + dx / dist * 10 * step), round(p[1] + dy / dist * 10 * step))
        if validate_point(q) is None:
            return q
    return None


def clump_points(p: Tuple[int, int], n: int) -> List[Tuple[int, int]]:
    """n taps, all within CLUMP_R px of p (a fixed small pattern, repeated)."""
    return [(p[0] + CLUMP_OFFSETS[k % len(CLUMP_OFFSETS)][0], p[1] + CLUMP_OFFSETS[k % len(CLUMP_OFFSETS)][1])
            for k in range(n)]


def _grass(r: int, g: int, b: int) -> bool:
    """Open grass: yellow-green. Never grey, blue or brown.

    Measured on the battle frame of run 218ca432: open grass is (156, 155, 56) or (135, 134, 37),
    the roof the model planned is grey (96, 85, 82), a wall is grey-blue, the dirt under a building
    is brown (69, 51, 39) and the red no-deploy outlines of the game are red."""
    return g >= r * 0.88 and b <= g * 0.8 and g >= 55


def is_grass(img: Image.Image, x: int, y: int) -> bool:
    """True when the ground at (x, y) is open grass - the only ground a troop comes out on."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    px = img.load()
    total = 0
    good = 0
    for dy in range(-GRASS_PATCH, GRASS_PATCH + 1):
        for dx in range(-GRASS_PATCH, GRASS_PATCH + 1):
            xx, yy = x + dx, y + dy
            if not (0 <= xx < img.width and 0 <= yy < img.height):
                continue
            total += 1
            if _grass(*px[xx, yy]):
                good += 1
    return total > 0 and good >= GRASS_MIN * total


def _ring(r: int) -> List[Tuple[int, int]]:
    """The offsets of a square ring of radius r."""
    return [(0, -r), (r, 0), (0, r), (-r, 0), (r, r), (-r, r), (r, -r), (-r, -r),
            (r // 2, -r), (r // 2, r), (-r // 2, -r), (-r // 2, r),
            (r, r // 2), (r, -r // 2), (-r, r // 2), (-r, -r // 2)]


def grass_spot(img: Image.Image, x: int, y: int, radius: int = GRASS_SEARCH_PX) -> Optional[Tuple[int, int]]:
    """The nearest open grass around (x, y), or None when there is none.

    The model often points at the edge of a roof: the open grass is 20 px away. The search stays
    inside the deploy band, so it never lands on the HUD, on the Surrender button or outside the
    field (run 218ca432 planned the roof of the dark elixir storage at (700, 370): 79 taps, 0 %)."""
    if is_grass(img, x, y):
        return (x, y)
    for r in range(10, radius + 1, 10):
        for dx, dy in _ring(r):
            p = (x + dx, y + dy)
            if _in_deploy_band(p[0], p[1]) and is_grass(img, p[0], p[1]):
                return p
    return None


def ground_openness(img: Image.Image, x: int, y: int, radius: int = OPEN_GROUND_PX) -> float:
    """How open the ground around (x, y) is: the share of the pixels that are NOT open grass.

    0.0 is a wide empty field, 1.0 is a corner between four buildings. The game refuses a
    point that is wedged between the buildings of the base - the refused points of the runs of
    19:00 and 20:00 (2026-10-20) were all inside the base, the points the game took were all
    on the open field around it - so the roomiest ground is the one worth offering first.
    """
    if img.mode != "RGB":
        img = img.convert("RGB")
    px = img.load()
    total = 0
    good = 0
    for dy in range(-radius, radius + 1, OPEN_GROUND_STEP):
        for dx in range(-radius, radius + 1, OPEN_GROUND_STEP):
            xx, yy = x + dx, y + dy
            if not (0 <= xx < img.width and 0 <= yy < img.height):
                continue
            total += 1
            if _grass(*px[xx, yy]):
                good += 1
    if total == 0:
        return 1.0
    return 1.0 - good / total


def deploy_candidates(img: Image.Image, point: Tuple[int, int],
                      limit: int = CANDIDATE_TOTAL) -> List[Tuple[int, int]]:
    """The points to offer the game, best first.

    The plan point comes first - the model knows where the base is - and after it the roomiest
    open ground around it, so a plan the game refuses is followed by real open field instead of
    by the same patch of grass 50 px away. Measured on the runs of 19:00 and 20:00: the points
    the game took were 140 to 355 px from the Town Hall on the open field, the ones it refused
    were 33 to 185 px from it, between the buildings.
    """
    cands: List[Tuple[float, int, Tuple[int, int]]] = []
    for r in CANDIDATE_RINGS:
        offsets = [(0, 0)] if r == 0 else _ring(r)
        ring: List[Tuple[float, int, Tuple[int, int]]] = []
        for dx, dy in offsets:
            p = (point[0] + dx, point[1] + dy)
            if not _in_deploy_band(p[0], p[1]):
                continue
            if not is_grass(img, p[0], p[1]):
                continue
            ring.append((ground_openness(img, p[0], p[1]), r, p))
        if r == 0:
            cands.extend(ring)                # the plan point keeps its place at the front
            continue
        ring.sort(key=lambda t: t[0])        # the roomiest ground of this ring first
        cands.extend(ring[:CANDIDATES_PER_RING])
    return [t[2] for t in cands][:limit]


def count_changed(before: Image.Image, after: Image.Image, card: int = 0) -> bool:
    """True when the number on the army card moved: a troop left the tray.

    The badge of the card that was tapped is compared with itself. The digits are white on the blue
    card header, so a troop that left the tray moves the ink of the number. Measured on the frames
    of run 218ca432: while the game refuses the deploy the badge is pixel-identical (nothing moved
    in 150+ frames of a battle).

    Arming a card moves the badge too - the card rises a pixel or two and the other card dims - but
    that animation lasts 0.4 s and the picture that opens the comparison is taken after the card
    has settled (CARD_SETTLE_S), so the arming is outside the comparison and only a real count
    change can pass it.

    A card without a count (the King, a spell) has nothing to read: there is no signal, so the wave
    is not blocked on it."""
    if card >= len(COUNT_BOXES):
        return True
    box = COUNT_BOXES[card]
    if _badge_ink(before, box) < COUNT_MIN_INK and _badge_ink(after, box) < COUNT_MIN_INK:
        # No number is drawn on this card at all (the King, a spell, a card whose count the game
        # does not show): there is nothing to compare, so the wave is not blocked on it. Before
        # this, an empty badge box compared two empty boxes, always read as "no change" and
        # every deploy was reported as refused.
        return True
    a = before.crop(box).convert("RGB")
    b = after.crop(box).convert("RGB")
    diff = ImageChops.difference(a, b)
    red, green, blue = diff.split()
    peak = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    values = list(peak.getdata())
    return sum(1 for v in values if v > COUNT_DELTA) >= COUNT_CHANGED_PX


PLAN_SYSTEM = """You plan where to deploy troops in a Clash of Clans battle. The screenshot is 1170x540.
Reply with ONE JSON object only: {"point": [x, y], "skip": false, "reason": "<max 8 words>"}.
ALL troops are dropped in one clump at this ONE point, because each troop walks to the nearest building.
point = plain open green grass just OUTSIDE the base's outer wall, on the side of the base where the big
orange Town Hall or the gold/elixir storages stand. Two rules, both learned from real battles:
* NEVER a point inside the wall ring, between the buildings: the game refuses such a point silently
  and not one troop comes out - the whole army is lost with 0 % damage.
* NEVER far out in the open field: the troops would walk the whole field under fire before they
  arrive. Aim for the grass right beside the wall, 10 to 50 px outside it, so the troops reach the
  buildings in seconds - and if the wall has a gap on that side, drop the army at the gap: the
  troops walk straight in. If the wall is closed there, pick another side.
Stay FARTHEST from the cannon, archer tower, mortar and inferno tower.
A troop only comes out on plain grass: never on a wall, a roof, a road or the brown path (a tap
there deploys nothing at all).
Not on the red button (bottom-left), the Overall Damage panel (bottom-right), the top bars, the troop tray
or the screen edge.
skip = true (point may be null) when every building sits inside a closed wall ring, or defenses guard every
side: the base is not worth attacking and Next is tapped for another one."""

COUNT_SYSTEM = """Read the troop counts in the troop tray of this Clash of Clans battle screenshot: the small
number on each troop card along the bottom, left to right (e.g. x12). Reply with ONE JSON object only:
{"counts": [<integer>, ...]}, one number per troop card, left to right. If no number is visible reply
{"counts": null}."""


RESULT_SYSTEM = """This is the end-of-battle screen of Clash of Clans. Reply with ONE JSON object only:
{"outcome": "victory" | "defeat" | "unknown", "damage_pct": <integer or null>, "stars": <0-3 or null>}.
outcome is the banner text (Victory or Defeat). damage_pct is the Total damage / Overall Damage percentage.
stars is the number of gold stars shown. Use null when a value is not visible."""


def _parse_json(txt: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
    except ValueError:
        return None


def plan_deploy(ask: Callable[[str, str, str], Tuple[str, Optional[int], Optional[int]]], b64: str,
                result: AttackResult, attempts: int = 2, hint: str = "") -> Optional[DeployPlan]:
    """Ask for a deploy point; if the code rejects it, ask once more and say why (live run fbf1c13c:
    three of four first lines were rejected, one on the top HUD, one on the damage panel, one too far).
    ``hint`` says what went wrong with the last point, so the model can pick another one.
    Returns DeployPlan(point=(-1, -1), reason="skip") when the model says the base is not worth it."""
    text = "Where do I deploy? JSON only."
    if hint:
        text += " " + hint
    for _ in range(attempts):
        reply, tin, tout = ask(PLAN_SYSTEM, b64, text)
        result.haiku_calls += 1
        a = _parse_json(reply)
        if a and a.get("skip") is True:
            return DeployPlan(point=(-1, -1), reason="skip: " + str(a.get("reason", ""))[:180])
        pt = a.get("point") if a else None
        if not isinstance(pt, list) or len(pt) != 2 or not all(isinstance(v, (int, float)) for v in pt):
            result.notes.append("plan: unparseable reply")
            text = "Your reply was not valid JSON. Reply with ONE JSON object only, as instructed."
            continue
        p = (int(pt[0]), int(pt[1]))
        why = validate_point(p)
        if why is None:
            candidate = p
        else:
            moved = nudge_point(p)
            if moved is None:
                result.notes.append(f"plan rejected: {why} {p}")
                text = (f"Your point {p} was rejected: {why}. Choose another point: plain green grass 60 to 200 px "
                        f"from the big orange Town Hall, on the Town Hall side of the base, away from the walls - "
                        f"not on a wall, a roof, a road or the brown path, not at the top of the screen and not on "
                        f"the right-hand panel.")
                continue
            result.notes.append(f"plan nudged: {why} {p} -> {moved}")
            candidate = moved
        # The point must also be open grass: the game refuses a tap on a roof, a wall or a path
        # without saying anything (run 218ca432 planned (700, 370), the roof of the dark elixir
        # storage, and sent 79 taps there: 0 % damage).
        spot = grass_spot(decode(b64), candidate[0], candidate[1])
        if spot is None:
            result.notes.append(f"plan on no grass: {candidate}")
            text = (f"Your point {candidate} is not on open grass - it is a building, a wall or a path, and "
                    f"the game drops no troop there. Pick a point on plain green grass, 60 to 200 px from "
                    f"the big orange Town Hall, on the Town Hall side of the base.")
            continue
        if spot != candidate:
            result.notes.append(f"plan moved {candidate} -> {spot}: the point was on a building, the "
                                "open grass is next to it")
        return DeployPlan(point=spot, reason=str(a.get("reason", ""))[:200])
    return None


def read_counts(ask: Callable[[str, str, str], Tuple[str, Optional[int], Optional[int]]], b64: str,
                result: AttackResult) -> Optional[List[int]]:
    """Troops left on each card, left to right; None when the model could not read them."""
    reply, tin, tout = ask(COUNT_SYSTEM, b64, "How many troops are left on each card? JSON only.")
    result.haiku_calls += 1
    a = _parse_json(reply)
    c = a.get("counts") if a else None
    if not isinstance(c, list) or not c or not all(isinstance(v, (int, float)) for v in c):
        return None
    return [max(0, int(v)) for v in c][:len(CARD_TAPS)]


def read_result(ask: Callable[[str, str, str], Tuple[str, Optional[int], Optional[int]]], b64: str,
                res: AttackResult) -> None:
    """One model call on the result screen: outcome, damage % and stars for the report."""
    reply, tin, tout = ask(RESULT_SYSTEM, b64, "What is the battle result? JSON only.")
    res.haiku_calls += 1
    a = _parse_json(reply)
    if not a:
        res.outcome = "unknown"
        res.notes.append("result: unparseable reply")
        return
    res.outcome = str(a.get("outcome") or "unknown")
    res.damage_pct = int(a["damage_pct"]) if isinstance(a.get("damage_pct"), (int, float)) else None
    res.stars = int(a["stars"]) if isinstance(a.get("stars"), (int, float)) else None


def _badge_ink(img: Image.Image, box: Tuple[int, int, int, int]) -> int:
    """The white pixels of a count badge: the digits of the number on the card."""
    a = img.crop(box).convert("RGB")
    return sum(1 for r, g, b in a.getdata() if r > 200 and g > 200 and b > 200)


def _tap_clump(dev: Any, res: AttackResult, point: Tuple[int, int], n: int,
               sleep: Callable[[float], None], start: int = 0) -> None:
    """n deploy taps in the clump around the point, continuing the pattern at ``start``."""
    for x, y in clump_points(point, n + start)[start:]:
        d = to_device({"x": x, "y": y})
        dev.tap(d["x"], d["y"])
        res.taps += 1
        sleep(TAP_GAP_S)


def _try_deploy_at(dev: Any, res: AttackResult, point: Tuple[int, int], n: int, index: int,
                   sleep: Callable[[float], None], card: int = 0) -> Optional[Tuple[int, int]]:
    """Tap the clump at one point and tell whether the troops came out.

    Two signals, both from the picture, no model call:
      * the ground must be open grass - the game refuses a tap on a roof, a wall or a path and
        says nothing (run 218ca432 planned the roof of the dark elixir storage: 79 taps, 0 %);
      * the count badge of the card that was tapped must move - a troop that left the tray changes
        its number.
    Returns the point where the troops came out, or None when the game refused the point."""
    before_b64, _ = dev.shot(index)
    before = decode(before_b64)
    spot = grass_spot(before, point[0], point[1])
    if spot is None:
        res.notes.append(f"deploy: no open grass at {point}, the game would refuse the tap")
        return None
    _tap_clump(dev, res, spot, n, sleep)
    after_b64, _ = dev.shot(index)
    if not count_changed(before, decode(after_b64), card):
        return None
    return spot


def _wait_for_battle_start(dev: Any, res: AttackResult, index: int, sleep: Callable[[float], None],
                           timeout_s: float = PRE_BATTLE_TIMEOUT_S) -> str:
    """Wait until the battle is running (the Overall Damage panel is up). Taps during the scouting
    countdown deploy nothing, so the first deploy wave would be lost (run 33caf775 started its
    deploy on a "Battle starts in: 29s" frame).

    "started": the battle is running, deploy now. "ended": the battle is over, read the result.
    "unknown": the panel never showed up (a mode without it): deploy anyway, that is what the
    harness did before."""
    waited = 0.0
    while waited < timeout_s:
        img_b64, _ = dev.shot(index)
        img = decode(img_b64)
        if is_battle_started(img):
            return "started"
        if is_result_screen(img):
            res.notes.append("battle ended before it started")
            return "ended"
        sleep(PRE_BATTLE_POLL_S)
        waited += PRE_BATTLE_POLL_S
    res.notes.append(f"battle not started after {int(timeout_s)} s: deploying anyway")
    return "unknown"


def _wait_for_next_base(dev: Any, res: AttackResult, index: int, sleep: Callable[[float], None],
                        b64: str = "", timeout_s: float = NEXT_BASE_TIMEOUT_S) -> str:
    """After Next, the next village loads in a second or two: the orange Next button is gone while the
    game swaps the base. Planning on the old frame puts the deploy point on the wrong village."""
    waited = 0.0
    while waited < timeout_s:
        sleep(1.5)
        waited += 1.5
        new_b64, _ = dev.shot(index)
        if is_next_visible(decode(new_b64)):
            return new_b64
        b64 = new_b64
    res.notes.append("next base did not load in time")
    return b64


def run_attack(dev: Any, ask: Callable[[str, str, str], Tuple[str, Optional[int], Optional[int]]],
               meter: Any, b64: str, index: int, sleep: Callable[[float], None] = time.sleep,
               timeout_s: float = RESULT_TIMEOUT_S) -> AttackResult:
    """Fight one battle. ``dev`` has shot(index) -> (b64, path), tap(x, y) in device pixels.

    Every model call is billed through ``meter`` (RunMeter.add); a call that returns no usage is charged
    its worst case, as in ``play``. The shot indexes are the step index, so report files do not collide.

    One deploy wave per card, one read of the troop counts: the old loop re-read the tray after every
    pass and the number never reached 0 (the troops were dying, the tray count does not grow back), so
    it tapped 208 times for a 70-troop army (run 33caf775) and the battles ended at 12-29 % damage.
    """
    res = AttackResult(status="no_troops")

    def billed(system: str, image_b64: str, text: str) -> Tuple[str, Optional[int], Optional[int]]:
        reply, tin, tout = ask(system, image_b64, text)
        if tin is None or tout is None:
            res.cost += meter.charge_failure()
            return reply, None, None
        res.cost += meter.add(tin, tout)
        return reply, tin, tout

    plan = plan_deploy(billed, b64, res)
    while plan is not None and plan.reason.startswith("skip") and res.skips < MAX_SKIPS:
        if not is_next_visible(decode(b64)):
            res.notes.append("skip asked but Next is not visible: attacking this base")
            plan = None
            break
        d = to_device({"x": NEXT_TAP[0], "y": NEXT_TAP[1]})
        dev.tap(d["x"], d["y"])
        res.skips += 1
        res.notes.append(f"base skipped with Next ({plan.reason})")
        b64 = _wait_for_next_base(dev, res, index, sleep, b64)
        plan = plan_deploy(billed, b64, res)
    if plan is not None and plan.reason.startswith("skip"):
        res.notes.append(f"skip limit {MAX_SKIPS} reached: asking for a point on this base")
        plan = plan_deploy(billed, b64, res, attempts=1)
        if plan is not None and plan.reason.startswith("skip"):
            plan = None
    if plan is None:
        res.status = "no_valid_plan"
        res.notes.append("waiting out the timer, no troops deployed")
        return _wait_for_result(dev, res, index, sleep, timeout_s, billed)
    res.plan = asdict(plan)

    # Read the tray on the scouting frame: its numbers are big and static, while the battle screen
    # is busy and the model reads them wrong (run 33caf775: 59 Barbarians read as 59, then 59 again
    # on the battle screen where the card said 21 - the deploy ran on and tapped 208 times).
    counts = read_counts(billed, b64, res)
    res.troops_left = sum(counts) if counts is not None else None
    counts = (counts[:MAX_CARDS] if counts is not None else [TAPS_PER_PASS])

    if _wait_for_battle_start(dev, res, index, sleep) == "ended":
        res.status = "battle_ended"
        return _wait_for_result(dev, res, index, sleep, timeout_s, billed)

    army = sum(counts)
    # The battle camera does not move when the battle starts (measured on run 3e0ca7e8: the
    # scouting frame and the battle frame have the same geometry), so the point planned on the
    # scouting frame is the point the taps are made on.
    #
    # The points the game is offered, best first: the plan point, then the roomiest open ground
    # around it. The game refuses a point silently and the refusal is about the ground, so the
    # harness reads the picture and moves on to the next point. NO model call happens here: the
    # planning call of the runs of 19:00 and 20:00 took 170 to 260 s, longer than a battle
    # (3 min), so the model could never re-plan in time - the army was lost while it thought.
    candidates = deploy_candidates(decode(b64), plan.point)
    for attempt in range(MAX_DEPLOY_ATTEMPTS):
        waves = 0
        landed = False
        use_point = plan.point
        pool = candidates[attempt * CANDIDATES_PER_ATTEMPT:(attempt + 1) * CANDIDATES_PER_ATTEMPT]
        for k, c in enumerate(counts):
            if c <= 0 or res.taps >= MAX_TOTAL_TAPS:
                continue
            if waves == 1:
                sleep(WAVE_GAP_S)          # the tanks are walking: let them pull the defenses first
            budget = min(c, MAX_TAPS_PER_CARD, MAX_TOTAL_TAPS - res.taps)
            sent = 0                     # troops that really left the tray
            card = to_device({"x": CARD_TAPS[k][0], "y": CARD_TAPS[k][1]})
            dev.tap(card["x"], card["y"])
            sleep(CARD_SETTLE_S)
            if landed:
                # the game took the taps of the first wave: send the rest of this card
                rest = min(budget - sent, MAX_TOTAL_TAPS - res.taps)
                if rest > 0:
                    _tap_clump(dev, res, use_point, rest, sleep)
                    sent = budget
                waves += 1
                continue
            # The game refused the point in three of six battles of run a5e2ce36 (140 taps, 71
            # troops still in the tray, 0 % damage) and in all three battles of run 218ca432 (79
            # taps, the count stayed at x59). The refusal is silent, so the harness reads the
            # picture: the ground must be open grass and the count badge of the card must move.
            # When the point is refused, the next point of the neighbourhood is tried - the
            # picture decides, no model call, so no minutes are lost before the next try.
            for p in pool:
                if sent >= budget or res.taps >= MAX_TOTAL_TAPS:
                    break
                n = min(VERIFY_TAPS if p == plan.point else FALLBACK_TAPS, budget - sent)
                spot = _try_deploy_at(dev, res, p, n, index, sleep, k)
                if spot is None:
                    res.notes.append(f"deploy {attempt + 1}: {n} taps at {p} deployed no troop, the game "
                                     f"refused the point (the count badge did not move)")
                    sleep(RETRY_PAUSE_S)
                    continue
                landed = True
                use_point = spot
                sent += n
                res.notes.append(f"deploy {attempt + 1}: the army came out at {spot}")
                rest = min(budget - sent, MAX_TOTAL_TAPS - res.taps)
                if rest > 0:
                    _tap_clump(dev, res, spot, rest, sleep, start=n)
                    sent = budget
                waves += 1
                break
            if not landed:
                break
        res.passes += 1
        img_b64, _ = dev.shot(index)
        left = read_counts(billed, img_b64, res)      # for the report; the decision is the picture
        if left is None:
            res.troops_left = None
        else:
            res.troops_left = sum(left)
            if not landed and sum(left) <= DEPLOY_CHECK_RATIO * army:
                # the picture missed the deploy but the tray says the army left it: believe the tray
                landed = True
        if landed:
            res.status = "deployed" if res.taps else "no_troops"
            break                         # the troops are on the field
        res.status = "no_deploy"
        res.notes.append(f"deploy {attempt + 1}: the game refused every point of the clump, "
                         "no troop came out")
        if attempt + 1 >= MAX_DEPLOY_ATTEMPTS:
            break
        # The second try takes the next points of the list: another part of the field, without
        # waiting for a model that would need longer than the battle itself.
    if not res.status or res.status == "no_troops":
        res.status = "deployed" if res.taps else "no_troops"
    return _wait_for_result(dev, res, index, sleep, timeout_s, billed)


def _wait_for_result(dev: Any, res: AttackResult, index: int, sleep: Callable[[float], None],
                     timeout_s: float, billed: Callable[[str, str, str], Tuple[str, Optional[int], Optional[int]]]
                     ) -> AttackResult:
    """Poll screenshots (no model call) until Return Home is visible, then tap it."""
    waited = 0.0
    while waited < timeout_s:
        img_b64, shot_path = dev.shot(index)
        if is_result_screen(decode(img_b64)):
            res.result_seen = True
            res.result_path = shot_path
            read_result(billed, img_b64, res)
            d = to_device({"x": RESULT_TAP[0], "y": RESULT_TAP[1]})
            dev.tap(d["x"], d["y"])
            return res
        sleep(POLL_S)
        waited += POLL_S
    res.status = "timeout" if res.status == "deployed" else res.status
    res.notes.append(f"no result screen after {int(timeout_s)} s")
    return res
