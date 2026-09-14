#!/usr/bin/env python3
"""
Build ONE self-contained HTML report from the DOM exporter (v5) for a folder of
screenshots — for local review. For every image it shows the DOM overlay (inline
base64) next to the extracted elements (grouped by type) + navigation graph + auto
quality flags, with a summary table up top so you can see at a glance what works /
what's missing.

Usage:
    python3 features/avq/backend_host/localize/dom_report.py [IMAGE_DIR] [--out report.html]
    # default IMAGE_DIR = ~/virtualpytest/screenshot/example_tv
"""
import os
import sys
import glob
import re
import base64
import tempfile
import html
import importlib.util
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "generic_ui_dom_exporter_v5", os.path.join(HERE, "generic_ui_dom_exporter_v5.py"))
v5 = importlib.util.module_from_spec(_spec)
sys.modules["generic_ui_dom_exporter_v5"] = v5
_spec.loader.exec_module(v5)
draw_dom = v5.domv4.draw_dom


def _looks_garbled(label):
    for w in re.sub(r'[^0-9A-Za-zÀ-ÿ ]', ' ', label or '').split():
        if len(w) >= 3 and not re.search(r'[aeiouyàâäéèêëïîôöùûü]', w.lower()):
            return True
    return False


def _b64(path):
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode('ascii')


