"""
Build an HTML DOM report for a userinterface from STORED node data, and persist it
to R2/MinIO (like the other reports) — built once per content signature, shared
across servers, served by streaming the R2 object (presigned MinIO URLs 400 through
the public proxy, so we don't hand the browser a direct R2 url).

Source: navigation_nodes.data.dom (generated + backfilled earlier). No LLM calls.
Per node: the <stem>_dom.jpg overlay (inlined base64), focusable elements, navigation
graph, and named-variant annotations (override / disabled / variant-only).

Cache: the report HTML lives at navigation/<ui>/dom_report.html with a sidecar
navigation/<ui>/dom_report.sig holding the content signature. A request rebuilds only
when the signature (node DOM versions + screenshot timestamps + variant mtimes) changes.

UX: sticky header with a node filter + expand/collapse-all, collapsible summary table
and per-node sections, floating jump-to-top/bottom controls.
"""
import base64
import hashlib
import html
import os
import re
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from shared.src.lib.database.navigation_trees_db import get_supabase, get_tree_nodes
from shared.src.lib.database.userinterface_db import get_userinterface_by_name, list_variants
from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils


def _to_key(s: str) -> str:
    key = re.sub(r'^https?://[^/]+/', '', str(s)).split('?', 1)[0]
    try:
        bucket = get_cloudflare_utils().bucket_name
        if bucket and key.startswith(f'{bucket}/'):
            key = key[len(bucket) + 1:]
    except Exception:
        pass
    return key


def _overlay_key(data: dict) -> Optional[str]:
    img = data.get('dom_image')
    if img:
        return _to_key(img)
    shot = data.get('screenshot') or data.get('screenshot_url')
    if not shot:
        return None
    return re.sub(r'\.(jpe?g|png)$', r'_dom.\1', _to_key(shot), flags=re.IGNORECASE)


def _collect(team_id: str, ui_id: str) -> tuple[dict, dict, list]:
    sb = get_supabase()
    trees = sb.table('navigation_trees').select('id').eq('userinterface_id', ui_id)\
        .eq('team_id', team_id).execute().data or []
    nodes_by_id: dict[str, dict] = {}
    for t in trees:
        for n in get_tree_nodes(t['id'], team_id, limit=500).get('nodes', []):
            nid = n.get('node_id')
            if not nid:
                continue
            has_dom = bool((n.get('data') or {}).get('dom'))
            prev = nodes_by_id.get(nid)
            if prev is None or (has_dom and not bool((prev.get('data') or {}).get('dom'))):
                nodes_by_id[nid] = n

    variants = list_variants(team_id, ui_id) or []
    vmap: dict[str, list] = {}
    for v in variants:
        name = v.get('name')
        for nid, ov in (v.get('node_overrides') or {}).items():
            ov = ov or {}
            label = 'disabled' if ov.get('disabled') else ('verifications' if 'verifications' in ov else 'override')
            vmap.setdefault(nid, []).append((name, label))
    return nodes_by_id, vmap, variants


def _signature(nodes_by_id: dict, variants: list) -> str:
    parts = []
    for nid in sorted(nodes_by_id):
        d = nodes_by_id[nid].get('data') or {}
        dom = d.get('dom') or {}
        parts.append(f"{nid}:{dom.get('_dom_meta', {}).get('v')}:{d.get('screenshot_timestamp')}")
    for v in variants:
        parts.append(f"V:{v.get('name')}:{v.get('updated_at')}")
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()


def _img_data_uri(key: str) -> str:
    if not key:
        return ''
    tmp = os.path.join(tempfile.gettempdir(), f"domrep_{uuid.uuid4().hex}.jpg")
    try:
        if not get_cloudflare_utils().download_file(key, tmp).get('success'):
            return ''
        with open(tmp, 'rb') as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode('ascii')
    except Exception:
        return ''
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


