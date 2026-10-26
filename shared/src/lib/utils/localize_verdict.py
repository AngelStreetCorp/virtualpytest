"""Localize v3 verdict: ONE answer to "where are we?" for the Localize button, the monitor
overlay and the MCP `localize` tool (TASK-104).

Shape: {kind, node_id?, label, confidence, evidence}, kind in VERDICT_KINDS.

Cascade order (cheapest and most certain first; the first step that answers wins):
  1. signal  -- black screen / no signal (image_helpers.classify_special_state)
  2. live    -- full-frame motion across every frame pair; node_id = the tree's live node
  3. node    -- identify_screen (fingerprint + title + Jev confirm), unchanged; a tie the
                matcher keeps is read the way every caller of `candidates` reads it: the
                first candidate, with the others in evidence.tied
  4. overlay -- screen_state_cv.overlay_plate: a popup / keyboard / notification on a still
                frame; node_id = the node matched UNDER the plate (ImageHelpers.match_under_plate).
                On an abstain, and ALSO over a node match whose regions under the plate do not
                match that node (the plate is new, not part of the node's own screen: a popup
                leaves enough of the page around it for the matcher to name the page; TASK-110)
  5. known_screen -- on an abstain, TASK-84 screen memory (screen_fingerprints) of this device
  5b. live   -- on an abstain, a slow live scene: every pair of the window moved, none still,
                none a band / box (a presenter reads 'minor', not 'full'), and the tree has a
                live node. A trailer on a menu moves as a box / band, so it stays not live.
  6. unknown

`after_match` runs steps 4-5b after the matcher; the button, the monitor and the benchmark call it.

The functions here are pure (no device, no DB) so the order is unit-tested once and the
executor and the standalone monitor process both import it without the navigation stack.

"Live" is the same signal in both callers, measured over the window each one has: the button
grabs MOTION_FRAMES distinct frames and needs every pair 'full'; the monitor already holds a
fused, debounced motion state per frame (capture_monitor._fuse_motion_state, a sustain window
longer than the button's ~1 s) and gates on it (monitor_localize.gate_motion_decision).
"""
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

VERDICT_KINDS = ('signal', 'live', 'node', 'overlay', 'known_screen', 'app', 'unknown')

# A node is THE live node of its tree when it is named `live` (owner decision 2026-10-19:
# one name convention instead of a per-node flag). Call the live-TV screen `live` in every tree.
LIVE_NODE_NAME = 'live'

LIVE_LABEL = 'Live video'

# The overlay step reads a STILL frame only: on moving content a lit subject on a dark surround
# looks like a popup plate (a close-up film scene on stb_tv). Motion pct above this skips it.
OVERLAY_STILL_PCT = 1.0

# Overlays that answer "where are we" (a tooltip is a hint on the page, not a different place).
OVERLAY_KINDS = ('popup', 'keyboard', 'notification')
OVERLAY_LABELS = {'popup': 'Popup', 'keyboard': 'Keyboard', 'notification': 'Notification'}

# Slow live (step 5b): a pair counts as moving when its kind is one of these; every pair must move,
# the quietest by at least SLOW_LIVE_MIN_PCT. Live presenter scenes measured 2.8-5.3 % on stb3.
SLOW_LIVE_PAIR_KINDS = ('minor', 'full')
SLOW_LIVE_MIN_PCT = 2.0

# Localize grabs this many DISTINCT capture files, at least MOTION_GAP_S apart, to measure
# motion itself (the monitor's per-frame JSON can be a second old and is absent on devices
# without a monitor). Captures run at 5 fps, 2 fps on lean profiles: a fixed sleep could return
# the same file twice, so the grab polls for a new file and gives up at MOTION_DEADLINE_S.
MOTION_FRAMES = 3
MOTION_GAP_S = 0.3
# Fresh windows (and the pause before each) tried on an abstain in a tree with a live node: a channel zap / banner.
MOTION_RETRY_GAP_S = 0.8
MOTION_RETRIES = 2
MOTION_POLL_S = 0.1
MOTION_DEADLINE_S = 2.5
# Thumbnail size the monitor's motion thresholds were tuned on (detector.py, 320x180 grey).
MOTION_SIZE = (320, 180)


