"""
Render a rebuilt graph as a readable text tree + a visual HTML report.

Inputs are the plain node/edge dicts the builder produced (MemorySink.nodes/.edges) so this
works offline with no DB. The HTML inlines the fixture screenshots as base64 so it is a
single self-contained file.
"""
import os
import base64
from typing import Dict, List, Optional, Any


def _adjacency(edges: Dict[str, Dict]) -> Dict[str, List]:
    adj: Dict[str, List] = {}
    for e in edges.values():
        keys = []
        if e.get('action_sets'):
            keys = [a.get('params', {}).get('key')
                    for a in e['action_sets'][0].get('actions', [])]
        adj.setdefault(e['source_node_id'], []).append(
            (e['target_node_id'], '+'.join(k for k in keys if k)))
    for s in adj:
        adj[s].sort(key=lambda x: x[0])
    return adj


def text_tree(nodes: Dict[str, Dict], edges: Dict[str, Dict],
              root: str = 'home') -> str:
    """ASCII tree via BFS from root; repeated nodes shown once then marked (↩)."""
    adj = _adjacency(edges)
    out: List[str] = []
    seen = set()

    def walk(nid: str, prefix: str, key: Optional[str], last: bool):
        branch = '└─' if last else '├─'
        tag = f"--{key}--> " if key else ""
        if nid in seen:
            out.append(f"{prefix}{branch} {tag}{nid} (↩)")
            return
        seen.add(nid)
        out.append(f"{prefix}{branch} {tag}{nid}")
        children = adj.get(nid, [])
        child_prefix = prefix + ('   ' if last else '│  ')
        for i, (tgt, k) in enumerate(children):
            walk(tgt, child_prefix, k, i == len(children) - 1)

    if root not in nodes:
        root = next(iter(nodes), None)
    if root:
        seen.add(root)
        out.append(root)
        children = adj.get(root, [])
        for i, (tgt, k) in enumerate(children):
            walk(tgt, '', k, i == len(children) - 1)
    # orphans (created but unreachable from root)
    orphans = [n for n in nodes if n not in seen]
    if orphans:
        out.append("")
        out.append(f"[unreached from {root}]: {', '.join(sorted(orphans))}")
    return '\n'.join(out)


def walk_text(result: Dict[str, Any], include_noops: bool = False) -> str:
    """Chronological key-by-key trace — one key press per step, as on the real STB.
    Reads from → key → to. Dead-end probes (no screen change) are hidden by default."""
    walk = result.get('walk') or []
    moves = sum(1 for w in walk if w['moved'])
    lines = [
        f"total presses: {result.get('presses')} ({moves} moved, "
        f"{len(walk) - moves} dead-end probes)  ·  "
        f"nodes/edges: {result.get('nodes')}/{result.get('edges')}",
        "",
        f"{'#':>4}  {'time':8}  {'t(s)':>7}  {'from':32} {'key':6} to",
        f"{'─'*4}  {'─'*8}  {'─'*7}  {'─'*32} {'─'*6} {'─'*22}",
    ]

    def fit(s: Any, width: int) -> str:
        s = str(s)
        return (s[:width - 1] + '…') if len(s) > width else s.ljust(width)

    n = 0
    for w in walk:
        if not include_noops and not w['moved']:
            continue
        n += 1
        to = w['to'] if w['moved'] else '(no change)'
        tcol = f"{w['t']:.1f}" if isinstance(w.get('t'), (int, float)) else '-'
        clock = w.get('clock') or '-'
        lines.append(f"{n:>4}  {clock:8}  {tcol:>7}  {fit(w['from'], 32)} {fit(w['key'], 6)} {to}")
    return '\n'.join(lines)


def discovery_list(nodes: Dict[str, Dict]) -> str:
    """Numbered list of nodes in the order they were discovered (dict insertion order)."""
    lines = []
    for i, nid in enumerate(nodes, 1):
        d = nodes[nid].get('data') or {}
        fp = d.get('fingerprint') or {}
        focus = (fp.get('focus') or {}).get('kind', '?')
        title = fp.get('title', '')
        lines.append(
            f"{i:2}. {nid:24} depth={d.get('depth', '?')!s:3} "
            f"focus={focus:5} title={title!r}")
    return '\n'.join(lines)


