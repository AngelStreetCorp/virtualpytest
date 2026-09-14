#!/usr/bin/env python3
"""
Generic TV UI DOM inference from a screenshot.

Goal:
  Build a deterministic, vision-only DOM-like representation:
    - interactive elements: nav tabs, buttons, cards, rows/menu items, visual focus boxes
    - main focused element
    - predicted remote navigation graph: LEFT/RIGHT/UP/DOWN, OK=ENTER, BACK=UNKNOWN

Inputs: 1280x720 TV screenshots.
Tools: OpenCV + Tesseract. No LLM, no DOM/ADB.

Exports per image:
  <stem>_dom.jpg   visual overlay
  <stem>_dom.json  structured DOM
  <stem>_dom.txt   compact text handoff
"""
from __future__ import annotations

import argparse, json, os, re, sys, importlib.util
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

HERE = Path(__file__).resolve().parent


def _load_optional(name: str, filename: str):
    p = HERE / filename
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, str(p))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod

navmod = _load_optional("ui_nav_fixed", "ui_infer_offline.py")
focusmod = _load_optional("focus_detector", "no_reference_focus_detector.py")

KNOWN_NAV_TOKENS = {
    "home", "tv", "guide", "apps", "replay", "filme", "serien", "movies", "series",
    "aufnahmen", "recordings", "shop", "settings", "profiles", "discover", "entdecken",
    "today", "channels", "radio", "accessibility", "parental", "system", "info",
}

@dataclass
class Element:
    id: str
    type: str       # nav_item, card, button, menu_item, text_item, focus_region
    label: str
    x: float
    y: float
    w: float
    h: float
    row: str = ""
    col: int = -1
    focused: bool = False
    source: str = ""
    score: float = 0.0

    @property
    def cx(self): return self.x + self.w / 2
    @property
    def cy(self): return self.y + self.h / 2
    @property
    def end(self): return self.x + self.w
    @property
    def bottom(self): return self.y + self.h


def slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "item"


def clamp01(v): return max(0.0, min(1.0, float(v)))


def norm_box(box, shape):
    H, W = shape[:2]
    x, y, w, h = box
    return (x / W, y / H, w / W, h / H)


def iou_box(a: Element, b: Tuple[float, float, float, float]) -> float:
    bx, by, bw, bh = b
    ax0, ay0, ax1, ay1 = a.x, a.y, a.end, a.bottom
    bx0, by0, bx1, by1 = bx, by, bx + bw, by + bh
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    return inter / max(1e-9, (a.w * a.h + bw * bh - inter))


def ocr_words(img) -> List[dict]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    up = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(up, config="--psm 11", output_type=Output.DICT)
    H, W = img.shape[:2]
    out = []
    for i, t in enumerate(data["text"]):
        t = (t or "").strip().strip("|_.,:;!()[]{}<>")
        if not t:
            continue
        try:
            conf = float(data["conf"][i])
        except Exception:
            conf = -1.0
        if conf < 10:
            continue
        x = data["left"][i] / 2 / W
        y = data["top"][i] / 2 / H
        w = data["width"][i] / 2 / W
        h = data["height"][i] / 2 / H
        if w < .003 or h < .006:
            continue
        out.append({"text": t, "x": x, "y": y, "w": w, "h": h, "cx": x + w / 2, "cy": y + h / 2, "conf": conf})
    return out


def label_from_words(words: List[dict], box: Tuple[float, float, float, float], below: bool = False) -> str:
    x, y, w, h = box
    selected = []
    if below:
        y0, y1 = y + h, y + h + 0.08
        x0, x1 = x - 0.015, x + w + 0.015
    else:
        y0, y1 = y - 0.01, y + h + 0.015
        x0, x1 = x - 0.015, x + w + 0.015
    for z in words:
        if x0 <= z["cx"] <= x1 and y0 <= z["cy"] <= y1:
            selected.append(z)
    if not selected:
        return ""
    selected.sort(key=lambda z: (round(z["cy"] / 0.025), z["x"]))
    # Keep up to the first 2 nearby lines; avoids collecting whole paragraphs.
    lines = []
    for z in selected:
        placed = False
        for line in lines:
            if abs(line[0]["cy"] - z["cy"]) < 0.025:
                line.append(z); placed = True; break
        if not placed:
            lines.append([z])
    lines = lines[:2]
    parts = []
    for line in lines:
        line.sort(key=lambda z: z["x"])
        parts.append(" ".join(z["text"] for z in line))
    return " / ".join(parts)[:80]



