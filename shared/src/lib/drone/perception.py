"""
Perception for the drone demos: every detector answers detect(frame, target) -> Detection | None.

ArucoDetector     marker id of the hider drone (target = id as string, e.g. '2')
SimColorDetector  colour-class detector for the objects rendered by the simulator
CocoDetector      COCO object detector on hardware (cv2.dnn, model path from DRONE_COCO_MODEL)
VlmDetector       vision LLM judge (usage vision.drone), the optional alternative
"""

import base64
import json
import os
import re
import threading
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple

import cv2
import numpy as np


@dataclass
class Detection:
    label: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x, y, w, h
    source: str


class Detector(Protocol):
    name: str

    def detect(self, frame: np.ndarray, target: str) -> Optional[Detection]: ...


def draw_detection(frame: np.ndarray, det: Optional[Detection]) -> np.ndarray:
    """Copy of the frame with the detection box drawn on it."""
    out = frame.copy()
    if det is not None:
        x, y, w, h = det.bbox
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 3)
        cv2.putText(out, f"{det.label} {det.confidence:.2f}", (x, max(y - 8, 14)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return out


class ArucoDetector:
    name = "aruco"

    def __init__(self, min_side_px: float = 8.0):
        self.min_side_px = min_side_px
        self._detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
                                                 cv2.aruco.DetectorParameters())
        self._lock = threading.Lock()

    def detect(self, frame: np.ndarray, target: str) -> Optional[Detection]:
        with self._lock:
            corners, ids, _ = self._detector.detectMarkers(frame)
        if ids is None:
            return None
        best = None
        for c, i in zip(corners, ids.flatten()):
            if str(int(i)) != str(target):
                continue
            x, y, w, h = cv2.boundingRect(c.reshape(-1, 2).astype(np.float32))
            side = min(w, h)
            if side < self.min_side_px:
                continue
            if best is None or w * h > best.bbox[2] * best.bbox[3]:
                best = Detection(f"marker {target}", min(1.0, 0.7 + side / 100.0), (x, y, w, h), self.name)
        return best


class SimColorDetector:
    """Largest blob of the target class's colour. HSV hue band so the renderer's depth shading still matches."""
    name = "color"

    def __init__(self, min_area: int = 600, full_conf_area: int = 4000, hue_tol: int = 8, min_side: int = 15):
        from .sim.world import CLASS_COLORS
        self.colors = CLASS_COLORS
        self.min_area = min_area
        self.full_conf_area = full_conf_area
        self.hue_tol = hue_tol
        self.min_side = min_side  # a sliver of an object at the frame edge is not a sighting

    def detect(self, frame: np.ndarray, target: str) -> Optional[Detection]:
        bgr = self.colors.get(target)
        if bgr is None:
            return None
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h0, _, _ = cv2.cvtColor(np.uint8([[bgr]]), cv2.COLOR_BGR2HSV)[0, 0]
        hue = hsv[:, :, 0].astype(int)
        dh = np.minimum(np.abs(hue - int(h0)), 180 - np.abs(hue - int(h0)))
        mask = ((dh <= self.hue_tol) & (hsv[:, :, 1] > 110) & (hsv[:, :, 2] > 45)).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        if n <= 1:
            return None
        k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        area = int(stats[k, cv2.CC_STAT_AREA])
        if area < self.min_area or min(stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT]) < self.min_side:
            return None
        bbox = tuple(int(v) for v in stats[k, :4])
        return Detection(target, min(1.0, area / self.full_conf_area), bbox, self.name)


COCO_CLASSES = [c for c in "person|bicycle|car|motorcycle|airplane|bus|train|truck|boat|traffic light|fire hydrant|"
                "stop sign|parking meter|bench|bird|cat|dog|horse|sheep|cow|elephant|bear|zebra|giraffe|backpack|"
                "umbrella|handbag|tie|suitcase|frisbee|skis|snowboard|sports ball|kite|baseball bat|baseball glove|"
                "skateboard|surfboard|tennis racket|bottle|wine glass|cup|fork|knife|spoon|bowl|banana|apple|sandwich|"
                "orange|broccoli|carrot|hot dog|pizza|donut|cake|chair|couch|potted plant|bed|dining table|toilet|tv|"
                "laptop|mouse|remote|keyboard|cell phone|microwave|oven|toaster|sink|refrigerator|book|clock|vase|"
                "scissors|teddy bear|hair drier|toothbrush".split("|")]
COCO_ALIASES = {"sofa": "couch", "plant": "potted plant", "table": "dining table", "television": "tv"}


