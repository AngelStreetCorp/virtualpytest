#!/usr/bin/env python3
"""
TV UI DOM inference from a screenshot.

Combines:
  - nav/menu extraction (OCR + row grammar)
  - card/tile extraction (geometry + optional OCR labels)
  - no-reference focus cue detection
  - spatial navigation inference between focusable elements

Output is a visual DOM-like JSON:
  elements: [{id,type,label,box,row,focused}]
  navigation: {node_id:{LEFT/RIGHT/UP/DOWN/OK/BACK}}

It is deterministic and vision-only. Card detection is heuristic: it detects large
rectangular UI tiles/posters in the content area, then groups them into rows.
"""
from __future__ import annotations

import argparse, json, os, re, importlib.util, sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

W,H = 1280,720

# Import previously built nav/focus modules from same directory.
HERE = Path(__file__).resolve().parent

def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, str(HERE / filename))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

# nav extractor: the in-repo geometry inferer (swap in a refined ui_infer when ready).
navmod = _load_module("ui_nav", "ui_infer_offline.py")
focusmod = _load_module("focus_detector", "no_reference_focus_detector.py")

@dataclass
class Element:
    id: str
    type: str           # nav_item, card, button, text, icon
    label: str
    x: float
    y: float
    w: float
    h: float
    row: str = ""
    focused: bool = False
    source: str = ""

    @property
    def cx(self): return self.x + self.w/2
    @property
    def cy(self): return self.y + self.h/2
    @property
    def end(self): return self.x + self.w
    @property
    def bottom(self): return self.y + self.h


def slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "item"


def iou(a: Element, b: Tuple[float,float,float,float]) -> float:
    x,y,w,h = b
    ax0,ay0,ax1,ay1 = a.x,a.y,a.end,a.bottom
    bx0,by0,bx1,by1 = x,y,x+w,y+h
    ix0,iy0=max(ax0,bx0),max(ay0,by0)
    ix1,iy1=min(ax1,bx1),min(ay1,by1)
    inter=max(0,ix1-ix0)*max(0,iy1-iy0)
    if inter<=0: return 0.0
    return inter/(a.w*a.h + w*h - inter)


