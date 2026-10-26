"""Trained detector for the img service: an Ultralytics YOLOv8 **segmentation** model in ONNX, through
cv2.dnn (same runtime as `coco_detect`, no torch on the host). type: `yolo_seg_detect`.

WHY THIS EXISTS ALONGSIDE `egg_detect` (TASK-90 goal 9)
--------------------------------------------------------
`egg_detect method: blob` finds each egg by its own local contrast, which is why it never merges two
eggs — but its box is the LoG *response diameter*, not the egg, so on real footage it draws circles
that are much smaller than the eggs they sit on (measured on the device3 frame: 45 px circles on
55-70 px eggs). This detector is a model trained on egg photographs, so its box IS the egg.

THE WHOLE FRAME IS NOT ENOUGH — SLICE IT
-----------------------------------------
Run on the whole 720p frame the model finds 87 of the ~227 eggs in it. The same model on a 480x240
crop of that frame finds 22 of the 26 eggs in it (85 %). So the model is not blind to the rest: it
loses them to *context* — one 640x640 input cannot hold 200 eggs at a size the head will commit to.
Slicing the frame into overlapping tiles and merging restores it (measured, one frame, ultralytics
reference then re-measured through this decoder):

    whole frame, one pass              87 boxes
    25 tiles 640x360, zoom 1.34       154 boxes
    64 tiles 480x270, zoom 1.34       205 boxes (234 before the sliver filter, below)

`tile_zoom` matters because the ONNX input is a fixed 640x640 square: a crop wider than 640 px can
only ever be scaled DOWN to fit it, which is the whole-frame failure again. A 480 px crop is scaled
UP 1.33x, and that is the scale the model was trained at.

THE TWO FILTERS HERE ARE NOT COSMETIC
-------------------------------------
1. `tile_overlap` — eggs that straddle a tile border come out as a box clipped by the tile edge, so
   with no overlap a fifth of the eggs lose their circle. 0.12 is the cheapest overlap that fixes it.
2. `min_side` / `max_aspect` — a clipped box is a sliver (measured: 1339 raw boxes at conf 0.03 over
   64 tiles, of which 205 survive dropping sides under 14 px and aspect ratios over 2.6). An egg is
   round; a box that is 6x longer than it is wide is a border artefact, never an egg. Drawing those
   is what made the first tiled render look broken.

NMS, AND THE TRAP THAT COST AN HOUR OF WRONG NUMBERS
----------------------------------------------------
`cv2.dnn.NMSBoxes` takes **(x, y, w, h)**, not xyxy. Passing xyxy makes every box overlap every other
one and silently deletes half of them: the whole-frame count read 36 instead of 87, and tiling looked
like it made recall *worse* (62 vs 88) when it in fact more than doubled it (154 vs 87). `nms()`
below converts, so callers hand it xyxy and cannot get it wrong.

Only the surviving boxes are kept; the mask prototypes are not used (see `use_masks`), which is what
keeps this at one 640x640 forward per tile.
"""
import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from monitor.analyzers.coco_detect import Detection


@dataclass
class _Raw:
    """One box in FRAME pixels, before the sliver filter."""
    cls: int
    conf: float
    x0: float
    y0: float
    x1: float
    y1: float


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def nms(items: Sequence[_Raw], conf: float, iou: float) -> List[_Raw]:
    """Class-aware NMS over xyxy boxes.

    `cv2.dnn.NMSBoxes` wants (x, y, w, h); feeding it xyxy inflates every overlap and throws away
    most of the detections while reporting no error. The conversion is the whole reason this is a
    function instead of a call at the use site.
    """
    if not items:
        return []
    boxes = [(it.x0, it.y0, max(0.0, it.x1 - it.x0), max(0.0, it.y1 - it.y0)) for it in items]
    scores = [it.conf for it in items]
    keep = cv2.dnn.NMSBoxesBatched(boxes, scores, [it.cls for it in items], conf, iou).reshape(-1)
    return [items[int(i)] for i in keep]