def steps_text(result: Dict[str, Any]) -> str:
    """Per-step timing table + totals from the builder result.

    A "step" = exploring ONE node (one BFS iteration). Within a step the builder presses
    keys to probe every direction; each press is one remote key action.
    """
    steps = result.get('steps') or []
    lines = [
        f"iterations (nodes explored):     {result.get('iterations', len(steps))}",
        f"presses (total remote keys sent):{result.get('presses')}",
        f"nodes / edges discovered:        {result.get('nodes')} / {result.get('edges')}",
        f"total duration:                  {result.get('duration_ms')} ms",
        "",
        "depth-first, one key at a time, DOM-driven. Steps in DISCOVERY order.",
        "via=key from parent · t=start(s) · press=own key presses · new=new screens · "
        "transitions: key→screen (* = new)",
        "",
        f"{'#':>3}  {'node':22} {'depth':>5} {'via':5} {'t(s)':>5} {'press':>5} {'new':>3}  transitions",
        f"{'─'*3}  {'─'*22} {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*3}  {'─'*40}",
    ]
    for s in steps:
        via = s.get('via') or 'start'
        trans = s.get('transitions') or []
        pretty = (', '.join(f"{t['keys']}→{t['dst']}{'*' if t['new'] else ''}" for t in trans)
                  if trans else '(leaf)')
        lines.append(f"{s['step']:>3}  {s['node']:22} {s.get('depth', '?')!s:>5} "
                     f"{via:5} {s['t_start_s']:>5} "
                     f"{s.get('presses', 0):>5} {s.get('new_nodes', 0):>3}  {pretty}")
    return '\n'.join(lines)


def _img_data_uri(path: str, max_bytes: int = 400_000) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) > max_bytes:  # keep the report light
        return None
    return 'data:image/jpeg;base64,' + base64.b64encode(data).decode()


def _esc(s: Any) -> str:
    return str(s if s is not None else '').replace('&', '&amp;').replace('<', '&lt;')


def _walk_html(result: Dict) -> str:
    """Walk as an HTML table with the resulting frame (thumbnail) after each action — the
    inline screenshot the device returned for that keypress."""
    walk = result.get('walk') or []
    rows = []
    n = 0
    for w in walk:
        if not w.get('moved'):
            continue
        n += 1
        t = f"{w['t']:.1f}" if isinstance(w.get('t'), (int, float)) else ''
        uri = _img_data_uri(w.get('shot')) if w.get('shot') else None
        thumb = (f"<a class=zoom href='#'><img src='{uri}'></a>" if uri else '')
        rows.append(
            f"<tr><td>{n}</td><td>{_esc(w.get('clock') or '')}</td><td>{t}</td>"
            f"<td>{_esc(w['from'])}</td><td class=k>{_esc(w['key'])}</td>"
            f"<td>{_esc(w['to'])}</td><td>{thumb}</td></tr>")
    return ("<table class=walk><tr><th>#<th>time<th>t(s)<th>from<th>key<th>to<th>frame</tr>"
            + ''.join(rows) + "</table>")