def clean_crop_label(txt: str) -> str:
    txt = (txt or "").strip().replace("\n", " ")
    txt = re.sub(r"[^A-Za-z0-9+& .:_-]+", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    # Drop common leading icon OCR noise before real labels.
    txt = re.sub(r"^(C |P |D |a |Pm |Dp |[>•▶]+ )+", "", txt).strip()
    low = txt.lower()
    if "replay" in low: return "Replay"
    if "play" in low or "piay" in low or "piay" in low: return "Play"
    if "audio" in low: return "Audio"
    return txt[:80]


def ocr_crop_label(img, pix_box: Tuple[int, int, int, int]) -> str:
    x, y, w, h = pix_box
    H, W = img.shape[:2]
    pad = max(2, int(min(w, h) * 0.08))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return ""
    variants = [crop, cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)]
    best = ""
    for im in variants:
        up = cv2.resize(im, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        for cfg in ["--psm 8", "--psm 7", "--psm 6"]:
            try:
                txt = clean_crop_label(pytesseract.image_to_string(up, config=cfg))
            except Exception:
                txt = ""
            if len(txt) > len(best):
                best = txt
    return best

def should_use_known_nav(words: List[dict]) -> bool:
    text = {re.sub(r"[^a-z]+", "", w["text"].lower()) for w in words if w["y"] < 0.20}
    # Avoid app-specific screens like Apple TV+/Netflix: require at least 2 known operator-UI
    # nav tokens in top bands.
    return len(text & KNOWN_NAV_TOKENS) >= 2


def extract_nav(path: str, img, words: List[dict]) -> Tuple[str, List[Element]]:
    if navmod is None or not should_use_known_nav(words):
        return infer_screen_title(words), []
    try:
        r = navmod.extract(path)
    except Exception:
        return infer_screen_title(words), []
    items = []
    # Reject hallucinated nav if none of the returned labels roughly appear in OCR top text.
    top_text = " ".join(w["text"].lower() for w in words if w["y"] < 0.22)
    match_count = 0
    for it in r.get("items", []):
        lbl = it.get("label", "")
        if not lbl:
            continue
        first = re.sub(r"[^a-z]+", "", lbl.lower().split()[0])
        if first and first in re.sub(r"[^a-z]+", " ", top_text):
            match_count += 1
        items.append(Element(
            id=f"nav_{it['id']}", type="nav_item", label=lbl,
            x=it["x"], y=it["y"], w=it["w"], h=it["h"], row="nav", col=len(items),
            focused=bool(it.get("focused")), source="known_nav"))
    if len(items) >= 2 and match_count >= 1:
        return r.get("screen_id") or infer_screen_title(words), items
    return infer_screen_title(words), []


def infer_screen_title(words: List[dict]) -> str:
    tops = [w for w in words if w["y"] < 0.12 and w["x"] < 0.35 and len(w["text"]) >= 2]
    if tops:
        tops.sort(key=lambda z: (z["y"], z["x"]))
        return slug("_".join(z["text"] for z in tops[:3]))
    return "unknown"


def merge_boxes(boxes: List[Tuple[int, int, int, int]], overlap_thr=0.55) -> List[Tuple[int, int, int, int]]:
    boxes = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
    kept = []
    for b in boxes:
        x, y, w, h = b
        area = w * h
        keep = True
        for k in kept:
            x2, y2, w2, h2 = k
            ix0, iy0 = max(x, x2), max(y, y2)
            ix1, iy1 = min(x + w, x2 + w2), min(y + h, y2 + h2)
            inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
            if inter / max(1, min(area, w2 * h2)) > overlap_thr:
                keep = False; break
        if keep:
            kept.append(b)
    return sorted(kept, key=lambda b: (b[1], b[0]))


def detect_visual_rects(img) -> List[Tuple[int, int, int, int, str, float]]:
    """Generic visual container detector: cards, buttons, menu rows, tiles."""
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    edges = cv2.Canny(gray, 45, 135)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if area < 1800 or w < 28 or h < 22:
            continue
        if w > .75 * W or h > .60 * H:
            continue
        asp = w / float(h)
        if not (0.35 <= asp <= 12.5):
            continue
        # Reject tiny text-only contours and very thin lines.
        if h < 18 or (h < 35 and asp > 8):
            continue
        roi = gray[y:y+h, x:x+w]
        sat = hsv[y:y+h, x:x+w, 1]
        edge_density = float(np.mean(edges[y:y+h, x:x+w] > 0))
        mean_v = float(np.mean(roi))
        mean_s = float(np.mean(sat))
        # Classify roughly.
        if h < 70 and asp > 2.0:
            typ = "button_or_row"
        elif 0.7 <= asp <= 1.45 and 45 <= w <= 260:
            typ = "tile"
        else:
            typ = "card"
        score = edge_density + mean_s / 500 + mean_v / 1000
        boxes.append((x, y, w, h, typ, score))
    boxes2 = merge_boxes([(x, y, w, h) for x, y, w, h, _, _ in boxes])
    # Rebuild with type by nearest original.
    out = []
    for b in boxes2:
        x, y, w, h = b
        best = min(boxes, key=lambda t: abs(t[0]-x)+abs(t[1]-y)+abs(t[2]-w)+abs(t[3]-h))
        # screen content only, but allow buttons in hero.
        if y < 0.12 * H and h < 45:
            continue
        out.append((x, y, w, h, best[4], best[5]))
    return out


def elements_from_visuals(img, words: List[dict], existing: List[Element]) -> List[Element]:
    H, W = img.shape[:2]
    rects = detect_visual_rects(img)
    out = []
    for idx, (x, y, w, h, typ, score) in enumerate(rects):
        xf, yf, wf, hf = norm_box((x, y, w, h), img.shape)
        # Skip if this is almost a nav element already.
        if any(iou_box(e, (xf, yf, wf, hf)) > 0.45 for e in existing):
            continue
        # Use labels inside or just below.
        label = label_from_words(words, (xf, yf, wf, hf), below=False)
        if not label:
            label = label_from_words(words, (xf, yf, wf, hf), below=True)
        # Determine element type.
        if typ == "button_or_row":
            etype = "button" if h < 80 and w < 260 else "menu_item"
        elif typ == "tile":
            etype = "card"
        else:
            etype = "card"
        # Remove obvious huge background fragments with no label unless useful as card.
        if not label and etype == "card" and (w * h < 6500 or y < 0.20 * H):
            continue
        if not label:
            label = etype
        out.append(Element(
            id=f"{etype}_{idx}_{slug(label)}", type=etype, label=label,
            x=xf, y=yf, w=wf, h=hf, source="visual_rect", score=float(score)))
    return dedupe_elements(out, existing)


def elements_from_text(words: List[dict], existing: List[Element]) -> List[Element]:
    """Add OCR text that is likely interactive but has no visible rectangle: icon buttons, row items."""
    candidates = []
    for i, w in enumerate(words):
        txt = w["text"]
        if len(txt) < 2:
            continue
        # Skip if already covered by visual/nav element.
        box = (w["x"], w["y"], w["w"], w["h"])
        if any(iou_box(e, box) > 0.15 or (e.x <= w["cx"] <= e.end and e.y <= w["cy"] <= e.bottom) for e in existing):
            continue
        # Good candidates: prominent words in nav/header areas, or menu options in center dialogs.
        if w["h"] > 0.026 or (0.15 < w["y"] < 0.85 and w["w"] > 0.035):
            candidates.append(Element(
                id=f"text_{i}_{slug(txt)}", type="text_item", label=txt,
                x=w["x"], y=w["y"], w=w["w"], h=w["h"], source="ocr_text", score=w["conf"]))
    return candidates


def dedupe_elements(new: List[Element], existing: List[Element]) -> List[Element]:
    out = []
    for e in new:
        if any(iou_box(o, (e.x, e.y, e.w, e.h)) > 0.55 for o in existing + out):
            continue
        out.append(e)
    return out


def focus_candidates(img) -> List[dict]:
    if focusmod is None:
        return []
    try:
        cands = focusmod.detect_focus(img, top_k=8)
        return [asdict(c) for c in cands]
    except Exception:
        return []


def add_focus_regions_as_elements(img, words: List[dict], elements: List[Element], cands: List[dict]) -> List[Element]:
    H, W = img.shape[:2]
    added = []
    for i, c in enumerate(cands[:3]):
        x, y, w, h = c["box"]
        xf, yf, wf, hf = x / W, y / H, w / W, h / H
        # If no existing element covers this focus cue, create one. This catches Apple TV Play, live menu row, etc.
        if any(iou_box(e, (xf, yf, wf, hf)) > 0.25 or (e.x-0.02 <= xf+wf/2 <= e.end+0.02 and e.y-0.03 <= yf+hf/2 <= e.bottom+0.03) for e in elements):
            continue
        label = ocr_crop_label(img, (x, y, w, h)) or label_from_words(words, (xf, yf, wf, hf), below=False) or label_from_words(words, (xf, yf, wf, hf), below=True)
        if not label:
            label = c.get("cue_type", "focus")
        typ = "button" if h < 90 else "focus_region"
        added.append(Element(
            id=f"{typ}_focus_{i}_{slug(label)}", type=typ, label=label,
            x=xf, y=yf, w=wf, h=hf, focused=False, source="focus_cue", score=float(c.get("score", 0))))
    return elements + added


def associate_focus(img, elements: List[Element], cands: List[dict]) -> Optional[str]:
    # Preserve reliable nav focus.
    nav_focus = next((e for e in elements if e.type == "nav_item" and e.focused), None)
    if nav_focus:
        return nav_focus.id
    if not cands or not elements:
        return None
    H, W = img.shape[:2]
    best_e, best_score = None, -999.0
    for rank, c in enumerate(cands[:5]):
        x, y, w, h = c["box"]
        fb = (x / W, y / H, w / W, h / H)
        fcx, fcy = fb[0] + fb[2] / 2, fb[1] + fb[3] / 2
        for e in elements:
            score = 0.0
            score += 0.65 * float(c.get("score", 0.0))
            if rank == 0:
                score += 1.0
            score += 4.0 * iou_box(e, fb)
            if e.x - 0.04 <= fcx <= e.end + 0.04 and e.y - 0.05 <= fcy <= e.bottom + 0.05:
                score += 1.2
            score -= 0.85 * rank
            # Type/style biases.
            cue = c.get("cue_type", "")
            if cue == "underline" and e.type == "nav_item":
                score += 1.0 - min(1.0, abs(e.cx - fcx) / 0.08)
            if cue in {"border_or_ring", "avatar_ring_or_fill"} and e.type in {"card", "button", "focus_region"}:
                score += 0.6
            if cue == "filled_highlight" and e.type in {"button", "menu_item", "card", "focus_region"}:
                score += 0.7
            if score > best_score:
                best_score = score; best_e = e
    if best_e and best_score > 0.55:
        # Refresh label from the strongest focus crop when OCR-on-full-frame was weak.
        if cands:
            x, y, w, h = cands[0]["box"]
            lab = ocr_crop_label(img, (x, y, w, h))
            if lab and (best_e.label in {"button", "card", "focus_region"} or len(best_e.label) < 4 or cands[0].get("cue_type") in {"filled_highlight", "border_or_ring", "avatar_ring_or_fill"}):
                best_e.label = lab
                best_e.id = f"{best_e.type}_{slug(lab)}"
        for e in elements:
            e.focused = False
        best_e.focused = True
        return best_e.id
    return None


def assign_rows_cols(elements: List[Element]) -> None:
    # Group all focusable elements by visual rows; keep nav row name if present.
    others = [e for e in elements if e.type != "nav_item"]
    rows = []
    for e in sorted(others, key=lambda z: (z.cy, z.x)):
        placed = False
        tol = max(0.045, min(0.11, e.h * 0.75))
        for row in rows:
            avg = sum(z.cy for z in row) / len(row)
            if abs(e.cy - avg) < tol:
                row.append(e); placed = True; break
        if not placed:
            rows.append([e])
    rows.sort(key=lambda r: sum(e.cy for e in r) / len(r))
    for ri, row in enumerate(rows):
        row.sort(key=lambda z: z.x)
        for ci, e in enumerate(row):
            if not e.row:
                e.row = f"row_{ri}"
            e.col = ci


def spatial_navigation(screen_id: str, elements: List[Element]) -> Dict[str, Dict[str, str]]:
    focusables = [e for e in elements if e.type in {"nav_item", "card", "button", "menu_item", "text_item", "focus_region"}]
    nav = {}
    for a in focusables:
        node = f"{screen_id}.{a.id}"
        edges = {"OK": f"ENTER:{a.label}", "BACK": "UNKNOWN"}
        for direction in ["LEFT", "RIGHT", "UP", "DOWN"]:
            best, best_cost = None, 999.0
            for b in focusables:
                if b is a:
                    continue
                dx, dy = b.cx - a.cx, b.cy - a.cy
                if direction == "RIGHT" and dx <= 0.012: continue
                if direction == "LEFT" and dx >= -0.012: continue
                if direction == "DOWN" and dy <= 0.012: continue
                if direction == "UP" and dy >= -0.012: continue
                if direction in {"LEFT", "RIGHT"}:
                    primary = abs(dx)
                    align = abs(dy) * 2.6
                    if abs(dy) < max(0.04, (a.h + b.h) * 0.55):
                        align *= 0.25
                    if a.row and a.row == b.row:
                        align *= 0.30
                    if a.type != b.type and a.type == "nav_item":
                        align += 0.60
                else:
                    primary = abs(dy)
                    align = abs(dx) * 1.7
                    if abs(dx) < max(a.w, b.w) * 0.75:
                        align *= 0.35
                    # Allow nav->first content down, but prefer same column in grids.
                    if a.type == "nav_item" and direction == "DOWN":
                        align *= 0.75
                cost = primary + align
                if cost < best_cost:
                    best_cost, best = cost, b
            if best:
                edges[direction] = f"{screen_id}.{best.id}"
        nav[node] = edges
    return nav


def infer_dom(path: str) -> Dict:
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    words = ocr_words(img)
    screen_id, navs = extract_nav(path, img, words)
    elements = list(navs)
    elements += elements_from_visuals(img, words, elements)
    elements += elements_from_text(words, elements)
    cands = focus_candidates(img)
    elements = add_focus_regions_as_elements(img, words, elements, cands)
    assign_rows_cols(elements)
    focused_id = associate_focus(img, elements, cands)
    nav = spatial_navigation(screen_id, elements)
    return {
        "image": os.path.basename(path),
        "screen_id": screen_id,
        "focused_element_id": focused_id,
        "elements": [asdict(e) for e in elements],
        "navigation": nav,
        "focus_candidates": cands[:5],
    }


def draw_dom(path: str, dom: Dict, out_path: str):
    img = cv2.imread(path)
    H, W = img.shape[:2]
    for e in dom["elements"]:
        x, y, w, h = int(e["x"] * W), int(e["y"] * H), int(e["w"] * W), int(e["h"] * H)
        if e.get("focused"):
            color, thick = (0, 0, 255), 3
        elif e["type"] == "nav_item":
            color, thick = (0, 255, 255), 2
        elif e["type"] in {"button", "menu_item"}:
            color, thick = (0, 255, 0), 2
        elif e["type"] == "text_item":
            color, thick = (255, 0, 255), 1
        else:
            color, thick = (255, 180, 0), 2
        cv2.rectangle(img, (x, y), (x + w, y + h), color, thick)
        txt = f"{e['type']}:{e['label']}"
        cv2.putText(img, txt[:36], (x, max(16, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, .42, color, 1, cv2.LINE_AA)
    cv2.imwrite(out_path, img)


def dom_text(dom: Dict) -> str:
    lines = [f"SCREEN: {dom.get('screen_id')}", f"IMAGE: {dom.get('image')}", "", "FOCUS:", f"  {dom.get('focused_element_id') or 'UNKNOWN'}", "", "ELEMENTS:"]
    for e in dom.get("elements", []):
        focus = ", focused=true" if e.get("focused") else ""
        lines.append("")
        lines.append(f'{e.get("type","element").upper()}(id="{e.get("id")}", label="{e.get("label")}", x={e.get("x",0):.4f}, y={e.get("y",0):.4f}, w={e.get("w",0):.4f}, h={e.get("h",0):.4f}, row="{e.get("row","")}", col={e.get("col",-1)}{focus})')
    lines.append("")
    lines.append("NAVIGATION:")
    for node, edges in sorted(dom.get("navigation", {}).items()):
        lines.append("")
        lines.append(f"{node}:")
        for key in ["LEFT", "RIGHT", "UP", "DOWN", "OK", "BACK"]:
            if key in edges:
                lines.append(f"  {key:<5} -> {edges[key]}")
    return "\n".join(lines) + "\n"


def export(path: str, dom: Dict, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    stem = Path(path).stem
    draw_dom(path, dom, os.path.join(out_dir, f"{stem}_dom.jpg"))
    with open(os.path.join(out_dir, f"{stem}_dom.json"), "w", encoding="utf-8") as f:
        json.dump(dom, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, f"{stem}_dom.txt"), "w", encoding="utf-8") as f:
        f.write(dom_text(dom))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", default="/mnt/data/generic_ui_dom_out")
    args = ap.parse_args()
    results = []
    for p in args.images:
        dom = infer_dom(p)
        export(p, dom, args.out)
        results.append(dom)
        print(f"{Path(p).name:18s} screen={dom['screen_id']:<18s} focus={dom['focused_element_id']} elements={len(dom['elements'])}")
        shown = [(e['type'], e['label'][:30], e['focused']) for e in dom['elements'][:10]]
        print("  ", shown)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "dom_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
