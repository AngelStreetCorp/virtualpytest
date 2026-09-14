#!/usr/bin/env python3
"""
Build a self-contained HTML report from OmniParser normalized outputs.

This mirrors dom_report.py's review style, but it is intentionally focus-free:
OmniParser is evaluated as a DOM detector only. It reads files produced by the
benchmark runner:

    <omni_out>/<stem>_normalized.json
    <omni_out>/<stem>_som.png            # optional OmniParser overlay

Usage:
    python3 features/avq/backend_host/localize/omniparser_dom_report.py \
        ~/virtualpytest/screenshot/example_tv \
        --omni-out /tmp/dom_benchmark/omni_full \
        --out /tmp/omniparser_dom_report.html
"""
from __future__ import annotations

import argparse
import base64
import glob
import html
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import cv2


def _b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _draw_overlay(img_path: str, dom: Dict[str, Any]) -> str:
    img = cv2.imread(img_path)
    if img is None:
        return ""
    h, w = img.shape[:2]
    for idx, element in enumerate(dom.get("elements", [])):
        x, y, bw, bh = element.get("bbox", [0, 0, 0, 0])
        x0, y0 = int(x * w), int(y * h)
        x1, y1 = int((x + bw) * w), int((y + bh) * h)
        is_text = element.get("type") == "text"
        color = (0, 0, 255) if is_text else (0, 220, 255)
        cv2.rectangle(img, (x0, y0), (x1, y1), color, 2)
        label = f"{idx}:{element.get('type', '')}"
        cv2.putText(
            img,
            label,
            (x0, max(18, y0 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )

    tmp = tempfile.mktemp(suffix=".jpg")
    try:
        cv2.imwrite(tmp, img)
        return _b64(tmp)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _load_dom(omni_out: Path, stem: str) -> Dict[str, Any]:
    path = omni_out / f"{stem}_normalized.json"
    if not path.exists():
        return {
            "image": f"{stem}.jpg",
            "ocr_text": [],
            "elements": [],
            "raw_count": 0,
            "error": "missing normalized OmniParser JSON",
        }
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _element_li(element: Dict[str, Any], idx: int) -> str:
    bbox = element.get("bbox", [0, 0, 0, 0])
    content = str(element.get("content") or "").strip()
    source = str(element.get("source") or "").strip()
    interactive = element.get("interactivity")
    details = []
    if content:
        details.append(f'<span class="content">{html.escape(content)}</span>')
    if source:
        details.append(f'<span class="source">{html.escape(source)}</span>')
    if interactive is not None:
        details.append(f'<span class="source">interactive={html.escape(str(interactive))}</span>')
    detail_html = " ".join(details)
    return (
        f'<li><b>{idx:02d}</b> {html.escape(str(element.get("type", "element")))} '
        f'<span class="box">[{bbox[0]:.3f},{bbox[1]:.3f} {bbox[2]:.3f}x{bbox[3]:.3f}]</span> '
        f"{detail_html}</li>"
    )


def _paths(image_dir: str) -> List[str]:
    return sorted(glob.glob(os.path.join(image_dir, "*.jpg")) + glob.glob(os.path.join(image_dir, "*.png")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "image_dir",
        nargs="?",
        default=os.path.expanduser("~/virtualpytest/screenshot/example_tv"),
    )
    parser.add_argument("--omni-out", default="/tmp/dom_benchmark/omni_full")
    parser.add_argument("--out", default="/tmp/omniparser_dom_report.html")
    args = parser.parse_args()

    omni_out = Path(args.omni_out)
    rows: List[str] = []
    sections: List[str] = []
    total_images = total_elements = total_text = total_icon = n_empty = n_missing = n_error = 0

    for img_path in _paths(args.image_dir):
        total_images += 1
        name = os.path.basename(img_path)
        stem = Path(img_path).stem
        dom = _load_dom(omni_out, stem)
        elements = dom.get("elements", [])
        text_count = sum(1 for e in elements if e.get("type") == "text")
        icon_count = sum(1 for e in elements if e.get("type") == "icon")
        ocr_count = len(dom.get("ocr_text", []))
        error = str(dom.get("error") or "")

        total_elements += len(elements)
        total_text += text_count
        total_icon += icon_count

        flags = []
        if not elements:
            flags.append("empty")
            n_empty += 1
        if error:
            flags.append(error)
            n_error += 1
        if "missing normalized" in error:
            n_missing += 1

        cls = "fail" if error else ("warn" if not elements else "ok")
        rows.append(
            f'<tr class="{cls}"><td><a href="#{html.escape(name)}">{html.escape(name)}</a></td>'
            f"<td>{len(elements)}</td><td>{text_count}</td><td>{icon_count}</td><td>{ocr_count}</td>"
            f'<td>{html.escape("; ".join(flags))}</td></tr>'
        )

        som_path = omni_out / f"{stem}_som.png"
        if som_path.exists():
            overlay = _b64(str(som_path))
        else:
            overlay = _draw_overlay(img_path, dom)

        ocr_html = "".join(f"<li>{html.escape(str(t))}</li>" for t in dom.get("ocr_text", [])[:80])
        text_html = "".join(_element_li(e, i) for i, e in enumerate(elements) if e.get("type") == "text")
        icon_html = "".join(_element_li(e, i) for i, e in enumerate(elements) if e.get("type") == "icon")
        other_html = "".join(
            _element_li(e, i)
            for i, e in enumerate(elements)
            if e.get("type") not in {"text", "icon"}
        )
        flag_html = "".join(f'<span class="flag">{html.escape(f)}</span>' for f in flags)

        sections.append(
            f"""
<h3 id="{html.escape(name)}">{html.escape(name)}
  <small>elements={len(elements)} · text={text_count} · icon={icon_count} · ocr={ocr_count}</small>
  {flag_html}
</h3>
<div class="grid">
  <img src="data:image/png;base64,{overlay}" />
  <div class="data">
    <h4>Text Elements ({text_count})</h4><ul>{text_html or "<li><i>none</i></li>"}</ul>
    <h4>Icon Elements ({icon_count})</h4><ul>{icon_html or "<li><i>none</i></li>"}</ul>
    {f'<h4>Other Elements</h4><ul>{other_html}</ul>' if other_html else ''}
    <h4>OCR Text ({ocr_count})</h4><ul class="ocr">{ocr_html or "<li><i>none</i></li>"}</ul>
  </div>
</div>"""
        )

    avg_elements = total_elements / total_images if total_images else 0
    avg_text = total_text / total_images if total_images else 0
    avg_icon = total_icon / total_images if total_images else 0
    summary = (
        f"{total_images} images · "
        f"<b class=\"ok\">avg {avg_elements:.1f} elements</b> · "
        f"<b class=\"ok\">avg {avg_text:.1f} text</b> · "
        f"<b class=\"ok\">avg {avg_icon:.1f} icon</b> · "
        f"<b class=\"warn\">{n_empty} empty</b> · "
        f"<b class=\"fail\">{n_error} errors</b>"
    )

    doc = f"""<!doctype html><meta charset="utf-8"><title>OmniParser DOM report</title>
<style>
body{{font:13px -apple-system,Segoe UI,Arial;background:#111;color:#ddd;margin:0;padding:16px}}
h1{{font-size:18px}} h3{{margin:28px 0 6px;border-top:1px solid #333;padding-top:14px}}
small{{color:#888;font-weight:normal}} a{{color:#6cf;text-decoration:none}}
table{{border-collapse:collapse;width:100%;font-size:12px}} td,th{{border:1px solid #333;padding:3px 6px;text-align:left}}
tr.ok td:first-child{{border-left:3px solid #2c2}} tr.warn td:first-child{{border-left:3px solid #fb0}} tr.fail td:first-child{{border-left:3px solid #f44}}
.ok{{color:#3d3}} .warn{{color:#fb0}} .fail{{color:#f66}}
.grid{{display:grid;grid-template-columns:560px 1fr;gap:16px;align-items:start}}
.grid img{{width:560px;border:1px solid #333;border-radius:4px}}
.data h4{{margin:8px 0 2px;color:#9cf}} ul{{margin:0;padding-left:18px}}
.box{{color:#888;font-size:11px}} .content{{color:#eee}} .source{{color:#777;font-size:11px}}
.flag{{display:inline-block;background:#532;color:#fb0;border-radius:3px;padding:1px 6px;margin-left:6px;font-size:11px}}
ul.ocr{{column-count:2}}
</style>
<h1>OmniParser DOM report &nbsp;<small>{summary}</small></h1>
<table><tr><th>image</th><th>elements</th><th>text</th><th>icon</th><th>ocr</th><th>flags</th></tr>{''.join(rows)}</table>
{''.join(sections)}"""

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(doc)

    print(
        f"{total_images} images -> {args.out} "
        f"(avg elements={avg_elements:.1f}, text={avg_text:.1f}, icon={avg_icon:.1f}, "
        f"empty={n_empty}, errors={n_error}, missing={n_missing})"
    )


if __name__ == "__main__":
    main()
