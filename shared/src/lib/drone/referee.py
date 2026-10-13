"""
Referee: the only judge of a win. On a claim it takes a fresh frame from the claiming drone and runs
its own verifier, which is configured stricter than the agent's own perception.
"""

import time
from typing import Optional, Tuple

import numpy as np

from .io import DroneIO
from .perception import Detector, draw_detection


EDGE_PX = 3  # a target touching the left/right frame border is only partly in view


class Referee:
    def __init__(self, detector: Detector, min_confidence: float = 0.0, attempts: int = 2, settle_s: float = 0.3):
        self.detector = detector
        self.min_confidence = min_confidence
        self.attempts = attempts
        self.settle_s = settle_s

    def verify(self, io: DroneIO, target: str) -> Tuple[dict, Optional[np.ndarray]]:
        """(verdict, annotated frame). verdict: confirmed, confidence, bbox, label, source, reason."""
        time.sleep(self.settle_s)
        verdict = {"confirmed": False, "confidence": 0.0, "bbox": None, "label": target,
                   "source": getattr(self.detector, "name", "?"), "reason": "no frame"}
        last: Optional[np.ndarray] = None
        for _ in range(self.attempts):
            frame = io.frame(fresh=True)
            if frame is None:
                continue
            last = frame
            det = self.detector.detect(frame, target)
            if det is None:
                verdict["reason"] = f"{target} not found in a fresh frame"
                continue
            verdict.update(confidence=round(det.confidence, 3), bbox=list(det.bbox), label=det.label,
                           source=det.source)
            x, y, w, h = det.bbox
            fw = frame.shape[1]
            if getattr(self.detector, "reliable_bbox", True) and (x <= EDGE_PX or x + w >= fw - EDGE_PX):  # (a near object runs off the bottom naturally)
                verdict["reason"] = f"{target} is cut off by the frame edge, not clearly in view"
                continue
            if det.confidence >= self.min_confidence:
                verdict.update(confirmed=True, reason="confirmed")
                return verdict, draw_detection(frame, det)
            verdict["reason"] = f"confidence {det.confidence:.2f} below referee floor {self.min_confidence:.2f}"
        return verdict, last
