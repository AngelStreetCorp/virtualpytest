"""First-person software renderer for the simulator (numpy ray cast, one ray per image column).

Walls, floor and ceiling are textured, furniture is drawn as shaded coloured boxes, and a per-pixel depth
buffer gives correct occlusion. Other drones are drawn as a small dark body with a ArUco marker
(DICT_4X4_50, id = drone index).

Marker size: real scale. Each real drone carries a paper box with a 4 cm tag on each side
(scripts/drone/print_markers.py), so the sim draws an 18 cm wide body (Tello with prop guards) under a 5 cm
white plate holding a MARKER_CM tag. At the 960 px / 82.6 deg camera (f ~ 545 px) a 4 cm tag is ~15 px
wide at 150 cm, close to where cv2.aruco stops reading it, so the sim's detection range is as short as the
real one is expected to be. The plate is a billboard (always faces the viewing camera), standing in for
the box's four faces.
"""

import math
from functools import lru_cache
from typing import List, Tuple

import cv2
import numpy as np

from .world import Pose, Room

_BODY = (45, 45, 50)
_WALL_BASE = {  # BGR per wall: N, E, S, W (low saturation so furniture hues stay unique)
    "N": (205, 210, 214), "E": (178, 184, 190), "S": (196, 202, 207), "W": (166, 172, 178),
}
MARKER_CM = 4.0
_PX_CM = 16.0  # sprite px per cm
_BODY_W_CM, _BODY_H_CM, _PLATE_CM = 18.0, 4.0, 5.0
_SPR_W = int(_BODY_W_CM * _PX_CM)
_SPR_H = int((_PLATE_CM + _BODY_H_CM) * _PX_CM)


@lru_cache(maxsize=16)
def _sprite(drone_id: int) -> Tuple[np.ndarray, np.ndarray]:
    """Drone sprite (BGR, mask): white plate with the ArUco tag above a dark body."""
    spr = np.zeros((_SPR_H, _SPR_W, 3), np.uint8)
    mask = np.zeros((_SPR_H, _SPR_W), np.uint8)
    plate, tag = int(_PLATE_CM * _PX_CM), int(MARKER_CM * _PX_CM)
    px0 = (_SPR_W - plate) // 2
    cv2.rectangle(spr, (px0, 0), (px0 + plate - 1, plate - 1), (255, 255, 255), -1)
    cv2.rectangle(mask, (px0, 0), (px0 + plate - 1, plate - 1), 255, -1)
    dic = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    off = (plate - tag) // 2
    spr[off:off + tag, px0 + off:px0 + off + tag] = cv2.aruco.generateImageMarker(dic, drone_id, tag)[:, :, None]
    cv2.rectangle(spr, (0, plate), (_SPR_W - 1, _SPR_H - 1), _BODY, -1)
    cv2.rectangle(mask, (0, plate), (_SPR_W - 1, _SPR_H - 1), 255, -1)
    led_y, r = plate + (_SPR_H - plate) // 2, max(2, int(0.6 * _PX_CM))
    cv2.circle(spr, (int(2 * _PX_CM), led_y), r, (0, 0, 230), -1)   # front LEDs
    cv2.circle(spr, (_SPR_W - int(2 * _PX_CM), led_y), r, (0, 200, 0), -1)
    return spr, mask


def _plane(img, depth, zc, zp, rows, f, px, py, dx, dy, base, check):
    """Paint a horizontal plane (floor/ceiling) on `rows`; also writes depth."""
    H, W = img.shape[:2]
    dz = np.abs(rows + 0.5 - H / 2.0)
    t = (f * abs(zp - zc) / dz).astype(np.float32)  # perpendicular depth per row
    wx = px + t[:, None] * dx[None, :]
    wy = py + t[:, None] * dy[None, :]
    par = ((np.floor(wx / check) + np.floor(wy / check)) % 2).astype(np.float32)
    fog = np.clip(1.15 - t / 1500.0, 0.55, 1.0)[:, None]
    shade = (0.86 + 0.14 * par) * fog
    img[rows[0]:rows[-1] + 1] = np.clip(np.asarray(base, np.float32)[None, None, :] * shade[:, :, None], 0, 255).astype(np.uint8)
    depth[rows[0]:rows[-1] + 1] = t[:, None]


