import json

import cv2
import numpy as np
import pytest

from shared.src.lib.drone.perception import (ArucoDetector, CocoDetector, SimColorDetector, VlmDetector,
                                             parse_json_object)
from shared.src.lib.drone.sim.world import CLASS_COLORS


def frame_with_marker(marker_id, size=80, at=(300, 200)):
    img = np.full((720, 960, 3), 120, np.uint8)
    m = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), marker_id, size)
    m = cv2.copyMakeBorder(m, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    x, y = at
    img[y:y + m.shape[0], x:x + m.shape[1]] = cv2.cvtColor(m, cv2.COLOR_GRAY2BGR)
    return img


def test_aruco_matches_only_target_id():
    f = frame_with_marker(2)
    d = ArucoDetector().detect(f, "2")
    assert d and d.source == "aruco" and abs(d.bbox[0] - 310) < 6 and d.confidence > 0.7
    assert ArucoDetector().detect(f, "1") is None
    assert ArucoDetector().detect(np.full((720, 960, 3), 120, np.uint8), "2") is None


def test_aruco_min_side():
    f = frame_with_marker(2, size=24)
    assert ArucoDetector(min_side_px=8).detect(f, "2")
    assert ArucoDetector(min_side_px=40).detect(f, "2") is None


def test_color_detector_finds_largest_blob_of_class_colour():
    f = np.full((720, 960, 3), 110, np.uint8)
    f[:] = (110, 100, 90)
    c = np.array(CLASS_COLORS["sofa"], np.uint8)
    cv2.rectangle(f, (100, 300), (400, 500), tuple(int(v) for v in c), -1)
    cv2.rectangle(f, (700, 100), (720, 120), tuple(int(v) for v in c), -1)  # speck below min area
    d = SimColorDetector().detect(f, "sofa")
    assert d and abs(d.bbox[0] - 100) <= 2 and d.bbox[2] >= 295 and d.confidence == 1.0
    assert SimColorDetector().detect(f, "tv") is None
    assert SimColorDetector().detect(f, "unknown") is None


def test_color_confidence_scales_with_area():
    f = np.full((720, 960, 3), (110, 100, 90), np.uint8)
    cv2.rectangle(f, (100, 100), (140, 140), tuple(int(v) for v in CLASS_COLORS["tv"]), -1)
    d = SimColorDetector().detect(f, "tv")
    assert d and 0.2 < d.confidence < 1.0


def test_coco_needs_model(monkeypatch):
    monkeypatch.delenv("DRONE_COCO_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="DRONE_COCO_MODEL"):
        CocoDetector()


def test_parse_json_object_is_tolerant():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure! {"visible": true, "confidence": 0.9} done') == {"visible": True, "confidence": 0.9}
    assert parse_json_object("nothing") is None
    assert parse_json_object("{broken") is None


def test_vlm_detector_parses_and_counts_tokens(monkeypatch):
    from shared.src.lib.ai import gateway
    answer = {"success": True, "usage": {"prompt_tokens": 100, "completion_tokens": 7},
              "content": "```json\n" + json.dumps({"visible": True, "confidence": 0.8, "bbox": [10, 20, 30, 40],
                                                    "note": "sofa"}) + "\n```"}
    calls = []
    monkeypatch.setattr(gateway, "complete", lambda usage, prompt, **kw: calls.append(usage) or answer)
    v = VlmDetector()
    d = v.detect(np.zeros((720, 960, 3), np.uint8), "sofa")
    assert calls == ["vision.drone"]
    assert d and d.bbox == (15, 30, 45, 60) and d.source == "vlm"  # reported on the 640 px copy, scaled back to 960
    assert (v.ai_calls, v.tokens_in, v.tokens_out) == (1, 100, 7)
    assert v.last_note == "sofa"
    answer["content"] = '{"visible": false, "confidence": 0.1, "bbox": null}'
    assert v.detect(np.zeros((720, 960, 3), np.uint8), "sofa") is None
    answer["success"] = False
    assert v.detect(np.zeros((720, 960, 3), np.uint8), "sofa") is None


def test_vlm_sends_a_640px_jpeg(monkeypatch):
    import base64
    from shared.src.lib.ai import gateway
    sent = {}

    def fake(usage, prompt, image_b64=None, **kw):
        sent["img"] = cv2.imdecode(np.frombuffer(base64.b64decode(image_b64), np.uint8), cv2.IMREAD_COLOR)
        return {"success": True, "content": "{\"visible\": false}", "usage": {}}

    monkeypatch.setattr(gateway, "complete", fake)
    VlmDetector().detect(np.zeros((720, 960, 3), np.uint8), "sofa")
    assert sent["img"].shape[1] == 640
