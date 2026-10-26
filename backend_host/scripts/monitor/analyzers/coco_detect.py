"""COCO object detector for the img service: YOLOX-nano (Apache-2.0) ONNX through cv2.dnn (TASK-90 §5).

The model file is not in git. It lives outside the project folder, e.g. /opt/virtualpytest/models/yolox_nano.onnx
(from the official Megvii YOLOX release), and MONITOR_COCO_MODEL points at it. This module owns the YOLOX
pre- and post-processing (letterbox 416, grid decode, NMS); it reuses only the COCO class list from
shared/src/lib/drone/perception.py, not CocoDetector.detect (one box per target).
"""
import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from shared.src.lib.drone.perception import COCO_CLASSES

STRIDES = (8, 16, 32)


@dataclass
class Detection:
    label: str
    conf: float
    bbox: Tuple[float, float, float, float]  # x, y, w, h in frame pixels
    shape: Optional[dict] = None             # {'ellipse': [cx, cy, ax, ay, angle_deg]} when the detector knows the outline
    size_mm: Optional[float] = None          # major axis in millimetres when the detector was given px_per_mm


def _grids(size: int):
    cells, strides = [], []
    for s in STRIDES:
        n = size // s
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        g = np.stack((xv, yv), 2).reshape(-1, 2)
        cells.append(g)
        strides.append(np.full((g.shape[0], 1), s))
    return np.concatenate(cells).astype(np.float32), np.concatenate(strides).astype(np.float32)