def _dom_tables(dom: Dict) -> str:
    """Per-node DOM detail column: focusable Elements + the Navigation map.

    Mirrors the Edit-node DOM tab: one row per focusable element, focused row highlighted.
    """
    els = (dom or {}).get('focusable_elements') or []
    if not els:
        return "<div class=domtab><span class=tag>no dom</span></div>"
    focused = dom.get('focused_element_id')
    nav = dom.get('navigation') or {}
    erows = []
    for i, e in enumerate(els):
        bb = e.get('bbox') or []
        bbtxt = '[' + ','.join(f"{float(v):.2f}" for v in bb) + ']' if len(bb) == 4 else ''
        cls = ' class=foc' if e.get('id') == focused else ''
        erows.append(
            f"<tr{cls}><td>{i}<td>{_esc(e.get('id'))}<td>{_esc(e.get('type'))}"
            f"<td>{_esc(e.get('label'))}<td>{_esc(e.get('text_found'))}<td>{bbtxt}</tr>")
    elements = ("<table class=dom><tr><th>#<th>id<th>type<th>label<th>text<th>bbox"
                + ''.join(erows) + "</table>")
    keys = ['LEFT', 'RIGHT', 'UP', 'DOWN', 'OK']
    nrows = []
    for e in els:
        eid = e.get('id')
        m = nav.get(eid) or {}
        cls = ' class=foc' if eid == focused else ''
        cells = ''.join(f"<td>{_esc(m.get(k)) if m.get(k) is not None else '·'}" for k in keys)
        nrows.append(f"<tr{cls}><td>{_esc(eid)}{cells}</tr>")
    navigation = ("<table class=dom><tr><th>element<th>L<th>R<th>U<th>D<th>OK"
                  + ''.join(nrows) + "</table>")
    return (f"<div class=domtab><div class=tag>Elements</div>{elements}"
            f"<div class=tag style='margin-top:8px'>Navigation</div>{navigation}</div>")


