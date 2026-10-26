"""Classical egg detector for a uniform belt (TASK-90 goal 9): type `egg_detect`, no model.

Eggs are found as bright blobs on a dark background: brightness (the maximum colour channel), blur, Otsu threshold with a floor,
open and close, contours, an ellipse fitted to each. This is what a candling lamp or a back-lit belt gives; on a textured
or bright belt it will need another detector (a trained one: the pipeline takes any detector that returns boxes).

Each detection carries `shape`: {'ellipse': [cx, cy, ax, ay, angle_deg]} (centre, FULL axis lengths, rotation) so the overlay
can outline the egg itself, and `size_mm` (major axis in millimetres) when the manifest gives `px_per_mm`.

Two eggs that touch come out of the threshold as ONE blob, and a belt of them is then counted as a handful of long tracks
instead of one count per egg (measured on real footage: one "egg" alive for the whole 29 s clip). Cutting such a blob back
into eggs again was tried (distance-transform peaks, erosion markers, Voronoi split) and NONE of it produced egg-shaped
parts, so there is no split option here: on real footage `method: blob` is the answer, because a blob detector finds each
egg by its own local contrast and never merges two of them in the first place.
"""
from typing import List, Optional

import cv2
import numpy as np

from monitor.analyzers.coco_detect import Detection