def cell_mask(diff, motion_thr=12, cell_thr=0.04, grid=4):
    """grid x grid bool array: True where more than `cell_thr` of the cell's pixels differ by more
    than `motion_thr` — the changed cells motion_shape counts."""
    h, w = diff.shape[:2]
    m = diff > motion_thr
    ys = np.linspace(0, h, grid + 1).astype(int)
    xs = np.linspace(0, w, grid + 1).astype(int)
    cell = np.zeros((grid, grid), dtype=bool)
    for r in range(grid):
        for c in range(grid):
            sub = m[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
            if sub.size and sub.mean() > cell_thr:
                cell[r, c] = True
    return cell


def _changed_bbox(m, cell, grid):
    """[x0, y0, x1, y1] frame fractions of the changed pixels of `m` inside the changed cells of
    `cell` (see motion_shape), or None when no cell changed."""
    if not cell.any():
        return None
    h, w = m.shape[:2]
    ys = np.linspace(0, h, grid + 1).astype(int)
    xs = np.linspace(0, w, grid + 1).astype(int)
    x0, y0, x1, y1 = w, h, 0, 0
    for r, c in zip(*np.nonzero(cell)):
        py, px = np.nonzero(m[ys[r]:ys[r + 1], xs[c]:xs[c + 1]])
        x0, x1 = min(x0, xs[c] + int(px.min())), max(x1, xs[c] + int(px.max()) + 1)
        y0, y1 = min(y0, ys[r] + int(py.min())), max(y1, ys[r] + int(py.max()) + 1)
    return [round(x0 / w, 3), round(y0 / h, 3), round(x1 / w, 3), round(y1 / h, 3)]


def motion_shape(diff, motion_thr=12, cell_thr=0.04, grid=4):
    """Coarse SPATIAL classification of a frame-to-frame diff — the same motion signal freeze
    detection already produces. Distinguishes full-frame motion (live TV) from a horizontal band
    (carousel) or a compact box (picture-in-picture), so the monitor can tell "live motion" apart
    from a moving UI. Pre-localize (raw shape only); capture_monitor fuses this with the localize
    result + hysteresis to emit the final motion state. ~sub-ms on a 320x180 thumbnail.

    Returns {kind, pct, cells, rows, cols, mask, bbox}:
      mask : the changed cells as a grid*grid-bit int, row-major (bit r*grid+c; bit 0 = top-left,
             bit 15 = bottom-right on the 4x4 grid) — WHERE the frame moved
      bbox : [x0, y0, x1, y1] as frame fractions (0..1), the changed pixels inside the changed
             cells (scattered noise outside them is ignored), or None when no cell changed
    kind:
      static : almost no change (freeze / still UI)
      full   : motion distributed across the frame  -> live candidate
      band   : wide + short horizontal strip        -> carousel candidate
      box    : compact localized region             -> picture-in-picture candidate
      minor  : some motion, no clear shape
    """
    m = diff > motion_thr
    pct = round(float(m.mean()) * 100.0, 1)
    cell = cell_mask(diff, motion_thr, cell_thr, grid)
    cells = int(cell.sum())
    rows = int(cell.any(axis=1).sum())
    cols = int(cell.any(axis=0).sum())
    mask = 0
    for r, c in zip(*np.nonzero(cell)):
        mask |= 1 << int(r * grid + c)
    bbox = _changed_bbox(m, cell, grid)
    if pct < 1.0:
        kind = 'static'
    elif cells >= (grid * grid) // 2 and rows >= 3 and cols >= 3:
        kind = 'full'
    elif rows <= 2 and cols >= 3:
        kind = 'band'
    elif rows <= 2 and cols <= 2 and cells == rows * cols and cells <= 3:
        kind = 'box'                         # one SOLID compact block (not scattered spots)
    else:
        kind = 'minor'
    return {'kind': kind, 'pct': pct, 'cells': cells, 'rows': rows, 'cols': cols, 'mask': mask, 'bbox': bbox}


def measure_motion(frames_bgr: List[Any]) -> Optional[Dict[str, Any]]:
    """Motion across consecutive frames: {kind, pct, pairs:[kind...]}, or None under two frames.

    kind is 'full' when at least one pair is full-frame motion, NO pair is still and the LAST pair
    still moves like video (minor / full, at least SLOW_LIVE_MIN_PCT): live video keeps moving (a
    slow scene gives full + minor over ~1 s, measured on stb_tv), while a zap, a fade or a screen
    change ends on a still pair, or on the new screen's own box / band (a zap out of live onto a
    menu with a hero trailer: full 44 % then box 1 % on stb3). Otherwise kind/pct are those of the
    pair that moved most, a full pair reported as 'change'.
    """
    import cv2
    # INTER_AREA averages like the ffmpeg scaler that makes the monitor's thumbnails; a
    # bilinear shrink drops pixels and lowers pct.
    grays = [cv2.cvtColor(cv2.resize(f, MOTION_SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
             for f in frames_bgr if f is not None and getattr(f, 'size', 0)]
    if len(grays) < 2:
        return None
    shapes = [motion_shape(cv2.absdiff(a, b)) for a, b in zip(grays, grays[1:])]
    kinds = [s['kind'] for s in shapes]
    pcts = [s['pct'] for s in shapes]
    if ('full' in kinds and 'static' not in kinds
            and kinds[-1] in SLOW_LIVE_PAIR_KINDS and pcts[-1] >= SLOW_LIVE_MIN_PCT):
        return {'kind': 'full', 'pct': min(pcts), 'pairs': kinds, 'pair_pcts': pcts}
    top = max(shapes, key=lambda s: s['pct'])
    return {'kind': 'change' if top['kind'] == 'full' else top['kind'], 'pct': top['pct'], 'pairs': kinds,
            'pair_pcts': pcts}


def grab_distinct_frames(take_screenshot, imread, sleep, clock,
                         count: int = MOTION_FRAMES) -> List[tuple]:
    """Up to `count` (path, frame) pairs from distinct capture files, MOTION_GAP_S or more apart.

    `take_screenshot` returns the newest capture's path; its basename names the capture file,
    so a new basename is a new frame. Polls every MOTION_POLL_S, stops at MOTION_DEADLINE_S
    with what it has (one frame when the capture is stuck: motion is then unmeasured).
    """
    import os
    out: List[tuple] = []
    seen = set()
    deadline = clock() + MOTION_DEADLINE_S
    while len(out) < count:
        path = take_screenshot()
        name = os.path.basename(path) if path else None
        if name and name not in seen:
            frame = imread(path)
            if frame is not None:
                seen.add(name)
                out.append((path, frame))
                if len(out) == count:
                    break
                if clock() + MOTION_GAP_S > deadline:
                    break
                sleep(MOTION_GAP_S)
                continue
        if clock() + MOTION_POLL_S > deadline or (out and path is None):
            break
        sleep(MOTION_POLL_S)
    return out


def common_signal_state(states: List[Optional[str]]) -> Optional[str]:
    """The signal state when EVERY frame shows the same one: a zap or a fade ends on black."""
    return states[0] if states and states[0] and all(s == states[0] for s in states) else None


def is_live_node(label: Optional[str]) -> bool:
    return (label or '').strip().lower() == LIVE_NODE_NAME


def find_live_node(nodes: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """First {node_id, label} named `live` -> {node_id, label}."""
    for n in nodes:
        if is_live_node(n.get('label')):
            return {'node_id': n.get('node_id'), 'label': n.get('label') or n.get('node_id')}
    return None


def signal_verdict(state: str, label: Optional[str] = None) -> Dict[str, Any]:
    return {'kind': 'signal', 'node_id': None, 'label': label or state, 'confidence': 1.0,
            'evidence': {'state': state}}


def live_verdict(motion: Optional[Dict[str, Any]], live_node: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {'kind': 'live', 'node_id': (live_node or {}).get('node_id'),
            'label': (live_node or {}).get('label') or LIVE_LABEL, 'confidence': 1.0,
            'evidence': {'motion': motion}}


def unknown_verdict(evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {'kind': 'unknown', 'node_id': None, 'label': 'Unknown', 'confidence': 0.0,
            'evidence': evidence or {}}


def verdict_before_match(state: Optional[str], state_label: Optional[str],
                         motion: Optional[Dict[str, Any]],
                         live_node: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Steps 1-2: a signal state, then full-frame motion. None = run the fingerprint matcher."""
    if state:
        return signal_verdict(state, state_label)
    if (motion or {}).get('kind') == 'full':
        return live_verdict(motion, live_node)
    return None


def verdict_from_match(result: Dict[str, Any]) -> Dict[str, Any]:
    """Steps 3 and 6 from an identify_screen result (later phases slot overlay/known_screen
    in before the unknown). A `state` on an abstain is still a signal verdict. Several
    candidates are a tie the matcher kept: the verdict reads it as every caller of
    `candidates` does (the popover, localize_check, goto) — the first one — and lists the
    others in evidence.tied, so a reader that must not guess can tell."""
    cands = result.get('candidates') or []
    if cands:
        top = cands[0]
        evidence = {'excluded': result.get('excluded_count', 0), 'total': result.get('total', 0)}
        if len(cands) > 1:
            evidence['tied'] = [c.get('node_id') for c in cands[1:]]
        return {'kind': 'node', 'node_id': top.get('node_id'), 'label': top.get('label'),
                'confidence': top.get('confidence', 0.0), 'evidence': evidence}
    if result.get('state'):
        return signal_verdict(result['state'], result.get('state_label'))
    evidence = {'excluded': result.get('excluded_count', 0), 'total': result.get('total', 0)}
    if result.get('reason'):
        evidence['reason'] = result['reason']
    return unknown_verdict(evidence)


def overlay_verdict(overlay: str, box, under: Optional[Dict[str, Any]],
                    evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """kind=overlay; node_id / label name the screen under the plate when one matched."""
    under = under or {}
    name = OVERLAY_LABELS.get(overlay, overlay)
    node_id = under.get('node_id')
    return {'kind': 'overlay', 'node_id': node_id,
            'label': f"{name} over {under.get('label')}" if node_id else name,
            'confidence': under.get('confidence', 0.0) if node_id else 1.0,
            'evidence': {**(evidence or {}), 'overlay': overlay, 'plate': list(box) if box else None,
                         'under': {k: under.get(k) for k in ('node_id', 'label', 'dist', 'regions', 'tied')}}}


def known_screen_verdict(row: Dict[str, Any], dist: int) -> Dict[str, Any]:
    """kind=known_screen from a TASK-84 screen_fingerprints row: its label, else what memory knows.

    A row with no label and no verdict word is UNNAMED: `evidence.named` is False and the label is empty,
    so every surface can show nothing for it (BUG-0662); no "Known screen (unknown, seen Nx)" text is built."""
    seen = int(row.get('seen_count') or 0)
    verdict = row.get('verdict')
    named = bool(row.get('label')) or (bool(verdict) and verdict != 'unknown')
    label = row.get('label') or (f"Known screen ({verdict}, seen {seen}x)" if named else '')
    return {'kind': 'known_screen', 'node_id': None, 'label': label,
            'confidence': round(max(0.0, 1.0 - dist / 256.0), 3),
            'evidence': {'screen_id': row.get('id'), 'dist': dist, 'verdict': verdict, 'named': named,
                         'seen_count': seen, 'scope': row.get('scope')}}


def is_slow_live(motion: Optional[Dict[str, Any]]) -> bool:
    """Every pair of a measured window moved (minor / full), the quietest by SLOW_LIVE_MIN_PCT.
    Needs the per-pair kinds (`pairs`, measure_motion); a single pct (the monitor) never qualifies:
    the monitor reads slow live from its own fused, longer window before the matcher runs."""
    pairs = (motion or {}).get('pairs') or []
    pcts = (motion or {}).get('pair_pcts') or [(motion or {}).get('pct') or 0.0]
    return (len(pairs) >= 2 and all(p in SLOW_LIVE_PAIR_KINDS for p in pairs)
            and min(float(p) for p in pcts) >= SLOW_LIVE_MIN_PCT)


def after_abstain(verdict: Dict[str, Any], img, node_fps: List[Dict[str, Any]], helpers,
                  known_lookup=None, motion: Optional[Dict[str, Any]] = None,
                  live_node: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Steps 4-5b on an `unknown` verdict: an overlay plate (with the node under it) on a still
    frame, then screen memory, then a slow live scene when the tree has a live node.
    `known_lookup(img)` returns (row, dist) or None; `motion` is the caller's motion measure
    ({pct, pairs?}); above OVERLAY_STILL_PCT the overlay step is skipped. Any other verdict
    passes through."""
    if verdict.get('kind') != 'unknown':
        return verdict
    from shared.src.lib.ai.screen_state_cv import overlay_plate
    moving = float((motion or {}).get('pct') or 0.0) > OVERLAY_STILL_PCT
    overlay, box = overlay_plate(img) if not moving else ('skipped', None)
    if overlay in OVERLAY_KINDS:
        under = helpers.match_under_plate(img, box, node_fps) if box and node_fps else None
        return overlay_verdict(overlay, box, under, verdict.get('evidence'))
    if live_node and is_slow_live(motion):
        return live_verdict(motion, live_node)
    found = known_lookup(img) if known_lookup else None
    if found:
        return known_screen_verdict(*found)
    return verdict


def plate_over_node(verdict: Dict[str, Any], img, node_fps: List[Dict[str, Any]], helpers,
                    motion: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Step 4 over a `node` verdict: a popup / keyboard / notification plate on a still frame whose
    covered regions do not match the named node (ImageHelpers.plate_in_node) is drawn OVER the
    screen: kind=overlay, the screen under it named by match_under_plate. A plate the node's own
    screenshot carries (a search page's keyboard) keeps the node verdict."""
    if verdict.get('kind') != 'node' or float((motion or {}).get('pct') or 0.0) > OVERLAY_STILL_PCT:
        return verdict
    from shared.src.lib.ai.screen_state_cv import overlay_plate
    overlay, box = overlay_plate(img)
    if overlay not in OVERLAY_KINDS or not box:
        return verdict
    fp = next((n.get('fingerprint') for n in node_fps if n.get('node_id') == verdict.get('node_id')), None)
    if not fp or helpers.plate_in_node(img, box, fp):
        return verdict
    under = helpers.match_under_plate(img, box, node_fps) if node_fps else None
    return overlay_verdict(overlay, box, under, {**(verdict.get('evidence') or {}), 'matched': verdict.get('node_id')})


def after_match(verdict: Dict[str, Any], img, node_fps: List[Dict[str, Any]], helpers,
                known_lookup=None, motion: Optional[Dict[str, Any]] = None,
                live_node: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Steps 4-5b after the matcher's verdict: a plate over a node match, else the abstain steps."""
    if verdict.get('kind') == 'node':
        return plate_over_node(verdict, img, node_fps, helpers, motion)
    return after_abstain(verdict, img, node_fps, helpers, known_lookup, motion=motion, live_node=live_node)
