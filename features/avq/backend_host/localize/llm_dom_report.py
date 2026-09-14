#!/usr/bin/env python3
"""
Build ONE self-contained HTML report of the LLM DOM generator (GPT-5.5, no hints)
over a folder of screenshots — for local review / regression.

Uses the SAME dom_generator.generate_dom() + render_dom_overlay() as production, so
the report reflects exactly what the live pipeline produces. For each image it shows
the DOM overlay (inline base64) next to the focusable elements + navigation graph,
with a summary table (focus, element count, latency, cost) up top.

Requires OPENAI_API_KEY in the environment.

Usage:
    python3 features/avq/backend_host/localize/llm_dom_report.py [IMAGE_DIR] [--out report.html] [--workers 6]
    # default IMAGE_DIR = ~/virtualpytest/screenshot/example_tv
"""
import argparse
import base64
import html
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))
from backend_host.src.services.ai_exploration.dom_generator import (  # noqa: E402
    generate_dom, render_dom_overlay,
)

RATE_IN, RATE_OUT = 5.0, 30.0  # GPT-5.5 $/1M


def _b64(path: str) -> str:
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode('ascii')


def _process(name: str, image_dir: Path, asset_dir: Path) -> dict:
    item = {'image': name}
    try:
        dom = generate_dom(str(image_dir / name))
        overlay = asset_dir / f"{Path(name).stem}_dom.jpg"
        render_dom_overlay(str(image_dir / name), dom, str(overlay))
        u = dom.get('_dom_meta', {}).get('usage', {})
        item.update({
            'dom': dom,
            'overlay': str(overlay),
            'cost': u.get('prompt_tokens', 0) * RATE_IN / 1e6 + u.get('completion_tokens', 0) * RATE_OUT / 1e6,
            'elapsed': dom.get('_dom_meta', {}).get('elapsed_sec', 0),
        })
        print(f"ok {name}: focus={dom.get('focused_element_id')} els={len(dom.get('focusable_elements', []))} ({item['elapsed']}s)")
    except Exception as e:
        item['error'] = str(e)
        print(f"fail {name}: {e}", file=sys.stderr)
    return item