def full_ocr_words(img) -> List[dict]:
    """OCR for labels under cards. Returns normalized word boxes."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(gray)
    up = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(up, config="--psm 11", output_type=Output.DICT)
    Hh,Ww=img.shape[:2]
    words=[]
    for i,t in enumerate(data["text"]):
        t=t.strip().strip("|_.,:;!()[]{}<>")
        if not t: continue
        try: conf=float(data["conf"][i])
        except: conf=-1
        if conf < 15: continue
        x=data["left"][i]/2/Ww; y=data["top"][i]/2/Hh
        w=data["width"][i]/2/Ww; h=data["height"][i]/2/Hh
        if w<.004 or h<.008: continue
        words.append({"text":t,"x":x,"y":y,"w":w,"h":h,"conf":conf,"cx":x+w/2,"cy":y+h/2})
    return words


def merge_boxes(boxes: List[Tuple[int,int,int,int]], iou_thr: float=0.35) -> List[Tuple[int,int,int,int]]:
    boxes = sorted(boxes, key=lambda b: b[2]*b[3], reverse=True)
    kept=[]
    for b in boxes:
        x,y,w,h=b; area=w*h
        keep=True
        for k in kept:
            x2,y2,w2,h2=k
            ix0,iy0=max(x,x2),max(y,y2); ix1,iy1=min(x+w,x2+w2),min(y+h,y2+h2)
            inter=max(0,ix1-ix0)*max(0,iy1-iy0)
            if inter/min(area,w2*h2) > iou_thr:
                keep=False; break
        if keep: kept.append(b)
    return sorted(kept, key=lambda b:(b[1],b[0]))


def detect_card_rectangles(img, screen_id: str) -> List[Tuple[int,int,int,int]]:
    """Find large rectangular cards/tiles/posters in the content area."""
    Hh,Ww=img.shape[:2]
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,50,150)
    edges=cv2.dilate(edges,np.ones((5,5),np.uint8),iterations=1)
    cnts,_=cv2.findContours(edges,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    boxes=[]
    for c in cnts:
        x,y,w,h=cv2.boundingRect(c)
        if y < 0.18*Hh: continue
        area=w*h
        if area < 6500 or w<60 or h<45: continue
        if w>0.60*Ww or h>0.45*Hh: continue
        asp=w/float(h)
        # app tiles square-ish, posters/cards landscape or square. Reject text lines.
        if not (0.55 <= asp <= 4.2): continue
        boxes.append((x,y,w,h))
    boxes=merge_boxes(boxes)

    # Remove obvious label-only fragments and boxes inside other boxes.
    filtered=[]
    for b in boxes:
        x,y,w,h=b; asp=w/float(h)
        # label fragments: wide and very short
        if h < 55 and asp > 2.8: continue
        # bottom cropped text/preview fragments touching bottom are not cards
        if y+h > Hh-5 and h < 90: continue
        filtered.append(b)

    # Screen-specific sanity: nav screens with no card grid still can produce content boxes.
    return filtered


def section_headers(words: List[dict]) -> List[dict]:
    """Large-ish left-aligned labels that name rows, e.g. BELIEBT, All Shows."""
    heads=[]
    for w in words:
        text=w["text"]
        if w["x"] < 0.22 and w["h"] > 0.025 and len(text)>=3:
            if w["y"] > .15:
                heads.append(w)
    return sorted(heads,key=lambda z:z["y"])


def label_for_card(box: Tuple[int,int,int,int], words: List[dict], img_shape) -> str:
    Hh,Ww=img_shape[:2]
    x,y,w,h=box
    xf,yf,wf,hf=x/Ww,y/Hh,w/Ww,h/Hh
    # Prefer words directly below the card, within same x span. For square app tiles labels are below.
    below=[]
    for z in words:
        if yf+hf <= z["cy"] <= yf+hf+0.075 and (xf-0.012) <= z["cx"] <= (xf+wf+0.012):
            below.append(z)
    if below:
        below=sorted(below,key=lambda z:(z["y"],z["x"]))
        # group only first line
        first_y=below[0]["cy"]
        line=[z for z in below if abs(z["cy"]-first_y)<0.025]
        return " ".join(z["text"] for z in line)[:60]
    # Fallback words inside card top-left (logos are noisy but better than empty sometimes)
    inside=[]
    for z in words:
        if xf <= z["cx"] <= xf+wf and yf <= z["cy"] <= yf+hf:
            inside.append(z)
    if inside:
        inside=sorted(inside,key=lambda z:(-z["conf"],z["x"]))[:2]
        return " ".join(z["text"] for z in sorted(inside,key=lambda z:z["x"]))[:60]
    return "card"


def group_rows(elements: List[Element], row_tol: float=0.09) -> List[List[Element]]:
    els=sorted(elements,key=lambda e:(e.cy,e.x))
    rows=[]
    for e in els:
        placed=False
        for row in rows:
            avg=sum(z.cy for z in row)/len(row)
            if abs(e.cy-avg) < row_tol:
                row.append(e); placed=True; break
        if not placed: rows.append([e])
    for row in rows: row.sort(key=lambda e:e.x)
    rows.sort(key=lambda r:sum(e.cy for e in r)/len(r))
    return rows


def infer_cards(img, screen_id: str) -> List[Element]:
    words=full_ocr_words(img)
    boxes=detect_card_rectangles(img, screen_id)
    Hh,Ww=img.shape[:2]
    elems=[]
    for idx,b in enumerate(boxes):
        x,y,w,h=b
        # Apps focus border can join the section header/label into a too-tall contour.
        # Normalize app tiles back to the visible square icon area before OCR label lookup.
        if screen_id == "apps" and h > 185 and w > 185:
            side = min(178, w-6, h-25)
            x = x + max(0, (w-side)//2)
            y = y + h - side - 2
            w = h = side
            b = (x,y,w,h)
        # avoid hero/video preview large overlay; keep content grid/cards mostly below row area
        label=label_for_card(b, words, img.shape)
        xf,yf,wf,hf=x/Ww,y/Hh,w/Ww,h/Hh
        elems.append(Element(id=f"card_{idx}", type="card", label=label or f"card {idx}", x=xf,y=yf,w=wf,h=hf,source="geometry"))
    rows=group_rows(elems)
    for ri,row in enumerate(rows):
        for ci,e in enumerate(row):
            e.row=f"row_{ri}"
            e.id=f"card_{ri}_{ci}_{slug(e.label)}"
    return [e for row in rows for e in row]


def nav_elements(path: str) -> Tuple[str,List[Element]]:
    r=navmod.extract(path)
    els=[]
    for it in r.get("items",[]):
        els.append(Element(id=f"nav_{it['id']}", type="nav_item", label=it["label"], x=it["x"], y=it["y"], w=it["w"], h=it["h"], row="nav", focused=bool(it.get("focused")), source="ocr_nav"))
    return r.get("screen_id","unknown"), els


def associate_focus(img, elements: List[Element]) -> Tuple[Optional[str], List[dict]]:
    cands=focusmod.detect_focus(img, top_k=5)
    # If the nav extractor already found an underline focus, keep it.
    # This prevents red logos/content from stealing focus on Home/Replay/Movie screens.
    existing = next((e for e in elements if e.focused and e.type == "nav_item"), None)
    if existing is not None:
        return existing.id, [asdict(c) for c in cands[:3]]
    if not cands:
        return None, []
    # Try to map the strongest focus cue to an element. Use IoU and center containment/proximity.
    best_el=None; best_score=-1
    Hh,Ww=img.shape[:2]
    for rank, cand in enumerate(cands[:1]):
        x,y,w,h=cand.box
        fb=(x/Ww,y/Hh,w/Ww,h/Hh)
        fcx,fcy=fb[0]+fb[2]/2, fb[1]+fb[3]/2
        for e in elements:
            # Earlier focus candidates are more trusted; later candidates are possible decoys.
            score=-0.45*rank
            score += iou(e, fb)*3.0
            # focus border may surround card closely, underline below nav, fill inside button/card.
            if e.x-0.03 <= fcx <= e.end+0.03 and e.y-0.04 <= fcy <= e.bottom+0.05:
                score += 0.7
            # underline: y just under nav text and x-center aligned
            if cand.cue_type == "underline" and e.type == "nav_item":
                score += max(0, 1.0 - abs(e.cx-fcx)/0.08)
            # big border around card/avatar
            if cand.cue_type in {"border_or_ring","avatar_ring_or_fill"} and e.type == "card":
                score += max(0, 0.8 - abs(e.cx-fcx)/0.12 - abs(e.cy-fcy)/0.12)
            if score > best_score:
                best_score=score; best_el=e
    if best_el and best_score > 0.55:
        for e in elements: e.focused=False
        best_el.focused=True
        return best_el.id, [asdict(c) for c in cands]
    return None, [asdict(c) for c in cands]


def spatial_navigation(screen_id: str, elements: List[Element]) -> Dict[str,Dict[str,str]]:
    focusables=[e for e in elements if e.type in {"nav_item","card","button"}]
    nodes={}
    for a in focusables:
        nid=f"{screen_id}.{a.id}"
        edges={"OK":f"ENTER:{a.label}","BACK":"UNKNOWN"}
        for direction in ["LEFT","RIGHT","UP","DOWN"]:
            best=None; best_cost=1e9
            for b in focusables:
                if b is a: continue
                dx=b.cx-a.cx; dy=b.cy-a.cy
                if direction=="RIGHT" and dx <= 0.015: continue
                if direction=="LEFT" and dx >= -0.015: continue
                if direction=="DOWN" and dy <= 0.015: continue
                if direction=="UP" and dy >= -0.015: continue
                # alignment penalty: prefer same row for L/R and same column for U/D
                if direction in {"LEFT","RIGHT"}:
                    primary=abs(dx)
                    align=abs(dy)*2.5
                    # strong bonus for same row labels/cards
                    if abs(dy)<0.08: align *= 0.35
                else:
                    primary=abs(dy)
                    align=abs(dx)*1.7
                    if abs(dx)<max(a.w,b.w)*0.7: align *= 0.45
                type_penalty=0.0
                # avoid jumping between nav and cards horizontally; vertical link is allowed
                if direction in {"LEFT","RIGHT"} and a.type!=b.type:
                    type_penalty += .6
                cost=primary+align+type_penalty
                if cost<best_cost:
                    best_cost=cost; best=b
            if best is not None:
                edges[direction]=f"{screen_id}.{best.id}"
        nodes[nid]=edges
    return nodes


def infer_dom(path: str) -> Dict:
    img=cv2.imread(path)
    if img is None: raise FileNotFoundError(path)
    screen, navs=nav_elements(path)
    cards=infer_cards(img, screen)
    elements=navs+cards
    focused_id, focus_candidates=associate_focus(img, elements)
    nav=spatial_navigation(screen, elements)
    return {
        "image": os.path.basename(path),
        "screen_id": screen,
        "focused_element_id": focused_id or next((e.id for e in elements if e.focused), None),
        "elements": [asdict(e) for e in elements],
        "navigation": nav,
        "focus_candidates": focus_candidates[:3],
    }


def draw_dom(path: str, dom: Dict, out_path: str):
    img=cv2.imread(path)
    Hh,Ww=img.shape[:2]
    for e in dom["elements"]:
        x=int(e["x"]*Ww); y=int(e["y"]*Hh); w=int(e["w"]*Ww); h=int(e["h"]*Hh)
        if e.get("focused"):
            color=(0,0,255); thick=3
        elif e["type"]=="nav_item":
            color=(0,255,255); thick=2
        else:
            color=(255,180,0); thick=2
        cv2.rectangle(img,(x,y),(x+w,y+h),color,thick)
        txt=f"{e['type']}:{e['label']}"
        cv2.putText(img,txt[:32],(x,max(18,y-6)),cv2.FONT_HERSHEY_SIMPLEX,.45,color,1,cv2.LINE_AA)
    cv2.imwrite(out_path,img)



def dom_text(dom: Dict) -> str:
    """Compact, deterministic DOM representation for another AI agent."""
    lines = []
    lines.append(f"SCREEN: {dom.get('screen_id','unknown')}")
    lines.append(f"IMAGE: {dom.get('image','')}")
    lines.append("")
    lines.append("FOCUS:")
    lines.append(f"  {dom.get('focused_element_id') or 'UNKNOWN'}")
    lines.append("")
    lines.append("ELEMENTS:")
    for e in dom.get('elements', []):
        type_name = str(e.get('type','element')).upper()
        focused = ', focused=true' if e.get('focused') else ''
        lines.append("")
        lines.append(
            f'{type_name}(id="{e.get("id","")}", label="{e.get("label","")}", '
            f'x={e.get("x",0):.4f}, y={e.get("y",0):.4f}, '
            f'w={e.get("w",0):.4f}, h={e.get("h",0):.4f}, '
            f'row="{e.get("row","")}"{focused})'
        )
    lines.append("")
    lines.append("NAVIGATION:")
    for node_id, edges in sorted(dom.get('navigation', {}).items()):
        lines.append("")
        lines.append(f"{node_id}:")
        for key in ["LEFT", "RIGHT", "UP", "DOWN", "OK", "BACK"]:
            if key in edges:
                lines.append(f"  {key:<5} -> {edges[key]}")
    return "\n".join(lines) + "\n"


def export_dom_files(path: str, dom: Dict, out_dir: str):
    """Export <stem>_dom.jpg, <stem>_dom.json and <stem>_dom.txt."""
    stem = Path(path).stem
    os.makedirs(out_dir, exist_ok=True)
    draw_dom(path, dom, os.path.join(out_dir, f"{stem}_dom.jpg"))
    with open(os.path.join(out_dir, f"{stem}_dom.json"), "w", encoding="utf-8") as f:
        json.dump(dom, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, f"{stem}_dom.txt"), "w", encoding="utf-8") as f:
        f.write(dom_text(dom))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", default="/mnt/data/ui_dom_out")
    args=ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    results=[]
    failed=[]
    for p in args.images:
        try:
            dom=infer_dom(p); results.append(dom)
            export_dom_files(p, dom, args.out)
            print(f"{Path(p).name:18s} screen={dom['screen_id']:10s} focus={dom['focused_element_id']} elems={len(dom['elements'])}")
            print("  ", [(e['type'],e['label'],e['row'],e['focused']) for e in dom['elements'][:12]])
        except Exception as e:
            # One unreadable/odd image must never abort the whole batch.
            failed.append(Path(p).name)
            print(f"{Path(p).name:18s} FAILED: {type(e).__name__}: {e}")
    if failed:
        print(f"\n{len(failed)} image(s) failed: {failed}")
    with open(os.path.join(args.out,"dom_results.json"),"w") as f:
        json.dump(results,f,indent=2)

if __name__=="__main__":
    main()