def _paint(img, depth, top, bot, t, valid, colors, rowfn=None):
    """Paint column spans [top, bot] with per-column depth `t`, respecting the depth buffer."""
    H, W = img.shape[:2]
    top = np.maximum(top, 0)
    bot = np.minimum(bot, H - 1)
    valid = valid & (bot >= top)
    vc = np.flatnonzero(valid)
    if vc.size == 0:
        return
    c0, c1 = vc[0], vc[-1] + 1  # work only inside the bounding box of the painted spans
    r0, r1 = int(top[vc].min()), int(bot[vc].max()) + 1
    rows = np.arange(r0, r1)[:, None]
    sl = (slice(r0, r1), slice(c0, c1))
    m = (valid[None, c0:c1] & (rows >= top[None, c0:c1]) & (rows <= bot[None, c0:c1])
         & (t[None, c0:c1] < depth[sl]))
    if not m.any():
        return
    blk = colors[None, c0:c1, :]
    if rowfn is not None:
        yy = np.broadcast_to(rows, m.shape)
        xx = np.broadcast_to(np.arange(c0, c1)[None, :], m.shape)
        blk = blk * rowfn(yy, xx)[:, :, None]
    else:
        blk = np.broadcast_to(blk, (r1 - r0, c1 - c0, 3))
    img[sl] = np.where(m[:, :, None], blk.astype(np.uint8), img[sl])
    depth[sl] = np.where(m, t[None, c0:c1], depth[sl])