_STYLE = """
body{font:13px -apple-system,Segoe UI,Arial;background:#111;color:#ddd;margin:0;padding:0 16px 60px}
#hdr{position:sticky;top:0;z-index:20;background:#181818;border-bottom:1px solid #333;
     padding:8px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
#hdr b{font-size:15px} #hdr .sum{color:#888} #hdr select,#hdr button,#hdr a.btn{
     background:#222;color:#ddd;border:1px solid #444;border-radius:4px;padding:3px 8px;font-size:12px;cursor:pointer}
a{color:#6cf;text-decoration:none}
details{border-top:1px solid #2a2a2a;margin-top:6px} details>summary{cursor:pointer;padding:8px 0;font-size:14px;color:#cde}
details.node[data-focus="0"]>summary{color:#fb0}
small{color:#888;font-weight:normal}
table{border-collapse:collapse;width:100%;font-size:12px} td,th{border:1px solid #333;padding:3px 6px;text-align:left;vertical-align:top}
tr.ok td:first-child{border-left:3px solid #2c2} tr.warn td:first-child{border-left:3px solid #fb0} tr.none td:first-child{border-left:3px solid #555}
.grid{display:grid;grid-template-columns:560px 1fr;gap:16px;align-items:start;padding:6px 0 14px}
.grid img{width:560px;border:1px solid #333;border-radius:4px}
h4{margin:8px 0 2px;color:#9cf} .elements tr.foc td,.navigation tr.foc td{color:#f66!important;font-weight:bold;background:#2a1010}
code{color:#9cf} .box{color:#888;font-size:11px}
.badge{display:inline-block;background:#243;color:#9f9;border:1px solid #365;border-radius:3px;padding:0 5px;font-size:11px;margin-left:4px}
#jump{position:fixed;right:16px;bottom:16px;display:flex;flex-direction:column;gap:6px;z-index:30}
#jump a{background:#2a2a2a;border:1px solid #555;border-radius:50%;width:34px;height:34px;display:flex;
        align-items:center;justify-content:center;font-size:16px;color:#cde}
"""

_SCRIPT = """
function filterNode(v){
  document.querySelectorAll('details.node').forEach(function(d){
    var show = (!v || d.dataset.node===v);
    d.style.display = show ? '' : 'none';
    if(v && show) d.open = true;
  });
  document.querySelectorAll('tr[data-node]').forEach(function(r){
    r.style.display = (!v || r.dataset.node===v) ? '' : 'none';
  });
}
function toggleAll(open){
  document.querySelectorAll('details.node').forEach(function(d){
    if(d.style.display!=='none') d.open=open;
  });
}
"""


def _build_html(ui_name: str, nodes_by_id: dict, vmap: dict, variants: list, img_map: dict) -> str:
    rows, sections, options = [], [], []
    with_dom = focus_set = 0
    items = sorted(nodes_by_id.items(), key=lambda kv: str(
        (kv[1].get('label') or kv[1].get('data', {}).get('description') or kv[0])).lower())

    for nid, node in items:
        data = node.get('data') or {}
        dom = data.get('dom') or {}
        label = str(node.get('label') or data.get('description') or nid)
        els = dom.get('focusable_elements', []) or []
        nav = dom.get('navigation', {}) or {}
        focus = dom.get('focused_element_id')
        badges = vmap.get(nid, [])
        if node.get('hidden_in_base'):
            badges = [('(variant-only)', '')] + badges
        badge_html = ' '.join(
            f'<span class="badge">{html.escape(str(vn))}{(":" + lb) if lb else ""}</span>' for vn, lb in badges
        )
        has = bool(dom)
        if has:
            with_dom += 1
            focus_set += 1 if focus else 0
        cls = 'ok' if (has and focus) else ('warn' if has else 'none')
        options.append(f'<option value="{html.escape(nid)}">{html.escape(label)}</option>')
        rows.append(
            f'<tr class="{cls}" data-node="{html.escape(nid)}"><td><a href="#{html.escape(nid)}" '
            f'onclick="document.getElementById(\'{html.escape(nid)}\').open=true">{html.escape(label)}</a></td>'
            f'<td>{len(els)}</td><td>{html.escape(str(focus or "—"))}</td>'
            f'<td>{badge_html or "—"}</td>'
            f'<td>{html.escape(str(dom.get("_dom_meta", {}).get("model", "—")))}</td></tr>'
        )

        summary_line = (f'focus={html.escape(str(focus or "—"))} · elements={len(els)}' if has else 'no DOM')
        body = ''
        if has:
            okey = _overlay_key(data)
            uri = img_map.get(okey, '') if okey else ''
            img = f'<img src="{uri}" loading="lazy" />' if uri else ''
            el_rows = ''.join(
                f'<tr class="{"foc" if (e.get("focused") or e.get("id") == focus) else ""}">'
                f'<td>{e.get("index", i)}</td><td><code>{html.escape(str(e.get("id", "")))}</code></td>'
                f'<td>{html.escape(str(e.get("type", "")))}</td><td>{html.escape(str(e.get("label", "") or "—"))}</td>'
                f'<td>{html.escape(str(e.get("text_found", "") or "—"))}</td>'
                f'<td><span class="box">{html.escape(str(e.get("bbox", "")))}</span></td></tr>'
                for i, e in enumerate(els)
            )
            els_html = ('<table class="elements"><tr><th>#</th><th>id</th><th>type</th><th>label</th>'
                        '<th>text</th><th>bbox</th></tr>' + el_rows + '</table>') if el_rows else '<i>none</i>'
            nav_rows = ''.join(
                f'<tr class="{"foc" if k == focus else ""}"><td><code>{html.escape(str(k))}</code></td>'
                f'<td>{html.escape(str(v.get("LEFT")))}</td><td>{html.escape(str(v.get("RIGHT")))}</td>'
                f'<td>{html.escape(str(v.get("UP")))}</td><td>{html.escape(str(v.get("DOWN")))}</td>'
                f'<td>{html.escape(str(v.get("OK", "")))}</td><td>{html.escape(str(v.get("BACK", "")))}</td></tr>'
                for k, v in list(nav.items())[:120]
            )
            nav_html = ('<table class="navigation"><tr><th>element</th><th>L</th><th>R</th><th>U</th><th>D</th>'
                        '<th>OK</th><th>BACK</th></tr>' + nav_rows + '</table>') if nav_rows else '<i>none</i>'
            body = f'<div class="grid">{img}<div><h4>Elements</h4>{els_html}<h4>Navigation</h4>{nav_html}</div></div>'

        sections.append(
            f'<details class="node" id="{html.escape(nid)}" data-node="{html.escape(nid)}" '
            f'data-focus="{1 if focus else 0}" open>'
            f'<summary>{html.escape(label)} <small>{summary_line} {badge_html}</small></summary>{body}</details>'
        )

    vnames = ', '.join(html.escape(str(v.get('name'))) for v in variants) or 'none'
    summary = f"{len(items)} nodes · {with_dom} with DOM · {focus_set} focus set · variants: {vnames}"
    header = (
        f'<div id="hdr"><span id="top"></span><b>DOM report — {html.escape(ui_name)}</b>'
        f'<span class="sum">{html.escape(summary)}</span>'
        f'<select onchange="filterNode(this.value)"><option value="">All nodes</option>{"".join(options)}</select>'
        f'<button onclick="toggleAll(true)">Expand all</button>'
        f'<button onclick="toggleAll(false)">Collapse all</button></div>'
    )
    summary_table = (
        '<details id="summary" open><summary>Summary table</summary>'
        '<table><tr><th>node</th><th>els</th><th>focus</th><th>variants</th><th>model</th></tr>'
        + ''.join(rows) + '</table></details>'
    )
    jump = '<div id="jump"><a href="#top" title="Top">↑</a><a href="#bottom" title="Bottom">↓</a></div>'
    return (
        f'<!doctype html><meta charset="utf-8"><title>DOM report — {html.escape(ui_name)}</title>'
        f'<style>{_STYLE}</style>'
        f'{header}{summary_table}{"".join(sections)}<span id="bottom"></span>{jump}'
        f'<script>{_SCRIPT}</script>'
    )


