#!/usr/bin/env python3
"""Push a local auto-build run (state.json) into the DB as a userinterface you can open in the
tree view — e.g. `example_tv_autobuild` next to the real `example_tv`.

It partitions the flat graph into <=2-level canvases the way example_tv is organised (a sibling row
+ their dive children; deeper content becomes a subtree headed by the menu node), lays siblings out
horizontally and dive children below, sets edge handles (horizontal for siblings, vertical "menu"
handles for parent->child), and presses the discovered remote key per edge. See
docs/agent/INTERFACE_EXPLORATION_AI.md. Idempotent by UI name; grafts onto the protected entry->home skeleton.

Usage:
  # env must point at the target Supabase (SUPABASE_URL + SUPABASE_ANON_KEY)
  python3 features/avq/backend_host/localize/push_autobuild_to_db.py \
      --run-dir features/avq/backend_host/localize/live_runs/fr_full \
      --ui-name example_tv_autobuild \
      --team-id 7fdeb4bb-3639-4ec3-959f-b54769a219ce \
      --models stb
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Make the shared lib importable regardless of CWD.
REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

import os  # noqa: E402

# Load DB credentials from a .env the way the server does (python-dotenv parses values with
# special chars that bash `source` chokes on). Honor --env-file, else the CWD/.env, else REPO/.env.
def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    for cand in (os.getenv("AUTOBUILD_ENV_FILE"), Path.cwd() / ".env", REPO / ".env"):
        if cand and Path(cand).exists():
            load_dotenv(cand)
            return


_load_env()

from shared.src.lib.utils.supabase_utils import get_supabase_client  # noqa: E402

# example_tv's team, so the auto-built UI lands beside it.
DEFAULT_TEAM = os.getenv("VPT_TEAM_ID", "7fdeb4bb-3639-4ec3-959f-b54769a219ce")
COL_W, ROW_H = 320, 220          # layout: siblings spread horizontally (x), dive children below (y)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ReactFlow handle ids (from Navigation_NavigationNode.tsx). Siblings connect horizontally
# (Left/Right); parent->child dives connect vertically via the "menu" handles (Top/Bottom).
H_SIB = ("right-source", "left-target")
H_DIVE = ("bottom-right-menu-source", "top-right-menu-target")

# Per-key settle (ms): focus moves are quick, OK/BACK change the screen.
KEY_WAIT = {"OK": 5000, "BACK": 5000}
_DIRS = {"RIGHT", "LEFT", "UP", "DOWN"}


def _key_wait(k: str) -> int:
    return KEY_WAIT.get(str(k).upper(), 1000)


def _edge_keys(e: dict) -> list:
    """Forward key SEQUENCE of an edge. Supports multi-key (`keys: [..]`, e.g. [RIGHT,OK]) and the
    legacy single `key`."""
    if e.get("keys"):
        return list(e["keys"])
    return [e["key"]]


def _primary_dir(keys) -> str:
    """The directional key that drives 2-D layout (first RIGHT/LEFT/UP/DOWN in the sequence)."""
    for k in keys:
        if str(k).upper() in _DIRS:
            return str(k).upper()
    return str(keys[0]).upper() if keys else ""


def _build_out(state: dict, for_layout: bool = False) -> dict:
    """nid -> [(target, keys, is_sibling)] for every observed edge (keys is the forward sequence).
    With for_layout, skip `no_layout` edges (e.g. the ring's wrap edge) so they add navigation
    without shifting the grid."""
    nodes = state["nodes"]
    out = {nid: [] for nid in nodes}
    for e in state["edges"]:
        s, t = e["source"], e["target"]
        # `reverse` edges (the verified BACK of a dive) exist only to fill the backward
        # action set — never navigation structure. Letting them into `out` would make every
        # dive leaf "have children" and turn it into a menu head in _partition.
        if e.get("reverse"):
            continue
        if for_layout and e.get("no_layout"):
            continue
        if s in nodes and t in nodes:
            out[s].append((t, _edge_keys(e), nodes[t].get("kind") == "sibling"))
    return out


def _partition(state: dict):
    """Split the flat graph into <=2-level canvases the way example_tv is organised. A canvas =
    a sibling row (level 0) + their direct dive children (level 1). A dive child that itself has
    children becomes a menu node: it stays in this canvas AND heads a subtree (parent_node_id ->
    it) holding its own sibling row + children. Recurses, so every canvas stays shallow.

    Returns (canvases, out). Each canvas: {idx, head, lvl0[], lvl1[], members[], menus(set),
    parent_idx, parent_node}."""
    nodes = state["nodes"]
    out = _build_out(state)
    has_children = {nid: bool(out.get(nid)) for nid in nodes}
    root = next(nid for nid, n in nodes.items() if not n.get("path"))

    # The auto-build graph is a DAG, not a tree: it has back-edges (settings -> home) and screens
    # reached from several places (suchen). A global `placed` set makes each node land in the FIRST
    # canvas that reaches it (a spanning tree); later dives to an already-placed node are dropped
    # as redundant cross-links, which keeps the partition finite and the canvases clean.
    placed = {root}
    canvases, work = [], [(root, None, None)]
    while work:
        head, p_idx, p_node = work.pop(0)
        idx = len(canvases)
        # level 0: the head plus its UNPLACED sibling closure
        lvl0, stack, local = [head], [head], {head}
        while stack:
            cur = stack.pop()
            for tgt, _k, is_sib in out.get(cur, []):
                if is_sib and tgt not in local and tgt not in placed:
                    local.add(tgt); placed.add(tgt); lvl0.append(tgt); stack.append(tgt)
        # level 1: UNPLACED dive children of the level-0 row
        lvl1, menus = [], []
        for s in lvl0:
            for tgt, _k, is_sib in out.get(s, []):
                if is_sib or tgt in local or tgt in placed:
                    continue
                local.add(tgt); placed.add(tgt); lvl1.append(tgt)
                if has_children.get(tgt):
                    menus.append(tgt)
                    work.append((tgt, idx, tgt))     # tgt heads its own subtree
        canvases.append({"idx": idx, "head": head, "lvl0": lvl0, "lvl1": lvl1,
                         "members": lvl0 + lvl1, "menus": set(menus),
                         "parent_idx": p_idx, "parent_node": p_node})
    return canvases, out


def _node_data(state: dict, nid: str, assets: dict) -> dict:
    n = state["nodes"][nid]
    label = n.get("label") or n.get("external_app") or nid
    data = {
        "type": "screen",
        "is_root": not n.get("path"),
        "depth": n.get("depth"),
        "description": label,
        "kind": n.get("kind"),
        "terminal": bool(n.get("terminal")),
        "dom": (json.loads(Path(n["dom"]).read_text()) if n.get("dom")
                and Path(n["dom"]).exists() else {}),
        "fingerprint": n.get("fingerprint") or {},
        "autobuild_path": "+".join(n.get("path") or []) or "HOME",
    }
    a = assets.get(nid) or {}
    if a.get("screenshot"):
        data["screenshot"] = a["screenshot"]
    if a.get("dom_image"):
        data["dom_image"] = a["dom_image"]
    if n.get("terminal"):
        data["terminal_kind"] = n.get("kind")        # external | dynamic
    return data


def _canvas_positions(state, canvas):
    """(x, y) per node, respecting the on-screen grid. Siblings are laid out in 2-D from the head
    by their actual navigation — RIGHT/LEFT move column (x), DOWN/UP move row (y) — so a nav row
    stays a row and an app grid stays a grid. Dive children sit in the rows BELOW the whole sibling
    grid, each under its parent's column (fanned out if a parent has several). Normalized to (0,0)."""
    from collections import deque, defaultdict
    out = _build_out(state, for_layout=True)
    lvl0, lvl1 = set(canvas["lvl0"]), set(canvas["lvl1"])
    DCOL = {"RIGHT": 1, "LEFT": -1}
    DROW = {"DOWN": 1, "UP": -1}

    # 2-D sibling grid from the head
    grid = {canvas["head"]: (0, 0)}                    # nid -> (col, row)
    via = {}                                           # nid -> (anchor nid, direction)
    dq = deque([canvas["head"]])
    while dq:
        cur = dq.popleft()
        c, r = grid[cur]
        for tgt, keys, is_sib in out.get(cur, []):
            if is_sib and tgt in lvl0 and tgt not in grid:
                d = _primary_dir(keys)
                grid[tgt] = (c + DCOL.get(d, 0), r + DROW.get(d, 0))
                via[tgt] = (cur, d)
                dq.append(tgt)
    nc = max((c for c, _ in grid.values()), default=0) + 1
    for nid in canvas["lvl0"]:                          # stragglers reached only via odd keys
        if nid not in grid:
            grid[nid] = (nc, 0); nc += 1

    # Column order within a NAV row must match the ON-SCREEN menu, not the BFS discovery
    # direction: once LEFT probes exist the ring wraps, and BFS reaches the menu's far end
    # via LEFT from the head — placing recordings/settings/profile at negative columns,
    # LEFT of search (stb3_sim, 2026-07-17). The nav underline x IS the on-screen position
    # (stored on every sibling fingerprint), so rows whose members all carry one are
    # re-ordered by it across the same column span.
    rows = defaultdict(list)
    for nid, (c, r) in grid.items():
        rows[r].append(nid)
    for r, members in rows.items():
        focus = {nid: ((state["nodes"][nid].get("fingerprint") or {}).get("focus") or {})
                 for nid in members}
        if len(members) > 1 and all(f.get("kind") == "nav" and f.get("x") is not None
                                    for f in focus.values()):
            cols = sorted(grid[nid][0] for nid in members)
            for col, nid in zip(cols, sorted(members, key=lambda n: float(focus[n]["x"]))):
                grid[nid] = (col, r)
    # vertical placements (DOWN/UP siblings like home_watch) follow their anchor's
    # re-ordered column — BFS order guarantees anchors are remapped before dependents
    for nid, (src, d) in via.items():
        if d in DROW:
            grid[nid] = (grid[src][0], grid[nid][1])
    max_row = max((r for _, r in grid.values()), default=0)

    # dive children: in the rows below the grid, under their parent's column. Children sharing a
    # column (different parents in the same column, or one parent with several) STACK vertically so
    # nothing overlaps.
    parent_of = {}
    for s in canvas["lvl0"]:
        for tgt, _k, is_sib in out.get(s, []):
            if not is_sib and tgt in lvl1:
                parent_of.setdefault(tgt, s)
    by_col = defaultdict(list)
    for child in canvas["lvl1"]:
        by_col[grid.get(parent_of.get(child, canvas["head"]), (0, 0))[0]].append(child)

    fpos = {nid: (float(c), float(r)) for nid, (c, r) in grid.items()}
    for c, kids in by_col.items():
        for i, child in enumerate(kids):
            fpos[child] = (float(c), max_row + 1 + i)
    minc = min(c for c, _ in fpos.values())
    minr = min(r for _, r in fpos.values())
    return {nid: (round((c - minc) * COL_W), round((r - minr) * ROW_H))
            for nid, (c, r) in fpos.items()}


def _collect_dom_texts(state):
    """All text_found values per node (lowercased) — for cross-node uniqueness."""
    texts = {}
    for nid, node in state["nodes"].items():
        dom_path = node.get("dom")
        vals = set()
        if dom_path and os.path.exists(dom_path):
            try:
                dom = json.loads(Path(dom_path).read_text(encoding="utf-8"))
                for el in dom.get("focusable_elements", []):
                    t = str(el.get("text_found") or "").strip()
                    if len(t) >= 3:
                        vals.add(t.lower())
            except Exception:
                pass
        texts[nid] = vals
    return texts


def _node_verifications(state, nid, dom_texts, img_size_cache):
    """Ladder D: one auto text verification per node, or [] when we can't do it honestly.

    Picks the node's most distinctive visible text — a text_found that appears in NO
    other node's DOM this run — and anchors waitForTextToAppear on that element's
    bbox (denormalized to the capture resolution, padded 15% per side). No unique
    text, no DOM, or no screenshot ⇒ [] (a vacuous verification is worse than none:
    verify_node passes empty arrays silently — see GOAL-02 audit P0.1).
    """
    node = state["nodes"].get(nid) or {}
    dom_path = node.get("dom")
    shot = node.get("screenshot")
    if not dom_path or not os.path.exists(dom_path) or not shot or not os.path.exists(shot):
        return []
    try:
        dom = json.loads(Path(dom_path).read_text(encoding="utf-8"))
    except Exception:
        return []

    others = set()
    for other_nid, vals in dom_texts.items():
        if other_nid != nid:
            others |= vals

    candidate = None
    for el in dom.get("focusable_elements", []):
        t = str(el.get("text_found") or "").strip()
        bbox = el.get("bbox")
        if len(t) >= 3 and t.lower() not in others and isinstance(bbox, list) and len(bbox) == 4:
            candidate = (t, bbox)
            break
    if candidate is None:
        return []

    if shot not in img_size_cache:
        try:
            from PIL import Image
            with Image.open(shot) as im:
                img_size_cache[shot] = im.size
        except Exception:
            img_size_cache[shot] = (1280, 720)  # STB capture default; padded area tolerates it
    iw, ih = img_size_cache[shot]

    text, (bx, by, bw, bh) = candidate
    pad_x, pad_y = bw * 0.15, bh * 0.15
    x = max(0, int((bx - pad_x) * iw))
    y = max(0, int((by - pad_y) * ih))
    w = min(iw - x, int((bw + 2 * pad_x) * iw))
    h = min(ih - y, int((bh + 2 * pad_y) * ih))
    return [{
        "command": "waitForTextToAppear",
        "verification_type": "text",
        "params": {"text": text, "timeout": 10, "check_interval": 1,
                   "area": {"x": x, "y": y, "width": w, "height": h}},
        "expected": True,
    }]


def _canvas_node_rows(state, canvas, tree_id, team, id_of, assets, skip_head=False):
    """DB node rows for one canvas: level-0 siblings on a horizontal row, level-1 dive children
    directly below their parent. Menu nodes carry has_subtree so the frontend lets you enter it."""
    pos = _canvas_positions(state, canvas)
    # Ladder D: per-node auto verifications (computed once per push, memoized on state)
    if "_dom_texts" not in state:
        state["_dom_texts"] = _collect_dom_texts(state)
    dom_texts = state["_dom_texts"]
    img_size_cache = state.setdefault("_img_size_cache", {})
    rows = []
    for nid in canvas["members"]:
        if skip_head and nid == canvas["head"]:
            continue                                  # root head is the protected `home` (updated, not inserted)
        is_menu = nid in canvas["menus"]
        x, y = pos[nid]
        rows.append({
            "tree_id": tree_id,
            "node_id": id_of(nid),
            "label": state["nodes"][nid].get("label") or state["nodes"][nid].get("external_app") or nid,
            "node_type": "screen",
            "position_x": x, "position_y": y,
            "data": _node_data(state, nid, assets),
            "style": {},
            "verifications": _node_verifications(state, nid, dom_texts, img_size_cache),
            "has_subtree": is_menu,
            "subtree_count": 1 if is_menu else 0,
            "team_id": team,
            "created_at": _now(), "updated_at": _now(),
        })
    return rows


def _action_set(state, src_nid, dst_nid, set_id, keys, strip=False, dst_node_id=None):
    """One action set = the full key SEQUENCE for this direction, each press carrying its per-key
    settle (d-pad 1s, OK/BACK 5s). `keys` may be a single key or a list (multi-key edge, [RIGHT,OK]).

    strip=True marks a commit-strip compound [DIR, OK]: the DIRECTIONAL press becomes
    position-independent — `repeat_until` the destination pane appears (max 7), then OK — so the
    edge works no matter which tab the strip remembers (the tab cache). Mirrors stb_tv's authored
    `RIGHT repeat_until(target) + OK`."""
    keys = [keys] if isinstance(keys, str) else list(keys)
    actions = []
    for k in keys:
        act = {"command": "press_key", "params": {"key": k, "wait_time": _key_wait(k)},
               "device_model": "remote"}
        if strip and k in ("RIGHT", "LEFT", "DOWN", "UP") and dst_node_id:
            # walk the strip until the target pane's fingerprint appears, then the OK commits it
            act["iterator"] = 7
            act["repeat_until"] = {"match": "all", "source": "node", "condition": "appears",
                                   "poll_wait_ms": 500, "verifications": [],
                                   "max_iterations": 7, "target_node_id": dst_node_id}
        actions.append(act)
    return {
        "id": set_id,
        "label": f"{state['nodes'][src_nid].get('label') or src_nid} → "
                 f"{state['nodes'][dst_nid].get('label') or dst_nid} ({'+'.join(keys)})",
        "actions": actions,
        "retry_actions": [], "failure_actions": [], "final_wait_time": 0,
    }


def _focus_of(state, nid):
    return ((state["nodes"].get(nid) or {}).get("fingerprint") or {}).get("focus") or {}


def _is_committed_focus(f):
    """Underline on the bold/selected tab (a resting pane) vs a hover. None when no selected_x."""
    sx = f.get("selected_x")
    if sx is None or f.get("x") is None:
        return None
    return abs(float(f["x"]) - float(sx)) <= 0.03


def _norm_title(state, nid):
    import re
    return re.sub(r"\W+", " ", str(((state["nodes"].get(nid) or {}).get("fingerprint") or {})
                                    .get("title") or "").lower()).strip()


def _collapse_strip_hovers(state):
    """Absorb transient commit-strip HOVER nodes into compound <DIR>+OK sibling edges.

    A settings-tab hover (nav focus, underline NOT on the bold tab) is not a resting state —
    the meaningful node is the committed pane its OK reaches. Collapse `P --DIR--> H --OK--> C`
    into `P --[DIR,OK]--> C` and drop H, so only committed panes remain (the stb_tv shape).

    STRICTLY lateral only: H is collapsed iff its OK lands on a nav COMMITTED pane on the SAME
    titled bar. This spares the home ring — home_tvguide is also focus≠selected, but its OK
    DIVES to a different-titled screen (tvguide), so it is a real launch node and is kept.
    """
    nodes, edges = state["nodes"], state["edges"]

    def is_hover(nid):
        f = _focus_of(state, nid)
        return f.get("kind") == "nav" and _is_committed_focus(f) is False

    def committed_pane(nid):
        f = _focus_of(state, nid)
        return f.get("kind") == "nav" and _is_committed_focus(f) is True

    removed, new_edges = set(), []
    for H in list(nodes):
        if not is_hover(H):
            continue
        ok_out = [e for e in edges if e["source"] == H and not e.get("reverse") and e["key"] == "OK"]
        if len(ok_out) != 1:
            continue
        C = ok_out[0]["target"]
        # lateral gate: OK commits a same-bar pane (not a dive) — spares the home ring
        if not (committed_pane(C) and _norm_title(state, H) == _norm_title(state, C)
                and _norm_title(state, H)):
            continue
        inbound = [e for e in edges if e["target"] == H and not e.get("reverse")
                   and e["key"] in ("RIGHT", "LEFT", "DOWN", "UP")]
        for ib in inbound:
            if ib["source"] in (H, C):
                continue
            new_edges.append({"source": ib["source"], "key": ib["key"],
                              "keys": [ib["key"], "OK"], "target": C,
                              "observed_capture": ok_out[0].get("observed_capture"),
                              "strip": True})
        removed.add(H)

    if not removed:
        return 0
    state["edges"] = [e for e in edges
                      if e["source"] not in removed and e["target"] not in removed] + new_edges
    for H in removed:
        nodes.pop(H, None)
    return len(removed)


def _relabel_strip_panes(state, run_dir):
    """Name committed panes by their ORDER in the RIGHT chain mapped to the strip DOM's tab
    list — reflow-independent, unlike the x-snapped DOM element (which mislabeled
    soundimage as Parental control, 2026-07-17). chain[i] -> tab[i]."""
    from pathlib import Path
    edges, nodes = state["edges"], state["nodes"]
    right = {e["source"]: e["target"] for e in edges
             if e.get("strip") and (e.get("keys") or [""])[0] == "RIGHT"}
    heads = [s for s in right if s not in set(right.values())]
    relabelled = 0
    for head in heads:
        dom_path = nodes[head].get("dom")
        if not dom_path:
            continue
        p = Path(dom_path)
        if not p.exists():
            p = run_dir / "dom" / p.name
        if not p.exists():
            continue
        dom = json.loads(p.read_text())
        tabs = [_sanitize_label(_element_short_id(e.get("id"))).replace("_", "")
                for e in dom.get("focusable_elements", []) if e.get("type") == "tab"]
        if not tabs:
            continue
        base = (nodes[head].get("label") or "").split("_")[0] or tabs[0]
        chain, cur = [head], head
        while cur in right:
            cur = right[cur]
            chain.append(cur)
        for i, nid in enumerate(chain):
            if i < len(tabs):
                nodes[nid]["label"] = base if i == 0 else f"{base}_{tabs[i]}"
                relabelled += 1
    return relabelled


def _element_short_id(elem_id):
    import re
    e = re.sub(r"^(nav|btn|button|tab|menu|item|card|tile|icon)_", "", (elem_id or "").strip().lower())
    e = re.sub(r"_(nav|btn|button|tab|menu|item|card|tile|icon)$", "", e)
    return e or "el"


def _canvas_edge_rows(state, canvas, tree_id, team, id_of):
    """One DB edge per NODE PAIR whose both ends live in this canvas. A pair observed in both
    directions (A→B and B→A) becomes a single edge with forward+backward action sets (the platform
    convention), not two edges. Sibling pairs (same level) get horizontal handles; dive pairs
    (cross level) get vertical menu handles."""
    members = set(canvas["members"])
    out = _build_out(state)
    rank = {}
    for i, nid in enumerate(canvas["lvl0"]):
        rank[nid] = (0, i)
    for j, nid in enumerate(canvas["lvl1"]):
        rank[nid] = (1, j)

    strip_dir = {(e["source"], e["target"]) for e in state["edges"] if e.get("strip")}
    # A DOWN/UP edge onto a pane ROW is position-independent the same way tab edges are (the
    # row cursor can persist): mark it strip so it pushes as `DOWN repeat_until(row) + OK`.
    for e in state["edges"]:
        if e.get("reverse") or e["key"] not in ("DOWN", "UP"):
            continue
        if _focus_of(state, e["target"]).get("kind") == "row":
            strip_dir.add((e["source"], e["target"]))

    pairs = {}        # frozenset({a,b}) -> {(s,t): keys}
    for s in canvas["members"]:
        for tgt, keys, _is_sib in out.get(s, []):
            if tgt in members:
                pairs.setdefault(frozenset((s, tgt)), {})[(s, tgt)] = keys
    # `reverse` edges (verified dive-BACKs, excluded from `out`) fill the missing direction of
    # their pair so the dive edge ships with a backward action set. setdefault: a real observed
    # forward edge in that direction (e.g. a settings->home cross-link) always wins over BACK.
    for e in state["edges"]:
        if not e.get("reverse"):
            continue
        s, t = e["source"], e["target"]
        if s in members and t in members:
            pairs.setdefault(frozenset((s, t)), {}).setdefault((s, t), _edge_keys(e))

    rows = []
    for n, (fs, dirs) in enumerate(pairs.items()):
        if len(dirs) == 2:                            # bidirectional -> forward low-rank, backward high
            a, b = sorted(fs, key=lambda x: rank.get(x, (9, 9)))
            fwd_keys, bwd_keys = dirs[(a, b)], dirs[(b, a)]
        else:
            (a, b), fwd_keys = next(iter(dirs.items()))
            bwd_keys = None
        src, dst = id_of(a), id_of(b)
        cross = rank.get(a, (0, 0))[0] != rank.get(b, (0, 0))[0]
        sh, th = (H_DIVE if cross else H_SIB)
        fwd_id = f"{src}_to_{dst}"
        action_sets = [_action_set(state, a, b, fwd_id, fwd_keys,
                                   strip=(a, b) in strip_dir, dst_node_id=dst)]
        if bwd_keys:
            action_sets.append(_action_set(state, b, a, f"{dst}_to_{src}", bwd_keys,
                                           strip=(b, a) in strip_dir, dst_node_id=src))
        rows.append({
            "tree_id": tree_id,
            "edge_id": f"edge-{src}-{dst}-{n}",
            "source_node_id": src, "target_node_id": dst,
            "data": {"sourceHandle": sh, "targetHandle": th, "priority": "p3",
                     "is_conditional": False, "is_conditional_primary": False},
            "default_action_set_id": fwd_id,
            "action_sets": action_sets,
            "team_id": team,
            "created_at": _now(), "updated_at": _now(),
        })
    return rows


def _upload_assets(state: dict, ui_name: str, run_dir: Path) -> dict:
    """Upload each node's screenshot (PNG -> JPG) and DOM overlay to R2 under
    navigation/<ui_name>/<label>.jpg and <label>_dom.jpg (the same key shape example_tv uses),
    and return {node_id: {screenshot, dom_image}} of storage keys to embed in node data.
    Terminal nodes (no capture) are skipped. Requires CLOUDFLARE_R2_* env."""
    import tempfile
    import cv2
    from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils

    prefix = f"navigation/{ui_name}"
    caps, overlays = run_dir / "captures", run_dir / "dom_overlays"
    mappings, plan = [], {}        # plan: nid -> {'screenshot': key, 'dom_image': key}
    tmp = Path(tempfile.mkdtemp(prefix="autobuild_assets_"))
    for nid, n in state["nodes"].items():
        label = _sanitize_label(n.get("label") or n.get("external_app") or nid)
        # Resolve assets RELATIVE to the run-dir (state.json stores absolute authoring-machine
        # paths that don't exist here), by basename under captures/ and dom_overlays/.
        shot = caps / Path(n["screenshot"]).name if n.get("screenshot") else None
        if shot and shot.exists():
            jpg = tmp / f"{label}.jpg"
            img = cv2.imread(str(shot))
            if img is not None:
                cv2.imwrite(str(jpg), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
                key = f"{prefix}/{label}.jpg"
                mappings.append({"local_path": str(jpg), "remote_path": key,
                                 "content_type": "image/jpeg"})
                plan.setdefault(nid, {})["screenshot"] = key
        dom_img = overlays / (Path(n["dom_image"]).name if n.get("dom_image")
                              else f"{nid}_dom.jpg")
        if dom_img.exists():
            key = f"{prefix}/{label}_dom.jpg"
            mappings.append({"local_path": str(dom_img), "remote_path": key,
                             "content_type": "image/jpeg"})
            plan.setdefault(nid, {})["dom_image"] = key

    if not mappings:
        print("no local assets to upload")
        return {}
    result = get_cloudflare_utils().upload_files(mappings, auto_delete_cold=False)
    ok = result.get("uploaded_count", 0) if isinstance(result, dict) else 0
    failed = result.get("failed_count", 0) if isinstance(result, dict) else len(mappings)
    print(f"uploaded {ok}/{len(mappings)} assets to {prefix}/ (failed={failed}; "
          f"screenshots + _dom overlays for {len(plan)} nodes)")
    if failed:                                   # drop keys whose upload failed so we don't point at nothing
        bad = {f.get("remote_path") for f in (result.get("failed_uploads") or [])}
        for nid, a in list(plan.items()):
            for kind in ("screenshot", "dom_image"):
                if a.get(kind) in bad:
                    a.pop(kind, None)
    return plan


def _sanitize_label(value: str) -> str:
    import re
    return (re.sub(r"[^a-z0-9]+", "_", (value or "screen").lower()).strip("_") or "screen")[:48]


def _graft_subtree(sb, state, run_dir, args, canvases) -> int:
    """Overwrite (or create) the subtree under a named node in an EXISTING UI, instead of building a
    standalone UI. The run's root maps onto that node (its in-tree copy heads the subtree). Used to
    drop a freshly-rebuilt screen (e.g. the corrected settings) back into example_tv_autobuild
    without disturbing the rest of the tree."""
    target, under = args.graft_into, args.graft_under
    if not under:
        print("ERROR: --graft-into requires --graft-under <node label>", file=sys.stderr); return 2
    uirows = sb.table("userinterfaces").select("id").eq("name", target).eq("team_id", args.team_id).execute().data
    if not uirows:
        print(f"ERROR: no userinterface {target!r}", file=sys.stderr); return 2
    ui_id = uirows[0]["id"]
    trees = sb.table("navigation_trees").select("id,name,is_root_tree,parent_node_id") \
        .eq("userinterface_id", ui_id).execute().data or []
    root_tree, root_nodes = None, []
    for t in trees:
        ns = sb.table("navigation_nodes").select("node_id,node_type,label").eq("tree_id", t["id"]).execute().data
        if any(n.get("node_type") == "entry" for n in ns):
            root_tree, root_nodes = t, ns; break
    if root_tree is None:
        root_tree = next((t for t in trees if t.get("is_root_tree")), trees[0])
        root_nodes = sb.table("navigation_nodes").select("node_id,node_type,label").eq("tree_id", root_tree["id"]).execute().data
    menu = next((n for n in root_nodes if n.get("label") == under), None)
    if not menu:
        print(f"ERROR: no node labeled {under!r} in {target}'s root tree", file=sys.stderr); return 2
    menu_id = menu["node_id"]
    existing = next((t for t in trees if t.get("parent_node_id") == menu_id), None)

    if args.dry_run:
        print(f"[dry-run] GRAFT into {target}: replace subtree under node {under!r} ({menu_id})")
        print(f"[dry-run] {'overwrite existing' if existing else 'create new'} subtree; "
              f"{sum(len(c['members']) for c in canvases)} nodes from this run")
        return 0

    assets = {} if args.no_upload else _upload_assets(state, target, run_dir)

    if existing:
        # Fully remove the old subtree (edges, nodes, AND the tree row — a trigger drops a tree once
        # its nodes are gone, which would orphan a re-insert), then rebuild fresh below.
        old = existing["id"]
        sb.table("navigation_edges").delete().eq("tree_id", old).execute()
        sb.table("navigation_nodes").delete().eq("tree_id", old).execute()
        sb.table("navigation_trees").delete().eq("id", old).execute()
        print(f"removed old subtree {existing['name']} ({old[:8]}) under {under!r}")
    tid0 = str(uuid4())
    sb.table("navigation_trees").insert({
        "id": tid0, "name": f"{under} - Subtree", "userinterface_id": ui_id,
        # tree_depth MUST be >0 — the server's get_descendant_trees_data filters depth>0, so a depth-0
        # subtree is invisible to get_complete_tree_hierarchy and the server ships root-only data to the
        # host's /cache/populate (=> 18-node graph, "no path"/"not found" on goto). Direct child = 1.
        "is_root_tree": False, "tree_depth": 1, "parent_tree_id": root_tree["id"], "parent_node_id": menu_id,
        "team_id": args.team_id, "created_at": _now(), "updated_at": _now(),
    }).execute()
    print(f"{'re' if existing else ''}created subtree under {under!r} ({tid0[:8]})")

    tree_ids = {0: tid0}
    depths = {0: 1}                                  # canvas idx -> tree_depth (root child = 1)
    for c in canvases[1:]:
        tree_ids[c["idx"]] = str(uuid4())
        depths[c["idx"]] = depths.get(c["parent_idx"], 1) + 1
    total_n = total_e = 0
    for c in canvases:
        tid = tree_ids[c["idx"]]
        # canvas 0's head IS the grafted-under node (its in-tree copy). Non-head nodes are renamed
        # with the subtree-id prefix so a run's node_000X can't collide with the menu node's own id
        # (e.g. apps == node_0004) inside this tree.
        id_of = (lambda nid, _h=c["head"], _i=c["idx"], _t=tid:
                 menu_id if (_i == 0 and nid == _h) else f"{_t[:8]}_{nid}")
        if c["parent_idx"] is not None:
            head_lbl = state["nodes"][c["head"]].get("label") or c["head"]
            sb.table("navigation_trees").insert({
                "id": tid, "name": f"{head_lbl} - Subtree", "userinterface_id": ui_id,
                "is_root_tree": False, "tree_depth": depths[c["idx"]],
                "parent_tree_id": tree_ids[c["parent_idx"]],
                "parent_node_id": c["parent_node"], "team_id": args.team_id,
                "created_at": _now(), "updated_at": _now(),
            }).execute()
        nodes = _canvas_node_rows(state, c, tid, args.team_id, id_of, assets, skip_head=False)
        edges = _canvas_edge_rows(state, c, tid, args.team_id, id_of)
        if nodes:
            sb.table("navigation_nodes").insert(nodes).execute()
        if edges:
            sb.table("navigation_edges").insert(edges).execute()
        total_n += len(nodes); total_e += len(edges)

    # CRITICAL: link the menu node to its subtree via child_tree_id. The navigation graph loader
    # (build_unified_tree_data) pulls a subtree into the unified graph ONLY when its menu node carries
    # child_tree_id — has_subtree/parent_node_id alone are NOT enough, and without it the subtree is
    # invisible to goto/pathfinding (the UI renders but isn't navigable).
    menu_row = sb.table("navigation_nodes").select("data").eq("tree_id", root_tree["id"]) \
        .eq("node_id", menu_id).execute().data
    menu_data = (menu_row[0].get("data") if menu_row else {}) or {}
    menu_data["child_tree_id"] = tid0
    sb.table("navigation_nodes").update({
        "has_subtree": True, "subtree_count": 1, "data": menu_data, "updated_at": _now(),
    }).eq("tree_id", root_tree["id"]).eq("node_id", menu_id).execute()
    print(f"grafted {len(canvases)} tree(s): {total_n} nodes, {total_e} edges under {under!r} in {target} "
          f"(child_tree_id linked)")
    print(f"\n✅ open it: userinterface {target!r} -> node {under!r} -> subtree")
    return 0


def _get_or_create_ui(sb, name: str, team: str, models: list) -> dict:
    """Reuse an existing UI of this name (its root tree carries a DB-protected entry->home
    skeleton that cannot be deleted), else create one (which auto-provisions that root tree)."""
    found = sb.table("userinterfaces").select("id,name").eq("name", name).eq("team_id", team).execute().data
    if found:
        print(f"reusing existing userinterface {name} ({found[0]['id']})")
        return found[0]
    ui = sb.table("userinterfaces").insert({
        "name": name, "models": models, "min_version": "", "max_version": "",
        "team_id": team, "created_at": _now(), "updated_at": _now(),
    }).execute().data[0]
    print(f"created userinterface {name} ({ui['id']})")
    return ui


def _root_tree_and_skeleton(sb, ui_id: str, team: str):
    """Return (root_tree_id, entry_node_id, home_node_id). Reset the root tree to just its
    protected skeleton (entry node + home node + entry->home edge) and drop any stray sibling
    trees. The home node is the graft point our root maps onto."""
    trees = sb.table("navigation_trees").select("id,name,is_root_tree") \
        .eq("userinterface_id", ui_id).execute().data or []
    if not trees:
        # The after_userinterface_insert trigger (seeds '<name>_navigation' with the
        # protected entry->home skeleton) is not installed on every DB — the cloud
        # instance lacked it on the first real push (2026-07-16). Provision the same
        # skeleton shape here (mirrored from a trigger-created tree, sauce-demo_navigation).
        ui_name = sb.table("userinterfaces").select("name").eq("id", ui_id).execute().data[0]["name"]
        tid = str(uuid4())
        sb.table("navigation_trees").insert({
            "id": tid, "name": f"{ui_name}_navigation", "userinterface_id": ui_id,
            "team_id": team, "is_root_tree": True, "tree_depth": 0,
            "created_at": _now(), "updated_at": _now(),
        }).execute()
        sb.table("navigation_nodes").insert([
            {"tree_id": tid, "node_id": "entry-node", "label": "Entry", "node_type": "entry",
             "position_x": 165, "position_y": 0, "style": {}, "verifications": [],
             "data": {"type": "entry", "is_root": True,
                      "description": "Entry point for navigation",
                      "verification_pass_condition": "all"},
             "team_id": team, "is_system_protected": True, "is_read_only": False,
             "has_subtree": False, "subtree_count": 0,
             "created_at": _now(), "updated_at": _now()},
            {"tree_id": tid, "node_id": "home", "label": "home", "node_type": "screen",
             "position_x": 165, "position_y": 200, "style": {}, "verifications": [],
             "data": {"type": "screen", "is_root": True,
                      "description": "Home screen - main landing page",
                      "verification_pass_condition": "all"},
             "team_id": team, "is_system_protected": False, "is_read_only": False,
             "has_subtree": False, "subtree_count": 0,
             "created_at": _now(), "updated_at": _now()},
        ]).execute()
        sb.table("navigation_edges").insert({
            "tree_id": tid, "edge_id": "edge-entry-node-to-home",
            "source_node_id": "entry-node", "target_node_id": "home", "label": "Entry→home",
            "data": {"priority": "p3", "sourceHandle": "right-source",
                     "targetHandle": "left-target",
                     "is_conditional": False, "is_conditional_primary": False},
            "action_sets": [{"id": "actionset-entry-home", "label": "Entry→home", "actions": []}],
            "default_action_set_id": "actionset-entry-home",
            "final_wait_time": 2000, "team_id": team, "is_system_protected": True,
            "created_at": _now(), "updated_at": _now(),
        }).execute()
        print(f"  provisioned skeleton root tree {ui_name}_navigation ({tid[:8]}) — "
              f"after_userinterface_insert trigger absent on this DB")
        trees = [{"id": tid, "name": f"{ui_name}_navigation", "is_root_tree": True}]
    root = None
    for t in trees:
        ns = sb.table("navigation_nodes").select("node_id,node_type,label").eq("tree_id", t["id"]).execute().data
        if any(n.get("node_type") == "entry" for n in ns):
            root = (t, ns)
            break
    if root is None:                       # no skeleton found — use the first root tree as-is
        t = next((x for x in trees if x.get("is_root_tree")), trees[0])
        root = (t, sb.table("navigation_nodes").select("node_id,node_type,label").eq("tree_id", t["id"]).execute().data)
    rt, ns = root
    tree_id = rt["id"]
    entry_id = next((n["node_id"] for n in ns if n.get("node_type") == "entry"), "entry-node")
    home_id = next((n["node_id"] for n in ns if n.get("label") == "home" and n.get("node_type") != "entry"),
                   "home")
    # Drop stray sibling trees (e.g. a previously-created *_root) entirely.
    for t in trees:
        if t["id"] == tree_id:
            continue
        sb.table("navigation_edges").delete().eq("tree_id", t["id"]).execute()
        sb.table("navigation_nodes").delete().eq("tree_id", t["id"]).execute()
        sb.table("navigation_trees").delete().eq("id", t["id"]).execute()
        print(f"  dropped stray tree {t['name']} ({t['id'][:8]})")
    # Reset the root tree to its skeleton: delete non-entry edges, then non-skeleton nodes.
    edges = sb.table("navigation_edges").select("edge_id,source_node_id").eq("tree_id", tree_id).execute().data or []
    for e in edges:
        if e["source_node_id"] == entry_id:
            continue                       # the protected entry->home edge
        sb.table("navigation_edges").delete().eq("tree_id", tree_id).eq("edge_id", e["edge_id"]).execute()
    nodes = sb.table("navigation_nodes").select("node_id").eq("tree_id", tree_id).execute().data or []
    for n in nodes:
        if n["node_id"] in (entry_id, home_id):
            continue
        sb.table("navigation_nodes").delete().eq("tree_id", tree_id).eq("node_id", n["node_id"]).execute()
    print(f"using root tree {tree_id} (entry={entry_id}, home={home_id}); reset to skeleton")
    return tree_id, entry_id, home_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--ui-name", default="example_tv_autobuild")
    ap.add_argument("--team-id", default=DEFAULT_TEAM)
    ap.add_argument("--models", nargs="*", default=["stb"])
    ap.add_argument("--dry-run", action="store_true",
                    help="Build the rows and print a summary WITHOUT touching the DB")
    ap.add_argument("--no-upload", action="store_true",
                    help="Skip uploading node screenshots / DOM overlays to R2")
    ap.add_argument("--graft-into", default=None, metavar="UI_NAME",
                    help="Instead of creating a standalone UI, OVERWRITE the subtree under a node in "
                         "this existing UI (e.g. example_tv_autobuild). Pair with --graft-under.")
    ap.add_argument("--graft-under", default=None, metavar="NODE_LABEL",
                    help="Label of the node in the target UI's root tree whose subtree this run "
                         "replaces (e.g. settings). The run's root maps onto that node.")
    ap.add_argument("--skip-failed", action="store_true",
                    help="Drop edges whose oracle verdict (state['validation']) is a failure. "
                         "Unvalidated edges are kept — only a run validated end-to-end should "
                         "use this to push a certified-only graph.")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    state = json.loads((run_dir / "state.json").read_text())

    if args.skip_failed:
        verdicts = state.get("validation") or {}
        kept = []
        for e in state["edges"]:
            ek = f"{e['source']}|{e.get('key')}|{e['target']}"
            status = (verdicts.get(ek) or {}).get("status")
            if status in ("fail_no_effect", "fail_wrong_screen", "source_unreachable"):
                print(f"[skip-failed] dropping {e['source']} --{e.get('key')}--> {e['target']} ({status})")
            else:
                kept.append(e)
        state["edges"] = kept

    collapsed = _collapse_strip_hovers(state)
    if collapsed:
        print(f"[strip] collapsed {collapsed} transient tab-hover node(s) into RIGHT/LEFT+OK edges")
    # Relabel ALWAYS (not gated on push-collapse): the builder's explore-time collapse now
    # absorbs hovers before push, so push-collapse is often 0 — but the strip compound edges
    # still need their panes named by chain order (else labels keep the _2 suffixes).
    relabelled = _relabel_strip_panes(state, run_dir)
    if relabelled:
        print(f"[strip] relabelled {relabelled} committed pane(s) by tab order")

    canvases, _out = _partition(state)
    root_canvas = canvases[0]
    root_nid = root_canvas["head"]

    if args.dry_run and not args.graft_into:
        print(f"[dry-run] userinterface: {args.ui_name}  team={args.team_id}  models={args.models}")
        print(f"[dry-run] {len(canvases)} trees (1 root + {len(canvases) - 1} subtrees)")
        for c in canvases:
            kind = "ROOT" if c["parent_idx"] is None else f"subtree of '{c['parent_node']}'"
            head_lbl = state["nodes"][c["head"]].get("label") or c["head"]
            sibs = [state["nodes"][n].get("label") or n for n in c["lvl0"]]
            kids = [(state["nodes"][n].get("label") or n) + ("*" if n in c["menus"] else "")
                    for n in c["lvl1"]]
            print(f"  [{c['idx']}] {kind}: head={head_lbl}")
            print(f"        siblings(horiz): {', '.join(sibs)}")
            if kids:
                print(f"        children(vert):  {', '.join(kids)}   (* = has its own subtree)")
        return 0

    sb = get_supabase_client()
    if sb is None:
        print("ERROR: no Supabase client — set SUPABASE_URL and SUPABASE_ANON_KEY", file=sys.stderr)
        return 2

    # Graft mode: overwrite the subtree under a node in an existing UI (handles its own dry-run).
    if args.graft_into:
        return _graft_subtree(sb, state, run_dir, args, canvases)

    ui = _get_or_create_ui(sb, args.ui_name, args.team_id, args.models)
    root_tree_id, entry_id, home_id = _root_tree_and_skeleton(sb, ui["id"], args.team_id)

    # Upload node screenshots + DOM overlays to R2 so the tree view shows real frames.
    assets = {} if args.no_upload else _upload_assets(state, args.ui_name, run_dir)

    # Allocate a tree id per canvas (root canvas -> the protected root tree).
    tree_ids = {0: root_tree_id}
    for c in canvases[1:]:
        tree_ids[c["idx"]] = str(uuid4())

    def id_of_in(canvas):
        """Node-id resolver for a canvas: the root canvas's head maps onto the protected `home`."""
        head = canvas["head"]
        return (lambda nid: home_id if (canvas["idx"] == 0 and nid == head) else nid)

    total_n = total_e = 0
    for c in canvases:
        tid = tree_ids[c["idx"]]
        id_of = id_of_in(c)
        if c["parent_idx"] is not None:
            # Subtree: a navigation_trees row linked to the menu node in its parent tree. Its head
            # is a copy of that menu node (same node_id, this tree), so its children hang under it.
            head_lbl = state["nodes"][c["head"]].get("label") or c["head"]
            sb.table("navigation_trees").insert({
                "id": tid, "name": f"{head_lbl} - Subtree", "userinterface_id": ui["id"],
                "is_root_tree": False, "parent_tree_id": tree_ids[c["parent_idx"]],
                "parent_node_id": c["parent_node"], "team_id": args.team_id,
                "created_at": _now(), "updated_at": _now(),
            }).execute()

        nodes = _canvas_node_rows(state, c, tid, args.team_id, id_of, assets,
                                  skip_head=(c["idx"] == 0))
        edges = _canvas_edge_rows(state, c, tid, args.team_id, id_of)

        if c["idx"] == 0:
            # Update the protected home node with our root head's layout + data + the run's
            # auto verification (goto_home's arrival check needs it).
            head_row = next((r for r in _canvas_node_rows(state, c, tid, args.team_id,
                            lambda nid: nid, assets) if r["node_id"] == c["head"]), None)
            if head_row:
                sb.table("navigation_nodes").update({
                    "position_x": head_row["position_x"], "position_y": head_row["position_y"],
                    "data": head_row["data"], "has_subtree": head_row["has_subtree"],
                    "subtree_count": head_row["subtree_count"],
                    "verifications": head_row.get("verifications") or [],
                    "updated_at": _now(),
                }).eq("tree_id", root_tree_id).eq("node_id", home_id).execute()
            # Author the Entry->home recipe when it's still the empty skeleton shell —
            # goto_home executes THIS edge, and leaving it empty forces every consumer
            # (validation included) into slow rescue anchoring (arbitrator ruling
            # 2026-07-16). The recipe is the run's own certified anchor mechanism: one
            # HOME press (the key toggles TV<->menu, so once, never repeated) + settle;
            # retry = BACK (kick out of a stray overlay/app) then HOME again. Arrival is
            # verified by the home node's run-derived verification above. An edge already
            # carrying actions is arbitrator-authored — never overwritten.
            entry_edge = sb.table("navigation_edges").select("id,action_sets,default_action_set_id") \
                .eq("tree_id", root_tree_id).eq("source_node_id", entry_id).execute().data
            if entry_edge:
                ee = entry_edge[0]
                sets = ee.get("action_sets") or []
                default = next((x for x in sets if x.get("id") == ee.get("default_action_set_id")),
                               sets[0] if sets else None)
                if default is not None and not default.get("actions"):
                    # The Entry->home recipe is the ONE piece the builder should NOT try to
                    # derive by exploration — it is a device reliability recipe (how to force
                    # the menu open from ANY state), which a human seeds/edits ONCE. The goal
                    # is 99% by exploring + this small seeded anchor. So this authors a minimal
                    # DEFAULT: TVGUIDE first forces a known non-home screen (de-arms the HOME
                    # TV<->menu toggle), then HOME opens the menu. No LEFT/RIGHT flood — the
                    # nav row is a RING and HOME lands on home consistently; which item is
                    # focused is the consumer's job to read + walk. Waits 5s/4s (measured
                    # enough 2026-07-17; was 8s/9s). Retry = one more HOME (the guide
                    # occasionally eats the first). An edge already carrying actions is
                    # arbitrator/human-authored — never overwritten.
                    #
                    # SUGGESTION (printed below): for production reliability, replace this
                    # default with the ANCHOR UI's (stb_tv's) position-independent recipe
                    # (RIGHT repeat_until(home) + OK style), and ultimately keep a HARDCODED
                    # per-known-STB recipe — edited once after learning, reused thereafter.
                    def _press(key, wait):
                        return {"command": "press_key", "device_model": "remote",
                                "params": {"key": key, "wait_time": wait}}
                    default["actions"] = [_press("TVGUIDE", 5000), _press("HOME", 4000)]
                    default["retry_actions"] = [_press("HOME", 4000)]
                    sb.table("navigation_edges").update({
                        "action_sets": sets, "updated_at": _now(),
                    }).eq("id", ee["id"]).execute()
                    print("authored Entry→home: TVGUIDE(5000)+HOME(4000); retry HOME(4000)")
                    print("  [suggestion] Entry→home is a seeded device recipe, not explored — "
                          "for production, copy the anchor UI's (stb_tv) recipe or a hardcoded "
                          "per-STB one; a human edits it ONCE, exploration does the other 99%.")

        if nodes:
            sb.table("navigation_nodes").insert(nodes).execute()
        if edges:
            sb.table("navigation_edges").insert(edges).execute()
        total_n += len(nodes)
        total_e += len(edges)

    print(f"pushed {len(canvases)} trees: {total_n} nodes (+ protected home), {total_e} edges")
    print(f"\n✅ open it: userinterface '{args.ui_name}' (id {ui['id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