def _overlay_b64(img_path, dom):
    tmp = tempfile.mktemp(suffix='.jpg')
    try:
        draw_dom(img_path, dom, tmp)
        return _b64(tmp)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    img_dir = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') \
        else os.path.expanduser('~/virtualpytest/screenshot/example_tv')
    out = '/tmp/dom_report.html'
    if '--out' in sys.argv:
        out = sys.argv[sys.argv.index('--out') + 1]

    paths = sorted(glob.glob(os.path.join(img_dir, '*.jpg')) + glob.glob(os.path.join(img_dir, '*.png')))
    rows, sections = [], []
    n_ok = n_nofocus = n_empty = n_failed = 0

    for p in paths:
        name = os.path.basename(p)
        try:
            dom = v5.infer_dom(p)
        except Exception as e:
            n_failed += 1
            rows.append(f'<tr class="fail"><td>{html.escape(name)}</td><td colspan="5">FAILED: {html.escape(type(e).__name__)}: {html.escape(str(e))}</td></tr>')
            sections.append(f'<h3 id="{html.escape(name)}">{html.escape(name)} — <span class="bad">FAILED</span></h3><pre>{html.escape(str(e))}</pre>')
            continue

        els = dom.get('elements', [])
        by_type = defaultdict(list)
        for e in els:
            by_type[e.get('type', '?')].append(e)
        focus_id = dom.get('focused_element_id')
        focus_label = next((e['label'] for e in els if e.get('focused')), None)

        flags = []
        if not els:
            flags.append('EMPTY (dark/video — nothing to map)')
            n_empty += 1
        elif not focus_id:
            flags.append('no focus detected')
            n_nofocus += 1
        else:
            n_ok += 1
        garbled = sorted({e['label'] for e in els
                          if e.get('type') in ('nav_item', 'card', 'menu_item') and _looks_garbled(e['label'])})
        if garbled:
            flags.append('garbled label(s): ' + ', '.join(garbled))
        status = 'EMPTY' if not els else ('NO-FOCUS' if not focus_id else 'ok')
        cls = 'fail' if status == 'EMPTY' else ('warn' if (status == 'NO-FOCUS' or garbled) else 'ok')
        types_str = ', '.join(f'{t}:{len(v)}' for t, v in sorted(by_type.items()))

        rows.append(
            f'<tr class="{cls}"><td><a href="#{html.escape(name)}">{html.escape(name)}</a></td>'
            f'<td>{html.escape(str(dom.get("screen_id", "")))}</td><td>{len(els)}</td>'
            f'<td>{html.escape(types_str)}</td>'
            f'<td>{html.escape(str(focus_label) if focus_id else "—")}</td>'
            f'<td>{html.escape("; ".join(flags)) if flags else ""}</td></tr>')

        # detail: elements grouped by type
        groups_html = ''
        for t, items in sorted(by_type.items()):
            lis = ''.join(
                f'<li class="{"foc" if e.get("focused") else ""}">{html.escape(e["label"])} '
                f'<span class="box">[{e.get("x",0):.2f},{e.get("y",0):.2f} {e.get("w",0):.2f}×{e.get("h",0):.2f}]</span></li>'
                for e in items)
            groups_html += f'<h4>{html.escape(t)} ({len(items)})</h4><ul>{lis}</ul>'
        nav_graph = dom.get('navigation', {})
        graph_html = ''
        for nid, edges in list(nav_graph.items())[:40]:
            es = '  '.join(f'{k}→{html.escape(str(v).split(".")[-1])}' for k, v in edges.items() if k in ('LEFT', 'RIGHT', 'UP', 'DOWN'))
            graph_html += f'<div><b>{html.escape(nid.split(".")[-1])}</b> {es}  <i>OK→{html.escape(str(edges.get("OK","")))}</i></div>'

        flag_html = ''.join(f'<span class="flag">{html.escape(f)}</span>' for f in flags)
        sections.append(f'''
<h3 id="{html.escape(name)}">{html.escape(name)} &nbsp; <small>screen={html.escape(str(dom.get("screen_id","")))} · {html.escape(types_str)} · focus={html.escape(str(focus_label) if focus_id else "—")}</small> {flag_html}</h3>
<div class="grid">
  <img src="data:image/jpeg;base64,{_overlay_b64(p, dom)}" />
  <div class="data">{groups_html}
    <h4>Navigation</h4><div class="graph">{graph_html or "<i>none</i>"}</div>
  </div>
</div>''')

    summary = (f'{len(paths)} images · <b class="ok">{n_ok} ok</b> · '
               f'<b class="warn">{n_nofocus} no-focus</b> · <b class="fail">{n_empty} empty</b> · '
               f'<b class="fail">{n_failed} failed</b> &nbsp;<small>(exporter v5)</small>')
    doc = f'''<!doctype html><meta charset="utf-8"><title>DOM exporter report (v5)</title>
<style>
body{{font:13px -apple-system,Segoe UI,Arial;background:#111;color:#ddd;margin:0;padding:16px}}
h1{{font-size:18px}} h3{{margin:28px 0 6px;border-top:1px solid #333;padding-top:14px}}
small{{color:#888;font-weight:normal}} a{{color:#6cf;text-decoration:none}}
table{{border-collapse:collapse;width:100%;font-size:12px}} td,th{{border:1px solid #333;padding:3px 6px;text-align:left;vertical-align:top}}
tr.ok td:first-child{{border-left:3px solid #2c2}} tr.warn td:first-child{{border-left:3px solid #fb0}} tr.fail td:first-child{{border-left:3px solid #f44}}
.ok{{color:#3d3}} .warn{{color:#fb0}} .fail,.bad{{color:#f66}}
.grid{{display:grid;grid-template-columns:560px 1fr;gap:16px;align-items:start}}
.grid img{{width:560px;border:1px solid #333;border-radius:4px}}
.data h4{{margin:8px 0 2px;color:#9cf}} ul{{margin:0;padding-left:18px}} li.foc{{color:#f66;font-weight:bold}}
.box{{color:#777;font-size:11px}} .graph div{{font-family:monospace;font-size:11px;color:#bbb}} .graph i{{color:#7a7}}
.flag{{display:inline-block;background:#532;color:#fb0;border-radius:3px;padding:1px 6px;margin-left:6px;font-size:11px}}
</style>
<h1>DOM exporter report &nbsp;<small>{summary}</small></h1>
<table><tr><th>image</th><th>screen</th><th>#</th><th>types</th><th>focus</th><th>flags</th></tr>{''.join(rows)}</table>
{''.join(sections)}'''
    with open(out, 'w', encoding='utf-8') as f:
        f.write(doc)
    print(f"{len(paths)} images → {out}  ({n_ok} ok, {n_nofocus} no-focus, {n_empty} empty, {n_failed} failed)")


if __name__ == '__main__':
    main()