# --- R2-backed persistence (the report is an artifact in storage, not per-server memory) ---

def _r2_text(key: str) -> Optional[str]:
    tmp = os.path.join(tempfile.gettempdir(), f"domrep_get_{uuid.uuid4().hex}")
    try:
        if not get_cloudflare_utils().download_file(key, tmp).get('success'):
            return None
        with open(tmp, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _r2_put_text(key: str, text: str) -> None:
    tmp = os.path.join(tempfile.gettempdir(), f"domrep_put_{uuid.uuid4().hex}")
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(text)
        get_cloudflare_utils().upload_files([{'local_path': tmp, 'remote_path': key}])
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def build_dom_report(ui_name: str, team_id: str) -> str:
    """Return the DOM report HTML for a userinterface, building + persisting it to R2
    only when the content signature changes; otherwise serve the stored R2 artifact."""
    ui = get_userinterface_by_name(ui_name, team_id)
    if not ui:
        return f"<h1>userinterface '{html.escape(ui_name)}' not found</h1>"

    nodes_by_id, vmap, variants = _collect(team_id, ui['id'])
    sig = _signature(nodes_by_id, variants)
    safe = re.sub(r'[^A-Za-z0-9_.-]', '_', ui_name)
    report_key = f"navigation/{safe}/dom_report.html"
    sig_key = f"navigation/{safe}/dom_report.sig"

    if _r2_text(sig_key) == sig:
        cached = _r2_text(report_key)
        if cached:
            return cached

    # Cache miss / changed -> rebuild: inline overlays (parallel), build, persist to R2.
    keys = []
    for n in nodes_by_id.values():
        d = n.get('data') or {}
        if d.get('dom'):
            k = _overlay_key(d)
            if k:
                keys.append(k)
    keys = list(dict.fromkeys(keys))
    img_map: dict[str, str] = {}
    if keys:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for k, uri in zip(keys, pool.map(_img_data_uri, keys)):
                img_map[k] = uri

    doc = _build_html(ui_name, nodes_by_id, vmap, variants, img_map)
    _r2_put_text(report_key, doc)
    _r2_put_text(sig_key, sig)
    return doc
