"""Egg condition classifier for the img service (TASK-90 goal 9): type `egg_classify`, a small CNN as ONNX through cv2.dnn.

The model file is not in git (it is trained locally from a CC-BY dataset, see docs/agent/devices/MONITOR_PROFILES.md and
scripts/train_egg_classifier.py) and is found through the env var named by `model_env`. The classes are whatever the model
was trained with and are listed in the manifest (`classes`): today good / bad (the only login-free dataset with labels),
clean / dirty / cracked drops in when a model for them exists, with no code change.

An attributor: `classify_det(frame, detection) -> (label, {class: probability})`. The pipeline lets it vote at every sample
of a track and averages the probabilities of the votes for the focus panel.
"""
import os
from typing import Dict, Optional, Sequence, Tuple

import cv2
import numpy as np

INPUT = 64
MARGIN = 0.12


def crop_for_model(frame_bgr: np.ndarray, bbox, size: int = INPUT) -> np.ndarray:
    """The crop the model sees: the egg's box with a 12 % margin, scaled to fit size x size keeping the aspect, black padding
    (the training script uses the same function, so training and running cannot drift apart)."""
    x, y, w, h = bbox
    mx, my = w * MARGIN, h * MARGIN
    x0, y0 = int(max(0, x - mx)), int(max(0, y - my))
    x1, y1 = int(min(frame_bgr.shape[1], x + w + mx)), int(min(frame_bgr.shape[0], y + h + my))
    crop = frame_bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return np.zeros((size, size, 3), np.uint8)
    r = min(size / crop.shape[1], size / crop.shape[0])
    nw, nh = max(1, int(round(crop.shape[1] * r))), max(1, int(round(crop.shape[0] * r)))
    canvas = np.zeros((size, size, 3), np.uint8)
    ox, oy = (size - nw) // 2, (size - nh) // 2
    canvas[oy:oy + nh, ox:ox + nw] = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
    return canvas


class EggClassify:
    """type: egg_classify — keys: attr (default 'condition'), classes, model_env (default MONITOR_EGG_MODEL)."""

    def __init__(self, classes: Sequence[str] = ('good', 'bad'), attr: str = 'condition', model_env: str = 'MONITOR_EGG_MODEL',
                 model_path: Optional[str] = None):
        self.attr = attr
        self.classes = tuple(classes)
        path = model_path or os.getenv(model_env, '')
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(
                f"egg_classify: model file not found ({model_env}={path!r}). Train it with scripts/train_egg_classifier.py "
                f"(data stays outside git) and set {model_env}.")
        self.net = cv2.dnn.readNetFromONNX(path)

    def probabilities(self, frame_bgr: np.ndarray, bbox) -> Dict[str, float]:
        blob = cv2.dnn.blobFromImage(crop_for_model(frame_bgr, bbox), 1.0 / 255.0, (INPUT, INPUT), (0, 0, 0), swapRB=True)
        self.net.setInput(blob)
        p = self.net.forward().reshape(-1)
        if p.shape[0] != len(self.classes):
            raise ValueError(f"model has {p.shape[0]} outputs, the manifest lists {len(self.classes)} classes")
        return {c: float(v) for c, v in zip(self.classes, p)}

    def classify_det(self, frame_bgr: np.ndarray, det) -> Tuple[str, Dict[str, float]]:
        probs = self.probabilities(frame_bgr, det.bbox)
        return max(probs, key=probs.get), probs

    def classify(self, frame_bgr: np.ndarray, bbox) -> str:
        probs = self.probabilities(frame_bgr, bbox)
        return max(probs, key=probs.get)