class CocoDetector:
    """YOLOv8-style ONNX model through cv2.dnn. Nothing is downloaded: DRONE_COCO_MODEL must point at a file."""
    name = "coco"

    def __init__(self, model_path: Optional[str] = None, min_conf: float = 0.35, input_size: int = 640):
        path = model_path or os.environ.get("DRONE_COCO_MODEL", "")
        if not path or not os.path.isfile(path):
            raise RuntimeError("CocoDetector needs a COCO ONNX model: set DRONE_COCO_MODEL to its path "
                               "(nothing is downloaded automatically)")
        self.net = cv2.dnn.readNetFromONNX(path)
        self.min_conf = min_conf
        self.size = input_size
        self._lock = threading.Lock()

    def detect(self, frame: np.ndarray, target: str) -> Optional[Detection]:
        label = COCO_ALIASES.get(target, target)
        if label not in COCO_CLASSES:
            return None
        cid = COCO_CLASSES.index(label)
        h, w = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (self.size, self.size), swapRB=True)
        with self._lock:
            self.net.setInput(blob)
            out = self.net.forward()
        pred = np.squeeze(out)
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T  # (anchors, 4 + classes)
        scores = pred[:, 4 + cid]
        best = None
        for i in np.where(scores >= self.min_conf)[0]:
            cx, cy, bw, bh = pred[i, :4]
            x, y = int((cx - bw / 2) * w / self.size), int((cy - bh / 2) * h / self.size)
            box = (max(x, 0), max(y, 0), int(bw * w / self.size), int(bh * h / self.size))
            if best is None or scores[i] > best.confidence:
                best = Detection(target, float(scores[i]), box, self.name)
        return best


class VlmDetector:
    name = "vlm"
    costly = True  # one paid call per frame: the scan agent only shows it scan frames
    reliable_bbox = False  # a model's box is a rough guess (or the whole frame): no edge-cut checks on it
    SEND_WIDTH = 640

    def __init__(self, min_conf: float = 0.5, usage: str = "vision.drone", scene_hint: str = ""):
        self.min_conf = min_conf
        self.usage = usage
        # The simulator draws furniture as plain coloured boxes, which a VLM rightly does not call a
        # sofa; sim runs pass sim_scene_hint() so the plumbing can be exercised. Real frames need none.
        self.scene_hint = scene_hint
        self.ai_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.last_note = ""
        self.models: set = set()
        self._lock = threading.Lock()

    def detect(self, frame: np.ndarray, target: str) -> Optional[Detection]:
        from shared.src.lib.ai import gateway
        full_w, full_h = frame.shape[1], frame.shape[0]
        small = frame
        if full_w > self.SEND_WIDTH:  # a 640 px JPEG is plenty for "is a sofa in view" and costs far fewer tokens
            small = cv2.resize(frame, (self.SEND_WIDTH, int(full_h * self.SEND_WIDTH / full_w)))
        scale = full_w / small.shape[1]
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return None
        what = (f"a small drone carrying a black-and-white square marker (id {target})" if target.isdigit()
                else f"a {target}")
        prompt = (f"A drone camera frame of size {small.shape[1]}x{small.shape[0]} px. Is {what} clearly visible "
                  f"in it? Answer with JSON only: {{\"visible\": bool, \"confidence\": 0..1, "
                  f"\"bbox\": [x, y, w, h] in pixels or null, \"note\": short string}}.")
        if self.scene_hint:
            prompt = f"{self.scene_hint}\n{prompt}"
        res = gateway.complete(self.usage, prompt, image_b64=base64.b64encode(buf.tobytes()).decode(),
                               media_type="image/jpeg", max_tokens=300)
        with self._lock:
            self.ai_calls += 1
            u = res.get("usage") or {}
            self.tokens_in += int(u.get("prompt_tokens", 0))
            self.tokens_out += int(u.get("completion_tokens", 0))
            if res.get("model"):
                self.models.add(f"{res.get('provider_used', '?')}/{res['model']}")
        self.last_note = ""
        if not res.get("success"):
            return None
        data = parse_json_object(res.get("content", ""))
        if not data:
            return None
        self.last_note = str(data.get("note", ""))
        if not data.get("visible"):
            return None
        try:
            conf = float(data.get("confidence", 0))
        except (TypeError, ValueError):
            return None
        if conf < self.min_conf:
            return None
        bbox = data.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                bbox = tuple(int(float(v) * scale) for v in bbox)
            except (TypeError, ValueError):
                bbox = (0, 0, full_w, full_h)
        else:
            bbox = (0, 0, full_w, full_h)
        return Detection(target, conf, bbox, self.name)


def sim_scene_hint() -> str:
    """How the simulator draws each class, for VlmDetector on simulated frames."""
    from .sim.world import CLASS_COLORS
    names = {(30, 30, 220): "red", (220, 80, 0): "blue", (0, 190, 0): "green", (0, 215, 235): "yellow",
             (210, 0, 210): "magenta"}
    boxes = ", ".join(f"a {cls} is a {names.get(tuple(c), str(c))} box" for cls, c in CLASS_COLORS.items())
    return (f"This is a simulated room rendered with plain boxes: {boxes}; another drone is a small dark bar "
            f"with a black-and-white square marker above it.")


def parse_json_object(text: str) -> Optional[dict]:
    """First JSON object in an LLM answer (tolerates fences and chatter)."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