class EggDetect:
    """type: egg_detect — keys: min_area_frac, max_area_frac, floor, px_per_mm, label, close_k, method, blob_*."""

    def __init__(self, min_area_frac: float = 0.001, max_area_frac: float = 0.6, floor: int = 60,
                 px_per_mm: Optional[float] = None, label: str = 'egg', min_fill: float = 0.55,
                 close_k: int = 3,
                 method: str = 'brightness', blob_min_threshold: int = 10, blob_max_threshold: int = 220,
                 blob_min_area_frac: float = 0.0002, blob_max_area_frac: float = 0.02,
                 blob_min_circularity: float = 0.45, blob_min_convexity: float = 0.80,
                 detect_width: Optional[int] = None):
        self.min_area_frac = min_area_frac
        self.max_area_frac = max_area_frac
        self.floor = floor
        self.px_per_mm = px_per_mm
        self.label = label
        self.min_fill = min_fill   # contour area / fitted ellipse area: a blob that is not egg-shaped is not an egg
        # CLOSE joins an egg with the plate or holder it sits on (candling line), but on a belt of touching eggs a big
        # kernel welds a whole pile into one blob before `split` ever runs. close_k is in units of the open kernel;
        # 0 disables it. Default 3 = the original 3*k kernel.
        self.close_k = close_k
        self.method = method
        self.blob_min_threshold = blob_min_threshold
        self.blob_max_threshold = blob_max_threshold
        self.blob_min_area_frac = blob_min_area_frac
        self.blob_max_area_frac = blob_max_area_frac
        self.blob_min_circularity = blob_min_circularity
        self.blob_min_convexity = blob_min_convexity
        # Detect on a downscaled copy and scale the boxes back (BUG-0836). An egg is 30-70 px wide at 720p, so
        # half resolution keeps every one of them (measured: 71 -> 69 boxes per frame, 97 %) for 2.4x less CPU
        # (57 -> 24 ms). The overlay lag is analysis period + analysis time, so a cheaper detector is what buys
        # a higher sample_hz, and a higher sample_hz is what makes the boxes sit on the eggs. None = full frame.
        self.detect_width = detect_width
        self._blob = None

    def _detect_blob(self, frame_bgr: np.ndarray) -> List[Detection]:
        """One box per egg from a LoG blob detector, for eggs that are NOT brighter than their background.

        The threshold path needs a bright egg on a dark belt (a candling lamp). Real footage has brown eggs on a grey
        roller and white eggs on a blue belt, and a threshold either welds a whole row into one blob or locks onto the
        machine. A blob detector looks for a roundish, convex, locally contrasting region instead, so it gives ONE box
        per egg there; recall is lower than a threshold on a proper candling shot, which is what `brightness` is for.
        """
        h, w = frame_bgr.shape[:2]
        area = float(h * w)
        if self._blob is None:
            p = cv2.SimpleBlobDetector_Params()
            p.minThreshold = self.blob_min_threshold
            p.maxThreshold = self.blob_max_threshold
            p.filterByColor = True
            p.blobColor = 255                       # grey image, so bright AND dark eggs are candidates
            p.filterByArea = True
            p.minArea = max(16.0, self.blob_min_area_frac * area)
            p.maxArea = self.blob_max_area_frac * area
            p.filterByCircularity = True
            p.minCircularity = self.blob_min_circularity
            p.filterByConvexity = True
            p.minConvexity = self.blob_min_convexity
            self._blob = cv2.SimpleBlobDetector_create(p)
        grey = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        out: List[Detection] = []
        for k in self._blob.detect(grey):
            cx, cy = float(k.pt[0]), float(k.pt[1])
            r = max(1.0, float(k.size) / 2.0)
            x, y, bw, bh = cx - r, cy - r, 2 * r, 2 * r
            det = Detection(self.label, round(float(min(1.0, k.size and 1.0)), 3), (x, y, bw, bh))
            det.shape = {'ellipse': [round(cx, 1), round(cy, 1), round(2 * r, 1), round(2 * r, 1), 0.0]}
            if self.px_per_mm:
                det.size_mm = round(2 * r / self.px_per_mm, 1)
            out.append(det)
        out.sort(key=lambda d: d.bbox[0])
        return out

    def detect(self, frame_bgr: np.ndarray) -> List[Detection]:
        if self.method == 'blob':
            # `detect_width` is applied here rather than inside _detect_blob so both methods share it and the
            # boxes are scaled back to frame pixels by the same code path (BUG-0836).
            if self.detect_width and frame_bgr.shape[1] > self.detect_width:
                h, w = frame_bgr.shape[:2]
                s = self.detect_width / float(w)
                small = cv2.resize(frame_bgr, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_AREA)
                dets = self._detect_blob(small)
                inv = 1.0 / s
                for d in dets:
                    d.bbox = [v * inv for v in d.bbox]
                    if getattr(d, 'shape', None) and 'ellipse' in d.shape:
                        d.shape['ellipse'] = [v * inv if i < 4 else v for i, v in enumerate(d.shape['ellipse'])]
                return dets
            return self._detect_blob(frame_bgr)
        h, w = frame_bgr.shape[:2]
        width = min(self.detect_width, w) if self.detect_width else 640
        scale = 1.0 if max(h, w) <= width else width / float(max(h, w))   # find on a small copy, report in frame pixels
        small = cv2.resize(frame_bgr, (int(w * scale), int(h * scale))) if scale != 1.0 else frame_bgr
        v = cv2.GaussianBlur(small.max(axis=2), (5, 5), 0)
        t, _ = cv2.threshold(v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        mask = (v > max(t, self.floor)).astype(np.uint8) * 255
        k = max(3, int(round(5 * scale)) | 1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
        if self.close_k:
            # join the egg with the plate or holder it sits on, which lights up as a separate blob under it
            c = self.close_k * k
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((c, c), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        frame_area = float(small.shape[0] * small.shape[1])
        out: List[Detection] = []
        for c in contours:
            det = self._one(mask, c, scale, frame_area)
            if det is not None:
                out.append(det)
        out.sort(key=lambda d: d.bbox[0])
        return out

    def _one(self, mask: np.ndarray, contour, scale: float, frame_area: float) -> Optional[Detection]:
        """The egg of one blob: an ellipse fitted to it, or None when it is too small, too big or not egg-shaped."""
        area = cv2.contourArea(contour)
        if area < self.min_area_frac * frame_area or area > self.max_area_frac * frame_area or len(contour) < 5:
            return None
        (cx, cy), (d1, d2), angle = cv2.fitEllipse(contour)
        ell_area = np.pi * d1 * d2 / 4.0
        fill = area / ell_area if ell_area > 0 else 0.0
        if fill < self.min_fill:
            return None
        x, y, bw, bh = cv2.boundingRect(contour)
        ax, ay = max(d1, d2), min(d1, d2)
        ang = angle if d1 >= d2 else angle + 90.0
        s = 1.0 / scale
        det = Detection(self.label, round(min(1.0, fill), 3), (x * s, y * s, bw * s, bh * s))
        det.shape = {'ellipse': [round(cx * s, 1), round(cy * s, 1), round(ax * s, 1), round(ay * s, 1), round(ang % 180.0, 1)]}
        if self.px_per_mm:
            det.size_mm = round(ax * s / self.px_per_mm, 1)
        return det
