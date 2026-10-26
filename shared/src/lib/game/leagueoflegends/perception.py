"""TASK-132: what the Garen bot sees in a game screenshot (read-only, pure numpy).

Calibrated on 2026-10-18 against real 1920x1200 frames of a Practice Tool game on ``vpt-windows``:
health bars are 1-4 px high; the fill is (197, 89, 89) red for enemies, blue for allies; the empty part is near
black (12, 13, 14). Minion bars are about 62 px wide, champion bars about 125 px, turret bars about 250 px.
The camera is locked on the player, who stands at about (868, 545).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

PLAYER_XY = (868, 545)  # champion feet on screen with the camera locked (Y)
HUD_Y = 1050  # nothing a bot clicks on lies below this row (bottom HUD) ...
MINION_BAR_MAX, CHAMPION_BAR_MAX = 80, 160  # red-run width limits (pixels): minion < 80 <= champion < 160 <= turret
MINION_BODY_DY = 50  # the minion body is about this far below its bar


@dataclass(frozen=True)
class Bar:
    kind: str  # "minion" | "champion" | "turret"
    x: int  # centre of the filled part
    y: int  # bar row
    frac: float  # health fraction 0..1
    team: str  # "enemy" | "ally"
    minion_type: Optional[str] = None  # "cannon" | "melee" | "caster" when known; None when unsure (always None from find_bars today)
    kill_mark: float = 0.0  # share of the bar (0..1) that one of our autos removes: the darker red segment at the left end of an enemy bar

    @property
    def kill_mark_frac(self) -> float:
        """Alias of ``kill_mark`` for the turn log (units[].kill_mark_frac)."""
        return self.kill_mark

    @property
    def body(self) -> Tuple[int, int]:
        """Where to click to target what the bar belongs to."""
        return self.x, self.y + (MINION_BODY_DY if self.kind == "minion" else 70)


class _Pixels:
    """Lazy ``dark_sum[y, x]`` (sum of the three channels): the near-black frame tests read a few hundred pixels per frame, so the
    whole-frame int sum that used to back them was wasted work."""

    def __init__(self, img: Any) -> None:
        self._img = img

    def __getitem__(self, yx: Any) -> int:
        y, x = yx
        p = self._img[y, x]
        return int(p[0]) + int(p[1]) + int(p[2])


def _dark_mask(img: Any) -> Any:
    """The darker red segment of an enemy bar (about (124, 28, 3)): the health our next auto would remove (the game's last-hit marker)."""
    import numpy as np

    r, g, b = img[..., 0].astype(np.int16), img[..., 1].astype(np.int16), img[..., 2].astype(np.int16)
    return (r > 85) & (r < 175) & (g < 60) & (b < 45) & (r - g > 60)


def _fill_mask(img: Any, team: str) -> Any:
    import numpy as np

    r, g, b = img[..., 0].astype(np.int16), img[..., 1].astype(np.int16), img[..., 2].astype(np.int16)
    if team == "enemy":
        pink = (r > 130) & (g < 115) & (b < 115) & (r - g > 70)
        return pink | _dark_mask(img)
    return (b > 170) & (r < 110) & (b - r > 70) & (g < 190)


MIN_DARK_ONLY_PX = 3


def find_bars(img: Any, team: str = "enemy") -> List[Bar]:
    """All health bars of ``team`` in an RGB uint8 array (H, W, 3), outside the HUD, minimap and top bar."""
    h, w = img.shape[:2]
    scale_y = h / 1200.0
    mask = _fill_mask(img, team)
    if team == "enemy":  # the top row of a bar is lighter and fails the colour test: a bar's rows 0-2 count as one
        mask[:-2] = mask[:-2] | mask[1:-1] | mask[2:]
    mask[int(HUD_Y * scale_y):, :] = False
    mask[:int(60 * scale_y), :] = False  # top scoreboard
    sx = w / 1920.0
    mask[int(680 * scale_y):, int(1590 * sx):] = False  # team portraits (with their red respawn digits) + minimap (bottom right)
    mask[int(340 * scale_y):, int(1880 * sx):] = False  # right screen edge strip: nothing reachable, only HUD digits (16 of 44 classifier vetoes were here)
    mask[:int(340 * scale_y), int(1500 * sx):] = False  # kill / objective notices (top right)
    mask[:, :int(100 * sx)] = False  # Practice Tool toolbar
    mask[int(930 * scale_y):, :int(780 * sx)] = False  # ability / summoner icons above the HUD
    mask[int(430 * scale_y):int(890 * scale_y), :int(540 * sx)] = False  # game chat (red/blue bot names and "has slain" lines read as bars: 1711 false bars in 1932 frames)
    dark_sum = _Pixels(img)  # near-black frame test
    dark = _dark_mask(img) if team == "enemy" else None
    if dark is not None:
        dark[:-2] = dark[:-2] | dark[1:-1] | dark[2:]
    bars: List[Bar] = []
    for y in [int(v) for v in mask.any(axis=1).nonzero()[0]]:
        row = mask[y]
        x = 0
        while x < w:
            if not row[x]:
                x += 1
                continue
            x0 = x
            while x < w and (row[x] or (team == "enemy" and row[x + 1:x + 4].any())):  # the dark/pink seam is a few px of other colours
                x += 1
            width = x - x0
            dark_w = 0
            if team == "enemy" and dark is not None and dark[y, x0]:
                dx = x0
                while dx < x and (dark[y, dx] or (dark[y, dx + 1:dx + 4].any() and dx - x0 < 40)):
                    dx += 1
                dark_w = dx - x0
            if width < 8 and not (team == "enemy" and width >= MIN_DARK_ONLY_PX and dark_w >= width - 2):
                continue  # a sliver of the dark kill segment alone (3-7 px) is a minion one auto from dying: keep it
            # skip the repeated rows of the same bar (a bar is 2-4 rows high)
            total = 62 if width < MINION_BAR_MAX else 128  # full bar widths measured on 1920x1200 frames
            cx = (x0 + x - 1) // 2
            if any(0 <= y - b.y <= 4 and abs(b.x - (x0 + total // 2)) <= 8 for b in bars):
                continue
            kind = "minion" if width < MINION_BAR_MAX else "champion" if width < CHAMPION_BAR_MAX else "turret"
            # a real bar has a near-black frame row just above AND just below its 3-4 fill rows
            if dark_sum[max(y - 1, 0), cx] > 90 or min(dark_sum[min(y + 3, h - 1), cx], dark_sum[min(y + 4, h - 1), cx]) > 90:
                continue
            if width < 8 and min(dark_sum[min(y + 1, h - 1), max(x0 - 1, 0)], dark_sum[min(y + 1, h - 1), max(x0 - 2, 0)]) > 90:
                continue  # a sliver must sit on the bar's near-black left frame; the red outline of the targeted minion is a thin red line on grass
            bars.append(Bar(kind, x0 + total // 2, y, round(min(width / total, 1.0), 2), team, None, round(min(dark_w / total, 1.0), 2) if kind == "minion" else 0.0))
    return _merge_turrets(bars)


# Cannon minions cannot be told from the bar: a real cannon (frame lasthit/a01 of game v2i) has the same 62 px bar as a melee minion in
# patch 26.20. The earlier "wider frame = cannon" rule rested on three frames and was wrong, so ``Bar.minion_type`` stays None.


def _merge_turrets(bars: List[Bar]) -> List[Bar]:
    """A turret bar is drawn as several segments on one row: three or more bars on one row become one ``turret``."""
    out: List[Bar] = []
    used = set()
    for i, b in enumerate(bars):
        if i in used:
            continue
        row = [j for j, c in enumerate(bars) if abs(c.y - b.y) <= 2 and j not in used]
        if len(row) >= 3:
            used.update(row)
            xs = [bars[j].x for j in row]
            out.append(Bar("turret", sum(xs) // len(xs), b.y, round(sum(bars[j].frac for j in row) / len(row), 2), b.team))
        else:
            out.append(b)
    return out


def nearest(bars: List[Bar], kind: str, max_dist_px: float) -> List[Bar]:
    """Bars of ``kind`` within ``max_dist_px`` of the player, nearest first."""
    px, py = PLAYER_XY
    close = [b for b in bars if b.kind == kind and ((b.x - px) ** 2 + (b.body[1] - py) ** 2) ** 0.5 <= max_dist_px]
    return sorted(close, key=lambda b: (b.x - px) ** 2 + (b.body[1] - py) ** 2)


MINIMAP_RECT = (1612 / 1920, 893 / 1200, 1912 / 1920, 1190 / 1200)  # the map inside the minimap frame, 1920x1200


def view_box_position(img: Any, rect: Tuple[float, float, float, float] = MINIMAP_RECT) -> Optional[Tuple[float, float]]:
    """Normalised (0..1, top-left origin) centre of the white camera box on the minimap.

    The camera is locked on the player, so the box centre is the player's position (clamped about half a box inside
    the map edges). ``img`` is RGB. Returns None when no box-shaped white outline is found.
    """
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    x0, y0, x1, y1 = int(rect[0] * w), int(rect[1] * h), int(rect[2] * w), int(rect[3] * h)
    crop = img[y0:y1, x0:x1]
    mask = ((crop[..., 0] > 230) & (crop[..., 1] > 230) & (crop[..., 2] > 230)).astype(np.uint8)
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best, best_area = None, 0
    for i in range(1, n):
        bx, by, bw, bh, _a = stats[i]
        if 25 <= bw <= 90 and 20 <= bh <= 75 and 1.0 <= bw / bh <= 2.2 and bw * bh > best_area:
            best, best_area = (bx + bw / 2, by + bh / 2), bw * bh
    if best is None:
        return None
    return best[0] / (x1 - x0), best[1] / (y1 - y0)


_SHOP_TABS = None


def shop_is_open(img: Any) -> bool:
    """True when the shop window is up: its RECOMMENDED / ALL ITEMS / ITEM SETS tab header is on screen (1920x1200).

    Match scores measured on real frames: 0.99+ with the shop open, below 0.3 without it.
    """
    global _SHOP_TABS
    import cv2
    import numpy as np
    from pathlib import Path
    from PIL import Image

    if _SHOP_TABS is None:
        _SHOP_TABS = np.asarray(Image.open(Path(__file__).resolve().parent / "nav_templates" / "shop_tabs.png").convert("RGB"))
    h, w = img.shape[:2]
    if (h, w) != (1200, 1920):
        return False
    region = img[60:260, 380:1240]
    return float(cv2.matchTemplate(region, _SHOP_TABS, cv2.TM_CCOEFF_NORMED).max()) >= 0.9


def hud_visible(img: Any) -> bool:
    """True when the in-game HUD is up: the green health bar of the champion at the bottom centre (1920x1200).

    False on the loading screen and the end screen. Measured: about 300 green pixels in the strip with the HUD, 0 without.
    """
    h, w = img.shape[:2]
    if (h, w) != (1200, 1920):
        return False
    strip = img[1153:1170, 700:1090].astype(int)
    green = (strip[..., 1] > 140) & (strip[..., 0] < 90) & (strip[..., 2] < 90)
    return int(green.sum()) >= 150


_SEARCH_EMPTY = None


def shop_search_is_empty(img: Any) -> bool:
    """True when the shop's search box still shows its placeholder ("Click Here to Search"): the typed name did not land.

    Match scores measured on real frames: 1.0 with the placeholder, below 0.45 with a typed name (1920x1200).
    """
    global _SEARCH_EMPTY
    import cv2
    import numpy as np
    from pathlib import Path
    from PIL import Image

    if _SEARCH_EMPTY is None:
        _SEARCH_EMPTY = np.asarray(Image.open(Path(__file__).resolve().parent / "nav_templates" / "shop_search_empty.png").convert("RGB"))
    if img.shape[:2] != (1200, 1920):
        return False
    return float(cv2.matchTemplate(img[180:225, 460:760], _SEARCH_EMPTY, cv2.TM_CCOEFF_NORMED).max()) >= 0.9


_CAM_ICONS = None


def _best_match(region: Any, template: Any) -> float:
    import cv2
    import numpy as np

    best = 0.0
    for sc in np.arange(0.3, 1.31, 0.1):  # the HUD buttons scale with the minimap size setting
        w, h = max(8, int(template.shape[1] * sc)), max(8, int(template.shape[0] * sc))
        if h > region.shape[0] or w > region.shape[1]:
            continue
        t = cv2.resize(template, (w, h), interpolation=cv2.INTER_AREA)
        best = max(best, float(cv2.matchTemplate(region, t, cv2.TM_CCOEFF_NORMED).max()))
    return best


def camera_state(img: Any) -> Optional[bool]:
    """True = camera locked on the champion, False = unlocked, None = cannot tell. Reads the HUD camera button next to the minimap
    (slashed camera = locked, plain camera = unlocked) at any HUD scale; works in the fountain, where the locked camera cannot
    centre the champion. Measured: the right icon scores 1.0 at the calibrated scale, the other one 0.83-0.85.
    """
    global _CAM_ICONS
    import cv2
    import numpy as np
    from pathlib import Path
    from PIL import Image

    if _CAM_ICONS is None:
        base = Path(__file__).resolve().parent / "nav_templates"
        _CAM_ICONS = tuple(np.asarray(Image.open(base / n).convert("L")) for n in ("camera_locked.png", "camera_unlocked.png"))
    h, w = img.shape[:2]
    if (h, w) != (1200, 1920):
        return None
    region = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)[1080:1200, 1400:1920]
    locked, unlocked = _best_match(region, _CAM_ICONS[0]), _best_match(region, _CAM_ICONS[1])
    if locked >= 0.88 and locked > unlocked + 0.05:
        return True
    if unlocked >= 0.88 and unlocked > locked + 0.05:
        return False
    return None


def camera_is_locked(img: Any) -> bool:
    """True only when :func:`camera_state` says locked."""
    return camera_state(img) is True


def hud_calibrated(img: Any) -> bool:
    """True when the HUD is laid out as the bot's pixel constants assume (MinimapScale 1.23 at 1920x1200): the camera button
    (either icon) is at its calibrated place at scale 1.0. False for another minimap size, resolution or HUD scale.
    """
    import cv2
    import numpy as np
    from pathlib import Path
    from PIL import Image

    if img.shape[:2] != (1200, 1920):
        return False
    base = Path(__file__).resolve().parent / "nav_templates"
    region = img[1160:1200, 1520:1580]
    best = 0.0
    for name in ("camera_locked.png", "camera_unlocked.png"):
        t = np.asarray(Image.open(base / name).convert("RGB"))
        best = max(best, float(cv2.matchTemplate(region, t, cv2.TM_CCOEFF_NORMED).max()))
    return best >= 0.95