def letterbox(frame: np.ndarray, size: int) -> Tuple[np.ndarray, float]:
    """Scale to fit size x size keeping the aspect ratio, pad bottom/right with 114. Returns (image, scale)."""
    r = min(size / frame.shape[0], size / frame.shape[1])
    nh, nw = int(frame.shape[0] * r), int(frame.shape[1] * r)
    canvas = np.full((size, size, 3), 114, np.uint8)
    canvas[:nh, :nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return canvas, r


def decode(output: np.ndarray, size: int) -> np.ndarray:
    """Raw YOLOX output [N, 85] (cx, cy, w, h as grid offsets/log sizes, objectness, 80 class scores)
    -> [N, 85] in letterboxed pixels."""
    o = output.astype(np.float32).copy()
    grid, stride = _grids(size)
    if o.shape[0] != grid.shape[0]:
        raise ValueError(f"model output has {o.shape[0]} anchors, expected {grid.shape[0]} for input {size}")
    o[:, :2] = (o[:, :2] + grid) * stride
    o[:, 2:4] = np.exp(o[:, 2:4]) * stride
    return o


def postprocess(output: np.ndarray, scale: float, frame_shape: Tuple[int, int], size: int,
                class_ids: Sequence[int], min_conf: float, nms_iou: float, class_agnostic: bool = False) -> List[Detection]:
    o = decode(output, size)
    scores = o[:, 4:5] * o[:, 5:]
    boxes, confs, ids = [], [], []
    for cid in class_ids:
        col = scores[:, cid]
        for i in np.nonzero(col >= min_conf)[0]:
            cx, cy, w, h = o[i, :4]
            boxes.append([float(cx - w / 2), float(cy - h / 2), float(w), float(h)])
            confs.append(float(col[i]))
            ids.append(cid)
    if not boxes:
        return []
    keep = np.array(cv2.dnn.NMSBoxesBatched(boxes, confs, ids, min_conf, nms_iou)).reshape(-1)
    if class_agnostic and len(keep):
        # one vehicle often gets a car AND a truck box (or truck and bus): keep the most confident one of overlapping boxes
        # whatever the class (all classes asked for are one kind of thing to this profile)
        sub = np.array(cv2.dnn.NMSBoxes([boxes[k] for k in keep], [confs[k] for k in keep], min_conf, nms_iou)).reshape(-1)
        keep = keep[sub]
    fh, fw = frame_shape
    out = []
    for k in np.array(keep).reshape(-1):
        x, y, w, h = boxes[k]
        x0, y0 = max(0.0, x / scale), max(0.0, y / scale)
        x1, y1 = min(float(fw), (x + w) / scale), min(float(fh), (y + h) / scale)
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        out.append(Detection(COCO_CLASSES[ids[k]], confs[k], (x0, y0, x1 - x0, y1 - y0)))
    out.sort(key=lambda d: -d.conf)
    return out


class CocoDetect:
    """type: coco_detect — keys: classes, min_conf, model_env (env var holding the model path), input_size, nms_iou,
    tiles, tile_overlap.

    `tiles: [nx, ny]` runs the model on an nx x ny grid of overlapping crops and merges them with one NMS. A 1280x720
    frame letterboxed into 416 shrinks every object to a third: on the street camera of counting_cars the whole frame
    gave 0-8 vehicles of ~150 in view, 2x2 tiles give ~60 (each tile is one forward, so 2x2 costs 4x)."""

    def __init__(self, classes: Sequence[str], min_conf: float = 0.4, model_env: str = 'MONITOR_COCO_MODEL',
                 input_size: int = 416, nms_iou: float = 0.45, model_path: Optional[str] = None,
                 class_agnostic: bool = True, tiles: Optional[Sequence[int]] = None, tile_overlap: float = 0.15):
        unknown = [c for c in classes if c not in COCO_CLASSES]
        if unknown:
            raise ValueError(f"not COCO classes: {unknown}")
        self.class_ids = [COCO_CLASSES.index(c) for c in classes]
        self.min_conf = min_conf
        self.size = input_size
        self.nms_iou = nms_iou
        self.class_agnostic = class_agnostic
        self.tiles = (int(tiles[0]), int(tiles[1])) if tiles else None
        self.tile_overlap = float(tile_overlap)
        path = model_path or os.getenv(model_env, '')
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(
                f"coco_detect: model file not found ({model_env}={path!r}). Put yolox_nano.onnx outside the project folder "
                f"(e.g. /opt/virtualpytest/models/) and set {model_env}.")
        self.net = cv2.dnn.readNetFromONNX(path)

    def detect(self, frame_bgr: np.ndarray) -> List[Detection]:
        if not self.tiles:
            return self._detect_one(frame_bgr)
        h, w = frame_bgr.shape[:2]
        nx, ny = self.tiles
        tw, th = min(w, int(w / nx * (1 + self.tile_overlap))), min(h, int(h / ny * (1 + self.tile_overlap)))
        found: List[Detection] = []
        for iy in range(ny):
            for ix in range(nx):
                x0, y0 = min(w - tw, int(ix * w / nx)), min(h - th, int(iy * h / ny))
                for d in self._detect_one(frame_bgr[y0:y0 + th, x0:x0 + tw]):
                    bx, by, bw, bh = d.bbox
                    found.append(Detection(d.label, d.conf, (bx + x0, by + y0, bw, bh)))
        if not found:
            return []
        # a vehicle in the overlap is found by two tiles: one NMS over all of them, whatever the class (see postprocess)
        keep = np.array(cv2.dnn.NMSBoxes([list(d.bbox) for d in found], [d.conf for d in found],
                                         self.min_conf, self.nms_iou)).reshape(-1)
        return sorted((found[int(k)] for k in keep), key=lambda d: -d.conf)

    def _detect_one(self, frame_bgr: np.ndarray) -> List[Detection]:
        canvas, scale = letterbox(frame_bgr, self.size)
        # YOLOX takes raw 0-255 BGR, no mean/std
        blob = cv2.dnn.blobFromImage(canvas, 1.0, (self.size, self.size), (0, 0, 0), swapRB=False)
        self.net.setInput(blob)
        out = self.net.forward()[0]
        return postprocess(out, scale, frame_bgr.shape[:2], self.size, self.class_ids, self.min_conf, self.nms_iou,
                           self.class_agnostic)