class YoloSegDetect:
    """type: yolo_seg_detect — keys: classes, min_conf, model_env, model_path, input_size, tile,
    tile_overlap, nms_iou, min_side, max_aspect, label, use_masks, fill, preprocess, flip_tta,
    dedupe_dist, dedupe_ratio, color_filter, backend, threads.

    `input_size` is a square side (640) or `[width, height]` for a rectangular export. A 16:9 frame
    letterboxed into a square is 44 % grey padding the model still has to run through; a 640x384
    export of the same weights sees the same eggs at the same scale for 0.6x the work (BUG-0917).
    `backend` is `opencv` (cv2.dnn, the default) or `onnxruntime`, which runs the same ONNX about
    twice as fast on the host's CPU; `threads` caps its intra-op threads so the capture ffmpegs keep
    their share.

    `tile_overlap` is the fraction of a tile shared with its neighbour (0.25 = a quarter overlap).
    There is no zoom knob on purpose: the ONNX input is a fixed `input_size` square, so a tile narrower
    than it is already scaled UP by input_size/tile_width — that IS the zoom the model wants (a 480 px
    tile in a 640 input is 1.33x). It also means `tile` must not exceed input_size: a wider crop can
    only be scaled down, which is the whole-frame failure this module exists to avoid.

    `fill`, `preprocess` and `flip_tta` decide WHAT THE MODEL IS SHOWN, and on the egg line they are
    worth more than any threshold: the model was trained on big white eggs on warm rods, and the feed
    is small white eggs on a saturated blue belt. Measured on the device3 frame: letterbox 89 boxes,
    stretch 96, + whitebalance/unsharp 226, + mirror TTA 238 candidates.

    `dedupe_dist` and `color_filter` decide WHAT A CIRCLE IS: whether two boxes are the same egg seen
    twice (IoU cannot tell, distance can) and whether a box is an egg or bare belt (the scene's own
    colour can, a brightness test cannot). Both are opt-in — the colour one is a property of the
    scene, and the dedupe one is a knob for scenes where the model really does fire twice."""

    def __init__(self, classes: Optional[Sequence[str]] = None, min_conf: float = 0.25,
                 model_env: str = 'MONITOR_YOLO_MODEL', model_path: Optional[str] = None,
                 input_size: int = 640, tile: Optional[Sequence[int]] = None, tile_zoom: float = 1.0,
                 tile_overlap: float = 0.25, nms_iou: float = 0.30, min_side: float = 14.0,
                 max_aspect: float = 2.6, label: Optional[str] = None, use_masks: bool = False,
                 fill: str = 'letterbox', preprocess: Optional[Sequence[str]] = None,
                 flip_tta: bool = False, dedupe_dist: float = 0.0,
                 dedupe_ratio: float = 0.35, color_filter: Optional[dict] = None,
                 backend: str = 'opencv', threads: int = 2):
        self.min_conf = min_conf
        if isinstance(input_size, (list, tuple)):
            self.in_w, self.in_h = int(input_size[0]), int(input_size[1])
        else:
            self.in_w = self.in_h = int(round(input_size))
        self.tile_overlap = float(tile_overlap)
        self.nms_iou = nms_iou
        self.min_side = float(min_side)
        self.max_aspect = float(max_aspect)
        self.use_masks = bool(use_masks)
        self.fill = fill
        self.preprocess = list(preprocess or [])
        self.flip_tta = bool(flip_tta)
        # Centre-distance dedupe (0 = off). See `merge_duplicates()`.
        self.dedupe_dist = float(dedupe_dist)
        self.dedupe_ratio = float(dedupe_ratio)
        # Colour validator: {v_min, s_max, min_ratio}. See `egg_ratio()`.
        self.color_filter = dict(color_filter) if color_filter else None
        # A label per class when the profile asks for several, else one label for everything found.
        self.labels = list(classes) if classes else None
        self.label = label or (classes[0] if classes and len(classes) == 1 else 'object')

        path = model_path or os.getenv(model_env, '')
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(
                f"yolo_seg_detect: model file not found ({model_env}={path!r}). Put the exported ONNX "
                f"outside the project folder (e.g. /var/lib/vpt_user/models/) and set {model_env}.")
        self.backend = str(backend).lower()
        self.sess = None
        self.net = None
        if self.backend == 'onnxruntime':
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = int(threads)
            so.inter_op_num_threads = 1
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self.sess = ort.InferenceSession(path, so, providers=['CPUExecutionProvider'])
            self._ort_in = self.sess.get_inputs()[0].name
        elif self.backend == 'opencv':
            self.net = cv2.dnn.readNetFromONNX(path)
        else:
            raise ValueError(f"yolo_seg_detect: unknown backend {backend!r} (opencv | onnxruntime)")
        self.tile = (int(tile[0]), int(tile[1])) if tile else None
        self._protos_shape = None
        self._n_classes = None
        self._n_mask_coeff = 0
        self._attrs = 0
        self._probe()

    # ---------------------------------------------------------------- model shape

    def _probe(self) -> None:
        """Read the head's shape from the graph so nothing has to be configured twice.

        output0 is [1, 4 + n_classes + n_mask_coeff, n_anchors]; output1, when the export kept the
        mask head, is [1, n_mask_coeff, mh, mw].

        THE CLASS COUNT IS NOT GUESSED. A segmentation head has 32 mask coefficients after the class
        scores, and when the export drops the prototype branch those columns stay in output0 with
        nothing marking where the classes end. Reading "attrs - 4" then treats every coefficient
        above `min_conf` as a class score: measured on the egg model, 618 boxes per frame instead of
        87, all of them noise. So the count comes from the protos when they are there, and from the
        profile's `classes` when they are not — and with neither it refuses to run.
        """
        got = self._run(np.zeros((1, 3, self.in_h, self.in_w), np.float32))
        o0 = got[0]
        if o0.ndim == 3:                                # [1, A, N] -> [A, N]
            o0 = o0[0]
        if o0.shape[0] < o0.shape[1]:                   # [A, N] -> [N, A]
            o0 = o0.T
        self._attrs = int(o0.shape[1])
        protos = None
        for g in got[1:]:
            if g is not None and g.ndim == 4:
                protos = g
        if protos is not None:
            self._n_mask_coeff = int(protos.shape[1])
            self._protos_shape = (int(protos.shape[2]), int(protos.shape[3]))
            self._n_classes = self._attrs - 4 - self._n_mask_coeff
        elif self.labels:
            self._n_classes = len(self.labels)
        else:
            raise ValueError(
                f"yolo_seg_detect: the model head has {self._attrs} attributes and no mask-prototype output "
                f"to tell classes from mask coefficients. Put `classes: [...]` in the profile (one name "
                f"per class, in the model's order).")
        if self._n_classes < 1:
            raise ValueError(f"yolo_seg_detect: {self._attrs} head attributes leave no room for a class score")
        if self.labels and len(self.labels) != self._n_classes:
            raise ValueError(f"yolo_seg_detect: profile asks for {len(self.labels)} classes but the model "
                             f"has {self._n_classes}")

    def _run(self, blob: np.ndarray) -> List[np.ndarray]:
        """One forward on either backend: every output of the graph, head first."""
        if self.sess is not None:
            return list(self.sess.run(None, {self._ort_in: blob}))
        names = [n for n in self.net.getUnconnectedOutLayersNames() if n]
        self.net.setInput(blob)
        return list(self.net.forward(names)) if len(names) > 1 else [self.net.forward(names[0])]

    # ---------------------------------------------------------------- pre / post

    def _prep(self, frame: np.ndarray) -> np.ndarray:
        """The transforms that close the gap to what the model was trained on.

        The model saw a portrait video of big white eggs on yellow rods, in daylight. The device3
        feed is a landscape shot of small white eggs on a blue belt. Every op here is aimed at one
        of those three differences, and each is measured, not assumed (see the table in the profile).
        """
        out = frame
        for op in self.preprocess:
            if op == 'clahe':
                lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
                out = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
            elif op == 'gamma':
                out = np.clip((out / 255.0) ** 0.6 * 255.0, 0, 255).astype(np.uint8)
            elif op == 'unsharp':
                blur = cv2.GaussianBlur(out, (0, 0), 3)
                out = cv2.addWeighted(out, 1.8, blur, -0.8, 0)
            elif op == 'gray':
                out = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
                out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
            elif op == 'whitebalance':
                # pull the colour out of the scene: the training background is warm, ours is blue
                g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
                g = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
                out = cv2.addWeighted(out, 0.35, g, 0.65, 0)
            elif op == 'eggness':
                # white on blue: the eggs keep their brightness and lose the belt's blue
                b, gg, r = cv2.split(out)
                e = np.clip((r.astype(np.int16) + gg.astype(np.int16)) // 2 - b.astype(np.int16), 0, 255)
                e = e.astype(np.uint8)
                out = cv2.cvtColor(e, cv2.COLOR_GRAY2BGR)
            elif op == 'edge':
                g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
                out = cv2.cvtColor(cv2.Canny(g, 60, 160), cv2.COLOR_GRAY2BGR)
            else:
                raise ValueError(f"yolo_seg_detect: unknown preprocess op {op!r}")
        return out

    def _letterbox(self, frame: np.ndarray) -> Tuple[np.ndarray, float, float]:
        """Put a crop into the model's fixed square input.

        `letterbox` keeps the aspect and pads with grey; `stretch` fills the square and distorts.
        Which one is right depends on the tile: a square tile can be stretched with no distortion at
        all, while a wide tile stretched would turn every egg into a tall ellipse.

        Returns the canvas and the TWO factors that take canvas pixels back to crop pixels. They are
        equal for a letterbox and for a stretched square tile, and different for a stretched
        non-square tile. Returning one scale for both is a bug that shows up as every box being
        640/tile_wide times too big -- which is exactly what the first stretched run drew.
        """
        h, w = frame.shape[:2]
        if self.fill == 'stretch':
            canvas = cv2.resize(frame, (self.in_w, self.in_h), interpolation=cv2.INTER_LINEAR)
            return canvas, w / float(self.in_w), h / float(self.in_h)
        r = min(self.in_h / h, self.in_w / w)
        nh, nw = int(round(h * r)), int(round(w * r))
        canvas = np.full((self.in_h, self.in_w, 3), 114, np.uint8)
        canvas[:nh, :nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        return canvas, 1.0 / r, 1.0 / r

    def _tiles(self, w: int, h: int) -> List[Tuple[int, int, int, int]]:
        """Grid of crops, in frame pixels. None = the whole frame as one crop."""
        if not self.tile:
            return [(0, 0, w, h)]
        tw = min(self.tile[0], w)
        th = min(self.tile[1], h)
        # `tile_overlap` is the fraction of a tile shared with its neighbour, so the STEP is what is
        # left over. Using the overlap itself as the step is the same maths four forwards cheaper on
        # paper and four times slower in practice: measured on the egg model, "overlap 0.25" then ran
        # a 75 % overlap (240 tiles, 75 s a frame) where 0.25 is meant to run 12 tiles.
        step = (max(8, int(round(tw * (1.0 - self.tile_overlap)))), max(8, int(round(th * (1.0 - self.tile_overlap)))))
        xs = sorted(set(list(range(0, max(1, w - tw + 1), step[0])) + [max(0, w - tw)]))
        ys = sorted(set(list(range(0, max(1, h - th + 1), step[1])) + [max(0, h - th)]))
        return [(x, y, x + tw, y + th) for y in ys for x in xs]

    def _forward(self, crop: np.ndarray) -> Tuple[np.ndarray, float, float, Optional[np.ndarray]]:
        canvas, rx, ry = self._letterbox(self._prep(crop))
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 255.0, (self.in_w, self.in_h), (0, 0, 0), swapRB=True)
        outs = self._run(blob)
        head = outs[0]
        protos = None
        for g in outs[1:]:
            if g is not None and g.ndim == 4:
                protos = g
        return head, rx, ry, protos

    def _decode(self, head: np.ndarray, rx: float, ry: float, ox: int, oy: int,
                frame_shape: Tuple[int, int]) -> List[_Raw]:
        """head [1, A, N] in letterbox pixels -> boxes in frame pixels."""
        h = head[0] if head.ndim == 3 else head
        # cv2 hands the head over as [A, N]. A is the width _probe measured on the graph, NOT
        # 4 + classes + mask coefficients: those two differ as soon as the export kept a mask head
        # without its prototypes, and then this check silently does not fire, the array is never
        # transposed, and `cls_scores` reads a row instead of a column. Guessing with
        # `shape[0] < shape[1]` is wrong too, the moment N == 1.
        if h.shape[0] == self._attrs and h.shape[1] != self._attrs:
            h = np.transpose(h, (1, 0))                 # [A, N] -> [N, A]
        nc = self._n_classes
        cx, cy, bw, bh = h[:, 0], h[:, 1], h[:, 2], h[:, 3]
        cls_scores = h[:, 4:4 + nc]
        ids = cls_scores.argmax(1)
        scores = cls_scores[np.arange(len(ids)), ids]
        keep = np.nonzero(scores >= self.min_conf)[0]
        out: List[_Raw] = []
        if keep.size == 0:
            return out
        fh, fw = frame_shape
        # Vectorised: at min_conf 0.02 a 640 head keeps thousands of anchors, and a Python loop over
        # them cost more than the forward on the host (BUG-0917).
        x0 = np.clip((cx[keep] - bw[keep] / 2) * rx + ox, 0.0, fw)
        y0 = np.clip((cy[keep] - bh[keep] / 2) * ry + oy, 0.0, fh)
        x1 = np.clip((cx[keep] + bw[keep] / 2) * rx + ox, 0.0, fw)
        y1 = np.clip((cy[keep] + bh[keep] / 2) * ry + oy, 0.0, fh)
        ok = ((x1 - x0) >= 1) & ((y1 - y0) >= 1)
        # .tolist() gives Python floats: a np.float32 that reaches the frame JSON raises
        # `Object of type float32 is not JSON serializable` when the worker writes it.
        for c, sc, a, b, cc, d in zip(ids[keep][ok].tolist(), scores[keep][ok].tolist(), x0[ok].tolist(),
                                      y0[ok].tolist(), x1[ok].tolist(), y1[ok].tolist()):
            out.append(_Raw(int(c), float(sc), a, b, cc, d))
        return out

    # ---------------------------------------------------------------- dedupe / colour

    @staticmethod
    def _centre(it: _Raw) -> Tuple[float, float]:
        return (it.x0 + it.x1) / 2.0, (it.y0 + it.y1) / 2.0

    def merge_duplicates(self, items: Sequence[_Raw]) -> List[_Raw]:
        """Drop the second, third, ... circle drawn on ONE egg.

        IoU NMS cannot do this. Two boxes on the same egg are offset by a few pixels and their IoU
        lands around 0.3-0.5, so some survive the 0.30 threshold and some do not — which is exactly
        the "two or three circles on one egg" artefact. Two DIFFERENT eggs that touch overlap by
        ~0.04 and their centres are a full diameter apart.

        So the test is not overlap but DISTANCE: two boxes of the same class whose centres are
        within `dedupe_dist` diameters of each other, and whose sizes are within `dedupe_ratio` of
        each other, are the same egg. Measured on the device3 frame, at 0.45 this removes the
        duplicate circles without merging a single pair of neighbouring eggs.

        The higher-confidence box wins: the model is more sure of that one, and its box is the one
        drawn.
        """
        if self.dedupe_dist <= 0 or len(items) < 2:
            return list(items)
        order = sorted(items, key=lambda it: it.conf, reverse=True)
        # Same greedy pass as one loop per pair, with the inner loop over the kept boxes in numpy:
        # ~180 eggs a frame made the pure-Python pairs a measurable slice of the cycle (BUG-0917).
        n = len(order)
        cls = np.array([it.cls for it in order])
        cx = np.array([(it.x0 + it.x1) / 2.0 for it in order])
        cy = np.array([(it.y0 + it.y1) / 2.0 for it in order])
        side = np.maximum(1e-6, np.array([((it.x1 - it.x0) + (it.y1 - it.y0)) / 2.0 for it in order]))
        kept_idx = np.empty(n, dtype=np.int64)
        nk = 0
        for i in range(n):
            k = kept_idx[:nk]
            if nk:
                big = np.maximum(side[i], side[k])
                dup = ((cls[k] == cls[i])
                       & (np.hypot(cx[k] - cx[i], cy[k] - cy[i]) <= self.dedupe_dist * big)
                       # a much bigger box is a different object, not a second look
                       & (np.minimum(side[i], side[k]) / big >= (1.0 - self.dedupe_ratio)))
                if dup.any():
                    continue
            kept_idx[nk] = i
            nk += 1
        return [order[i] for i in kept_idx[:nk]]

    def egg_ratio(self, frame_bgr: np.ndarray, it: _Raw) -> float:
        """How much of the box looks like BELT rather than like an egg.

        The scene is white eggs on a saturated blue belt. A detector box that lands on bare belt is
        mostly saturated blue; a real egg is mostly not. That is the discriminator that survives
        shadow — a brightness test does not (measured: a "bright and unsaturated" test at V>140
        rejected 84 of 220 candidates, and most of those 84 were real eggs lying in the shadow of
        the pile, while the belt boxes it kept were the bright ones).

        Two modes, because the two scenes are not the same:
          `belt` (default) — the fraction of the box that is saturated blue. Reject it when it is
                             over `max_ratio` (0.5). This is the egg line's discriminator.
          `white`           — the fraction of the box that is bright AND unsaturated. Reject it when
                             it is under `min_ratio`. This is the "white egg" one, for a scene whose
                             eggs are white and whose belt is not blue.

        It is a property of THIS scene, so it stays opt-in (`color_filter` in the profile) and off by
        default: on a brown-egg line or a candling rig the numbers mean nothing.
        """
        cf = self.color_filter or {}
        mode = str(cf.get('mode', 'belt')).lower()
        h, w = frame_bgr.shape[:2]
        x0, y0 = int(max(0, it.x0)), int(max(0, it.y0))
        x1, y1 = int(min(w, it.x1)), int(min(h, it.y1))
        if x1 - x0 < 3 or y1 - y0 < 3:
            return 1.0
        hsv = cv2.cvtColor(frame_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0].astype(np.float32)
        sat = hsv[:, :, 1].astype(np.float32)
        val = hsv[:, :, 2].astype(np.float32)
        if mode == 'white':
            v_min = float(cf.get('v_min', 140.0))
            s_max = float(cf.get('s_max', 70.0))
            return float(((val > v_min) & (sat < s_max)).mean())
        s_min = float(cf.get('s_min', 120.0))
        h_min = float(cf.get('h_min', 90.0))
        h_max = float(cf.get('h_max', 130.0))
        return float(((sat > s_min) & (hue > h_min) & (hue < h_max)).mean())


    # ---------------------------------------------------------------- public

    def detect(self, frame_bgr: np.ndarray) -> List[Detection]:
        h, w = frame_bgr.shape[:2]
        tiles = self._tiles(w, h)
        raws: List[_Raw] = []
        protos_keep: List[np.ndarray] = []
        for (x0, y0, x1, y1) in tiles:
            crop = frame_bgr[y0:y1, x0:x1]
            if crop.size == 0 or min(crop.shape[:2]) < 8:
                continue
            head, rx, ry, protos = self._forward(crop)
            raws.extend(self._decode(head, rx, ry, x0, y0, (h, w)))
            if protos is not None:
                protos_keep.append(protos)
            if self.flip_tta:
                # The same eggs, seen from the other side. A model that missed an egg in a crowd
                # often finds it in the mirrored crop, because the neighbours it was confused by are
                # on the other side of it now. Costs a second forward per tile and is merged by the
                # same NMS, so a box found twice is one box.
                fw_crop = crop.shape[1]
                head_f, _, _, protos_f = self._forward(cv2.flip(crop, 1))
                for it in self._decode(head_f, rx, ry, x0, y0, (h, w)):
                    # undo the flip: x' = crop_w - x
                    raws.append(_Raw(it.cls, it.conf, x0 + fw_crop - it.x1, it.y0,
                                      x0 + fw_crop - it.x0, it.y1))
        if not raws:
            return []
        kept = nms(raws, self.min_conf, self.nms_iou)

        # sliver filter + colour validator, on the raw boxes so the class id survives
        surviving: List[_Raw] = []
        for it in kept:
            bw = float(it.x1 - it.x0)
            bh = float(it.y1 - it.y0)
            side = min(bw, bh)
            aspect = max(bw, bh) / max(1e-6, side)
            if side < self.min_side or aspect > self.max_aspect:
                continue      # a tile-border sliver, not an egg (see module docstring)
            if self.color_filter:
                mode = str(self.color_filter.get('mode', 'belt')).lower()
                ratio = self.egg_ratio(frame_bgr, it)
                if mode == 'white':
                    need = float(self.color_filter.get('min_ratio', 0.55))
                    if ratio < need:
                        continue      # not enough white in it: not an egg
                else:
                    need = float(self.color_filter.get('max_ratio', 0.5))
                    if ratio > need:
                        continue      # mostly bare belt: not an egg
            surviving.append(it)

        surviving = self.merge_duplicates(surviving)

        out: List[Detection] = []
        for it in surviving:
            bw = float(it.x1 - it.x0)
            bh = float(it.y1 - it.y0)
            name = self.labels[it.cls] if self.labels else self.label
            det = Detection(name, round(it.conf, 3), (it.x0, it.y0, bw, bh))
            # the overlay draws this ellipse: it is the box fitted to the egg, not the LoG response
            det.shape = {'ellipse': [round((it.x0 + it.x1) / 2, 1), round((it.y0 + it.y1) / 2, 1),
                                     round(bw, 1), round(bh, 1), 0.0]}
            out.append(det)
        out.sort(key=lambda d: d.bbox[0])
        return out