def build_html(results: list, out_html: Path) -> None:
    rows, sections = [], []
    tot_cost = focus_found = 0
    for item in results:
        name = item['image']
        dom = item.get('dom') or {}
        els = dom.get('focusable_elements', []) or []
        nav = dom.get('navigation', {}) or {}
        focus = dom.get('focused_element_id')
        focus_found += 1 if focus else 0
        tot_cost += item.get('cost', 0)
        err = item.get('error', '')
        cls = 'fail' if err else ('ok' if focus else 'warn')
        rows.append(
            f'<tr class="{cls}"><td><a href="#{html.escape(name)}">{html.escape(name)}</a></td>'
            f'<td>{len(els)}</td><td>{len(nav)}</td><td>{html.escape(str(focus or "—"))}</td>'
            f'<td>{item.get("elapsed", 0)}s</td><td>${item.get("cost", 0):.4f}</td><td>{html.escape(err)}</td></tr>'
        )
        overlay_html = (f'<img src="data:image/jpeg;base64,{_b64(item["overlay"])}" />'
                        if item.get('overlay') and os.path.exists(item['overlay']) else '')
        el_rows = ''.join(
            f'<tr class="{"foc" if (e.get("focused") or e.get("id") == focus) else ""}">'
            f'<td>{e.get("index", i)}</td><td><code>{html.escape(str(e.get("id", "")))}</code></td>'
            f'<td>{html.escape(str(e.get("type", "")))}</td><td>{html.escape(str(e.get("label", "") or "—"))}</td>'
            f'<td>{html.escape(str(e.get("text_found", "") or "—"))}</td>'
            f'<td><span class="box">{html.escape(str(e.get("bbox", "")))}</span></td>'
            f'<td>{html.escape(str(e.get("confidence", "")))}</td></tr>'
            for i, e in enumerate(els)
        )
        els_html = ('<table class="elements"><tr><th>#</th><th>id</th><th>type</th><th>label</th>'
                    '<th>text</th><th>bbox</th><th>conf</th></tr>' + el_rows + '</table>') if el_rows else '<i>none</i>'
        nav_rows = ''.join(
            f'<tr class="{"foc" if k == focus else ""}"><td><code>{html.escape(str(k))}</code></td>'
            f'<td>{html.escape(str(v.get("LEFT")))}</td><td>{html.escape(str(v.get("RIGHT")))}</td>'
            f'<td>{html.escape(str(v.get("UP")))}</td><td>{html.escape(str(v.get("DOWN")))}</td>'
            f'<td>{html.escape(str(v.get("OK", "")))}</td><td>{html.escape(str(v.get("BACK", "")))}</td></tr>'
            for k, v in list(nav.items())[:120]
        )
        nav_html = ('<table class="navigation"><tr><th>element</th><th>L</th><th>R</th><th>U</th><th>D</th>'
                    '<th>OK</th><th>BACK</th></tr>' + nav_rows + '</table>') if nav_rows else '<i>none</i>'
        sections.append(
            f'<h3 id="{html.escape(name)}">{html.escape(name)} <small>focus={html.escape(str(focus or "—"))} · '
            f'elements={len(els)}</small></h3><div class="grid">{overlay_html}'
            f'<div><h4>Elements</h4>{els_html}<h4>Navigation</h4>{nav_html}</div></div>'
        )
    summary = f"{len(results)} images · {focus_found} focus found · ${tot_cost:.2f} total"
    doc = f"""<!doctype html><meta charset="utf-8"><title>LLM DOM report (GPT-5.5)</title>
<style>
body{{font:13px -apple-system,Segoe UI,Arial;background:#111;color:#ddd;margin:0;padding:16px}}
h1{{font-size:18px}} h3{{margin:28px 0 6px;border-top:1px solid #333;padding-top:14px}}
small{{color:#888;font-weight:normal}} a{{color:#6cf;text-decoration:none}}
table{{border-collapse:collapse;width:100%;font-size:12px}} td,th{{border:1px solid #333;padding:3px 6px;text-align:left;vertical-align:top}}
tr.ok td:first-child{{border-left:3px solid #2c2}} tr.warn td:first-child{{border-left:3px solid #fb0}} tr.fail td:first-child{{border-left:3px solid #f44}}
.grid{{display:grid;grid-template-columns:560px 1fr;gap:16px;align-items:start}} .grid img{{width:560px;border:1px solid #333;border-radius:4px}}
h4{{margin:8px 0 2px;color:#9cf}} .elements tr.foc td,.navigation tr.foc td{{color:#f66!important;font-weight:bold;background:#2a1010}}
code{{color:#9cf}} .box{{color:#888;font-size:11px}}
</style>
<h1>LLM DOM report — GPT-5.5, medium, no hints <small>{html.escape(summary)}</small></h1>
<table><tr><th>image</th><th>els</th><th>nav</th><th>focus</th><th>time</th><th>cost</th><th>error</th></tr>{''.join(rows)}</table>
{''.join(sections)}"""
    out_html.write_text(doc, encoding='utf-8')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('image_dir', nargs='?',
                    default=os.path.expanduser('~/virtualpytest/screenshot/example_tv'))
    ap.add_argument('--out', default='/tmp/llm_dom_report.html')
    ap.add_argument('--workers', type=int, default=6)
    args = ap.parse_args()

    if not os.getenv('OPENAI_API_KEY', '').strip():
        print('❌ OPENAI_API_KEY not set')
        return 1

    image_dir = Path(args.image_dir)
    names = sorted(p.name for p in image_dir.glob('*.jpg'))
    if not names:
        print(f'No .jpg images in {image_dir}')
        return 1
    asset_dir = Path(tempfile.mkdtemp(prefix='llm_dom_report_'))
    print(f"{len(names)} images, {args.workers} workers -> {args.out}")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda n: _process(n, image_dir, asset_dir), names))

    build_html(results, Path(args.out))
    ok = sum(1 for r in results if not r.get('error') and (r.get('dom') or {}).get('focused_element_id'))
    print(f"\nhtml: {args.out}\nfocus found: {ok}/{len(results)}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