def html_report(nodes: Dict[str, Dict], edges: Dict[str, Dict],
                shots_dir: str, *, title: str = 'auto-build',
                diff: Optional[Dict[str, Any]] = None,
                tree_text: str = '', result: Optional[Dict[str, Any]] = None,
                dom_dir: Optional[str] = None) -> str:
    adj = _adjacency(edges)
    parts: List[str] = []
    parts.append(f"<!doctype html><meta charset=utf-8><title>{title}</title>")
    parts.append("<style>body{font:13px -apple-system,Arial;background:#111;color:#ddd;"
                 "margin:0;padding:16px}h2{border-bottom:1px solid #333;padding-top:14px}"
                 ".n{display:flex;gap:12px;border:1px solid #2a2a2a;border-radius:6px;"
                 "padding:8px;margin:8px 0;background:#181818}.n img{width:240px;height:auto;"
                 "border:1px solid #333;border-radius:4px}.meta{flex:1}code{color:#6cf}"
                 ".ph{width:240px;min-height:135px;display:flex;flex-direction:column;"
                 "align-items:center;justify-content:center;border:1px dashed #444;"
                 "border-radius:4px;color:#666;font-size:12px;text-align:center}"
                 ".k{color:#fc6}.miss{color:#f77}.ok{color:#7d7}pre{background:#0c0c0c;"
                 "padding:10px;border-radius:6px;overflow:auto;line-height:1.4}"
                 ".tag{font-size:11px;color:#888}"
                 "summary{cursor:pointer;font-size:15px;font-weight:bold;padding:8px 0;"
                 "border-bottom:1px solid #333;margin-top:8px}"
                 "details>:not(summary){margin-top:8px}"
                 ".domtab{width:520px;font-size:11px;overflow:auto;max-height:380px}"
                 "table.dom{border-collapse:collapse;width:100%;margin-top:2px}"
                 "table.dom th,table.dom td{border:1px solid #2a2a2a;padding:1px 4px;"
                 "text-align:left;white-space:nowrap}table.dom th{color:#888;font-weight:normal}"
                 "table.dom tr.foc{background:#3a1414}"
                 "table.walk{border-collapse:collapse;width:100%;font-size:12px}"
                 "table.walk th,table.walk td{border:1px solid #2a2a2a;padding:4px 6px;"
                 "text-align:left;vertical-align:top}table.walk th{color:#888;font-weight:normal}"
                 "table.walk img{width:220px;border:1px solid #333;border-radius:3px;display:block}"
                 "</style>")
    parts.append(f"<h1>{title}</h1>")

    if diff:
        n, e = diff['nodes'], diff['edges']
        parts.append(f"<p><b>Coverage</b> — nodes {n['covered']}/{n['truth']} "
                     f"(<span class=ok>{n['coverage']*100:.0f}%</span>), "
                     f"edges {e['covered']}/{e['truth']} "
                     f"(<span class=ok>{e['coverage']*100:.0f}%</span>)</p>")
        if n['missing']:
            parts.append(f"<p class=miss><b>missing nodes:</b> {', '.join(n['missing'])}</p>")
        if n['extra']:
            parts.append(f"<p class=tag>extra nodes: {', '.join(n['extra'])}</p>")

    def section(title, body_html, open_=True):
        parts.append(f"<details{' open' if open_ else ''}><summary>{title}</summary>"
                     + body_html + "</details>")

    if result:
        # Walk with per-step frames when the steps carry inline screenshots; else plain text.
        has_frames = any(w.get('shot') for w in (result.get('walk') or []))
        section("Walk — one key per step",
                _walk_html(result) if has_frames
                else "<pre>" + walk_text(result).replace('<', '&lt;') + "</pre>")
        section("Steps — per node",
                "<pre>" + steps_text(result).replace('<', '&lt;') + "</pre>", open_=False)

    if tree_text:
        section("Tree", "<pre>" + tree_text.replace('<', '&lt;') + "</pre>", open_=False)

    parts.append("<details><summary>Nodes (in discovery order)</summary>")
    for i, nid in enumerate(nodes, 1):       # dict preserves discovery order
        node = nodes[nid]
        d = node.get('data') or {}
        shot = d.get('screenshot')
        shot_uri = _img_data_uri(os.path.join(shots_dir, os.path.basename(shot))) if shot else None
        # Single visual column: prefer the DOM overlay (screenshot + boxes); fall back to the
        # raw screenshot when no overlay exists. The overlay already IS the screenshot, so a
        # separate raw-screenshot column is redundant.
        dom_img = d.get('dom_image')
        dom_uri = None
        if dom_img:
            base = os.path.basename(dom_img)
            for cand in ([os.path.join(dom_dir, base)] if dom_dir else []) + \
                        [os.path.join(shots_dir, base)]:
                if os.path.exists(cand):
                    dom_uri = _img_data_uri(cand)
                    break
        visual_uri = dom_uri or shot_uri
        # Click the image to open it full-size in a new tab (via JS blob — a data: href would
        # be blocked by the browser and open about:blank).
        visual = (f"<a class=zoom href='#' title='open image in new tab'>"
                  f"<img src='{visual_uri}'></a>" if visual_uri
                  else "<div class=ph>no image</div>")
        outs = adj.get(nid, [])
        fp = d.get('fingerprint') or {}
        focus = fp.get('focus') or {}
        fp_txt = (f"dhash <code>{(fp.get('dhash') or '')[:12]}…</code> · "
                  f"focus <span class=k>{focus.get('kind','?')}</span>"
                  + (f" x={focus.get('x'):.3f}" if isinstance(focus.get('x'), (int, float)) else "")
                  + (f" · title <i>{fp.get('title','')}</i>" if fp.get('title') else ""))
        dom = d.get('dom') or {}
        fe = dom.get('focusable_elements') or []
        dom_txt = (f"{len(fe)} focusable · focused=<code>{dom.get('focused_element_id')}</code>"
                   if dom else "<span class=tag>no dom</span>")
        edges_html = ''.join(
            f"<div><span class=k>{k or '?'}</span> → <code>{t}</code></div>"
            for t, k in outs) or "<span class=tag>no outgoing edges</span>"
        parts.append(
            f"<div class=n>{visual}<div class=meta><b>{i}. {nid}</b>"
            f"<div class=tag>depth: <code>{d.get('depth', '?')}</code></div>"
            f"<div class=tag>fingerprint: {fp_txt}</div>"
            f"<div class=tag>dom: {dom_txt}</div>"
            f"<div style='margin-top:6px'>{edges_html}</div></div>{_dom_tables(dom)}</div>")
    parts.append("</details>")
    # Open any clicked image full-size in a new tab. We read the <img> data: URI, turn it into
    # a blob URL and open THAT — browsers block top-level navigation to data: URIs (about:blank).
    parts.append(
        "<script>document.addEventListener('click',function(e){"
        "var a=e.target.closest('a.zoom');if(!a)return;e.preventDefault();"
        "var img=a.querySelector('img');if(!img)return;"
        "fetch(img.src).then(function(r){return r.blob();})"
        ".then(function(b){window.open(URL.createObjectURL(b),'_blank');});});</script>")
    return '\n'.join(parts)