def render_view(room: Room, pose: Pose, others: List[Tuple[int, Pose]], width: int = 960, height: int = 720,
                hfov_deg: float = 82.6) -> np.ndarray:
    W, H = width, height
    f = (W / 2.0) / math.tan(math.radians(hfov_deg / 2.0))
    zc = max(pose.z, 6.0)  # camera height; a landed drone still sits a few cm above the floor
    yaw = math.radians(pose.yaw_deg)
    fx, fy = math.sin(yaw), math.cos(yaw)
    rx, ry = math.cos(yaw), -math.sin(yaw)
    px, py = pose.x, pose.y
    s = ((np.arange(W) + 0.5) - W / 2.0) / f
    dx = (fx + s * rx).astype(np.float32)  # unnormalised: ray parameter t == perpendicular depth
    dy = (fy + s * ry).astype(np.float32)

    img = np.empty((H, W, 3), np.uint8)
    depth = np.full((H, W), np.inf, np.float32)
    hz = H // 2
    # ceiling above eye level, floor below it
    _plane(img, depth, zc, room.height, np.arange(0, hz), f, px, py, dx, dy, (232, 232, 236), 100.0)
    depth[:hz] = np.inf  # ceiling never occludes sprites that are in front of the wall tops
    _plane(img, depth, zc, 0.0, np.arange(hz, H), f, px, py, dx, dy, (110, 125, 140), 50.0)
    cols_i = np.arange(W)

    # walls: nearest positive exit of the room rectangle
    with np.errstate(divide="ignore", invalid="ignore"):
        tx = np.where(dx > 0, (room.width - px) / dx, (0 - px) / dx)
        ty = np.where(dy > 0, (room.depth - py) / dy, (0 - py) / dy)
    tx = np.where(np.isfinite(tx) & (tx > 0), tx, np.inf)
    ty = np.where(np.isfinite(ty) & (ty > 0), ty, np.inf)
    tw = np.minimum(tx, ty).astype(np.float32)
    x_wall = tx < ty
    hitx = px + tw * dx
    hity = py + tw * dy
    wall_cols = np.empty((W, 3), np.float32)
    along = np.where(x_wall, hity, hitx)
    for name, sel in (("E", x_wall & (dx > 0)), ("W", x_wall & (dx <= 0)),
                      ("N", ~x_wall & (dy > 0)), ("S", ~x_wall & (dy <= 0))):
        wall_cols[sel] = _WALL_BASE[name]
    panel = np.where(np.abs((along % 100.0) - 50.0) > 48.5, 0.9, 1.0)  # panel seams every 100 cm
    wall_cols *= (np.clip(1.1 - tw / 1500.0, 0.6, 1.0) * panel)[:, None]
    with np.errstate(invalid="ignore"):
        vtop = H / 2.0 - f * (room.height - zc) / tw
        vbot = H / 2.0 - f * (0.0 - zc) / tw

    def wall_rows(yy, xx):  # baseboard below 10 cm, darker towards the ceiling
        z = zc + (H / 2.0 - yy) * tw[xx] / f
        return np.where(z < 10, 0.62, 1.0 - 0.1 * (z / room.height)).astype(np.float32)

    _paint(img, depth, np.ceil(vtop).astype(np.int32), np.floor(vbot).astype(np.int32), tw,
           np.isfinite(tw), wall_cols, wall_rows)

    # furniture boxes
    ones = np.ones(W, bool)
    for o in room.objects:
        x0, x1, y0, y1 = o.bounds
        with np.errstate(divide="ignore", invalid="ignore"):
            ddx = np.where(np.abs(dx) < 1e-9, 1e-9, dx)
            ddy = np.where(np.abs(dy) < 1e-9, 1e-9, dy)
            ax, bx = (x0 - px) / ddx, (x1 - px) / ddx
            ay, by = (y0 - py) / ddy, (y1 - py) / ddy
        tminx, tmaxx = np.minimum(ax, bx), np.maximum(ax, bx)
        tminy, tmaxy = np.minimum(ay, by), np.maximum(ay, by)
        t_in = np.maximum(tminx, tminy)
        t_out = np.minimum(tmaxx, tmaxy)
        hit = (t_out > t_in) & (t_in > 1.0)
        if not hit.any():
            continue
        t_in = np.where(hit, t_in, np.inf).astype(np.float32)
        t_out = np.where(hit, t_out, np.inf).astype(np.float32)
        side_x = tminx > tminy
        # position along the face, to darken the box edges
        hx = px + np.where(hit, t_in, 0) * dx
        hy = py + np.where(hit, t_in, 0) * dy
        e = np.where(side_x, np.minimum(hy - y0, y1 - hy), np.minimum(hx - x0, x1 - hx))
        edge = np.where(e < 1.5, 0.55, 1.0)
        base = np.asarray(o.color, np.float32)
        fog = np.clip(1.1 - t_in / 1600.0, 0.55, 1.0)
        cols = base[None, :] * (np.where(side_x, 0.72, 0.9) * fog * edge)[:, None]
        ztop = o.z0 + o.h
        with np.errstate(invalid="ignore"):
            v_top = H / 2.0 - f * (ztop - zc) / t_in
            v_bot = H / 2.0 - f * (o.z0 - zc) / t_in
        _paint(img, depth, np.ceil(v_top).astype(np.int32), np.floor(v_bot).astype(np.int32), t_in, hit, cols)
        if zc > ztop:  # top face visible from above: between the near and far top edges
            with np.errstate(invalid="ignore"):
                v_far = H / 2.0 - f * (ztop - zc) / t_out
            tcols = base[None, :] * np.clip(1.15 * fog, 0, 1.0)[:, None]
            _paint(img, depth, np.ceil(v_far).astype(np.int32), np.ceil(v_top).astype(np.int32) - 1, t_in, hit, tcols)

    # other drones as billboards with their ArUco marker
    for did, op in others:
        rel_x, rel_y = op.x - px, op.y - py
        d = rel_x * fx + rel_y * fy
        if d < 20:
            continue
        k = f / d / _PX_CM  # screen px per sprite px
        sw, sh = int(round(_SPR_W * k)), int(round(_SPR_H * k))
        if sw < 3 or sh < 3:
            continue
        u = W / 2.0 + f * (rel_x * rx + rel_y * ry) / d
        v_bottom = H / 2.0 - f * ((op.z - 2.0) - zc) / d
        left, top = int(round(u - sw / 2.0)), int(round(v_bottom - sh))
        x0c, y0c = max(left, 0), max(top, 0)
        x1c, y1c = min(left + sw, W), min(top + sh, H)
        if x1c <= x0c or y1c <= y0c:
            continue
        spr, msk = _sprite(did)
        interp = cv2.INTER_AREA if k < 1.0 else cv2.INTER_LINEAR
        spr_r = cv2.resize(spr, (sw, sh), interpolation=interp)
        msk_r = cv2.resize(msk, (sw, sh), interpolation=interp)
        sub = (slice(y0c - top, y1c - top), slice(x0c - left, x1c - left))
        roi = (slice(y0c, y1c), slice(x0c, x1c))
        vis = (msk_r[sub] > 127) & (np.float32(d) < depth[roi])
        img[roi][vis] = spr_r[sub][vis]
        depth[roi][vis] = d
    return img
