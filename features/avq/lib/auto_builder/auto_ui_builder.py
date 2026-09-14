"""
AutoUIBuilder — autonomous BFS reconstruction of a navigation graph.

Pure logic: it only touches a DeviceAdapter (device I/O) and a GraphSink (persistence), so
the same loop runs OFFLINE (ReplayAdapter + MemorySink) and LIVE (LiveAdapter + DbSink).

Loop (BFS over screens):
  bootstrap home -> create node
  while frontier and within budget:
    src = frontier.pop(); goto(src); capture; dom
    for each candidate key from the DOM (+ optional special keys):
        return to src; press key; capture; identify
          - frame unchanged  -> boundary/no-op, skip
          - matches an existing node -> just record the edge
          - genuinely new -> create node (+fingerprint +1 verification) + edge, enqueue
  flush in batches

Dedup ("identify") is delegated to the adapter: offline = dHash family + focus agreement;
live = production localize(). Edges/nodes use the shape node_generator/structure_creator
persist, so the result is structurally comparable to a hand-authored UI.
"""
import time
from collections import deque
from typing import Dict, List, Optional, Any, Callable

try:  # package import (live host)
    from .device_adapter import DeviceAdapter, DPAD_KEYS, fp_same_node as same_node
    from .graph_sink import GraphSink
except ImportError:  # dependency-light import (offline test, dir on sys.path)
    from device_adapter import DeviceAdapter, DPAD_KEYS, fp_same_node as same_node
    from graph_sink import GraphSink

# The only keys a screen's DOM can expose (per-element navigation map).
DOM_KEYS = ['OK', 'RIGHT', 'DOWN', 'LEFT', 'UP', 'BACK']
# Probe order: OK first (dive into a screen), then dead/perpendicular keys, and the likely
# FORWARD-continue keys (DOWN, RIGHT) LAST — so a sweep's continue is the node's last probe
# (nothing after it ⇒ no walk-back when the recursion unwinds).
PROBE_ORDER = ['OK', 'UP', 'LEFT', 'DOWN', 'RIGHT']
# Opposite key to return after a probe (also discovers the reverse edge).
OPPOSITE = {'OK': 'BACK', 'RIGHT': 'LEFT', 'LEFT': 'RIGHT', 'UP': 'DOWN', 'DOWN': 'UP'}


class AutoUIBuilder:
    def __init__(self, adapter: DeviceAdapter, sink: GraphSink, *,
                 start_label: str = 'home',
                 max_nodes: int = 200, max_presses: int = 100000,
                 max_depth: Optional[int] = None,
                 flush_every: int = 25,
                 log: Callable[[str], None] = print):
        self.adapter = adapter
        self.sink = sink
        self.start_label = start_label
        self.max_nodes = max_nodes
        self.max_presses = max_presses
        # Semantic screen depth: D-pad focus moves remain at the current depth; OK enters the
        # next depth. None means unlimited. At the limit D-pad exploration continues, but OK
        # is not probed because it would enter a deeper screen.
        self.max_depth = max_depth
        self.flush_every = flush_every
        self.log = log

        # node_key -> {node_key, label, fingerprint, dom}
        self.nodes: Dict[str, Dict] = {}
        self.edges: set = set()        # (src, dst, key-tuple) already created
        self.adj: Dict[str, List] = {} # discovered graph src -> [(keys, dst)] (for navigation)
        self.tried: set = set()        # (node, key) pairs already probed — never repeat
        self.node_depth: Dict[str, int] = {}
        self.steps: List[Dict] = []    # per-explored-node records (discovery order)
        self.walk: List[Dict] = []     # chronological per-keypress log {seq,key,from,to,moved}
        self.current: Optional[str] = None   # device's logical position (node_key)
        self._pos = 0                  # canvas layout cursor
        self._t0 = 0.0

    # -- node/edge construction (shape matches save_node / save_edge) ------------
    def _create_node(self, key: str, screenshot: str, fp: Dict, dom: Dict,
                     is_root: bool = False, depth: int = 0) -> Dict:
        # Identity = fingerprint (the recognizer, used by localize); structure = DOM.
        # No synthesized reference-image/text verification — the tree is built purely from
        # fingerprint + DOM.
        self._pos += 1
        node = {
            'node_id': key, 'label': key, 'node_type': 'screen',
            'verifications': [],
            'data': {'type': 'screen', 'is_root': is_root, 'ai_generated': True,
                     'discovery_order': self._pos, 'depth': depth,
                     'screenshot': screenshot, 'fingerprint': fp, 'dom': dom},
            'position_x': 250 + (self._pos % 6) * 200,
            'position_y': 100 + (self._pos // 6) * 160,
        }
        self.nodes[key] = {'node_key': key, 'label': key, 'fingerprint': fp,
                           'dom': dom, 'depth': depth}
        self.node_depth[key] = depth
        self.sink.upsert_node(node)
        return node

    def _create_edge(self, src: str, dst: str, keys: List[str]) -> None:
        sig = (src, dst, tuple(keys))
        if sig in self.edges:
            return
        self.edges.add(sig)
        self.adj.setdefault(src, []).append((list(keys), dst))   # for discovered-graph navigation
        asid, rasid = f'{src}_to_{dst}', f'{dst}_to_{src}'
        fwd = [{'command': 'press_key', 'action_type': 'remote',
                'params': {'key': k, 'wait_time': 1000}} for k in keys]
        edge = {
            'edge_id': asid,
            'source_node_id': src, 'target_node_id': dst,
            'default_action_set_id': asid,
            'action_sets': [
                {'id': asid, 'label': f'{src} → {dst}', 'actions': fwd,
                 'retry_actions': [], 'failure_actions': [], 'final_wait_time': 0},
                # reverse is discovered separately (opposite-key probe) as its own edge;
                # left empty here rather than a fake BACK.
                {'id': rasid, 'label': f'{dst} → {src}', 'actions': [],
                 'retry_actions': [], 'failure_actions': [], 'final_wait_time': 0},
            ],
            'data': {'ai_generated': True},
        }
        self.sink.upsert_edge(edge)

    # -- discovery --------------------------------------------------------------
    def _candidate_keys(self, dom: Dict) -> List[str]:
        # Keys come ONLY from the current screen's DOM — the focused element's navigation
        # map ({OK,UP,DOWN,LEFT,RIGHT,BACK}). No injected/physical keys (HOME/POWER are not
        # in any DOM). One key at a time; focus moves become sibling nodes, OK opens a screen.
        nav = (dom or {}).get('navigation') or {}
        focused = (dom or {}).get('focused_element_id')
        fmap = nav.get(focused, {}) if focused else {}
        # BACK is the RETURN mechanism, not a discovery direction — don't probe it.
        return [k for k in DOM_KEYS if k != 'BACK' and fmap.get(k)]

    def _unique_label(self, label: str, fp: Dict) -> str:
        if label not in self.nodes:
            return label
        # same label already exists with a DIFFERENT fingerprint -> suffix
        if same_node(self.nodes[label]['fingerprint'], fp):
            return label
        i = 2
        while f'{label}_{i}' in self.nodes:
            i += 1
        return f'{label}_{i}'

    def _press(self, key: str) -> None:
        """Press one key and log the chronological walk (from → to, as on the real STB)."""
        before = self.adapter.label_here()
        self.adapter.press_key(key)
        after = self.adapter.label_here()
        self.walk.append({'seq': len(self.walk) + 1, 'key': key,
                          'from': before, 'to': after, 'moved': before != after})

    # -- navigation over the DISCOVERED graph (no ground-truth, no teleport) -----
    def _discovered_path(self, src: str, dst: str) -> Optional[List[str]]:
        """BFS over the keys the builder has ALREADY discovered → flat key list (or None)."""
        if src == dst:
            return []
        q = deque([(src, [])])
        seen = {src}
        while q:
            cur, ks = q.popleft()
            for keys, tgt in self.adj.get(cur, []):
                if tgt in seen:
                    continue
                seen.add(tgt)
                nk = ks + keys
                if tgt == dst:
                    return nk
                q.append((tgt, nk))
        return None

    def _navigate(self, target: str) -> bool:
        """Reposition to `target` using ONLY discovered edges (real key presses).
        Falls back to pressing BACK (back-stack) a few times to unwind toward target."""
        if self.current == target:
            return True
        path = self._discovered_path(self.current, target)
        if path is not None:
            for k in path:
                self._press(k)
            self.current = target
            return True
        # fallback: unwind with BACK, re-syncing position from the device each time
        for _ in range(6):
            self._press('BACK')
            here = self.adapter.label_here()
            if here and here != '?':
                self.current = here
            if self.current == target:
                return True
            p = self._discovered_path(self.current, target)
            if p is not None:
                for k in p:
                    self._press(k)
                self.current = target
                return True
        return False

    # -- depth-first discovery (one key at a time, each (node,key) probed ONCE) --
    def _explore(self, node: str, via_key: Optional[str], depth: int = 0) -> None:
        """We are physically AT `node`. Press each DOM key once (skipping the key back to the
        parent). `OK` dives into a screen; a focus move (RIGHT/DOWN/…) just CONTINUES the sweep
        into the next focus node — no eager return. Repositioning happens lazily at the start
        of the next probe (pathfinding / BACK), so there's no RIGHT/LEFT oscillation. Own
        press count excludes the recursive child. Step recorded on ENTRY (discovery order)."""
        step = {'step': len(self.steps) + 1, 'node': node, 'via': via_key, 'depth': depth,
                't_start_s': round(time.time() - self._t0, 3),
                'presses': 0, 'new_nodes': 0, 'transitions': []}
        self.steps.append(step)

        src_fp = self.adapter.fingerprint(self.adapter.capture())
        keys = self._candidate_keys(self.adapter.dom(self.adapter.capture()))
        rev_via = OPPOSITE.get(via_key) if via_key else None   # the key back to the parent
        ordered = [k for k in PROBE_ORDER if k in keys]        # forward keys (DOWN/RIGHT) last

        for key in ordered:
            if key == rev_via or (node, key) in self.tried:   # don't go back the way we came
                continue
            # Depth is screen nesting, not key count: D-pad stays on this depth, while OK
            # enters a child screen. At the limit, continue the focus sweep but do not dive.
            if key == 'OK' and self.max_depth is not None and depth >= self.max_depth:
                continue
            self.tried.add((node, key))
            if self.adapter.press_count >= self.max_presses or len(self.nodes) >= self.max_nodes:
                break

            n0 = self.adapter.press_count
            self._navigate(node)                    # lazy reposition (free if already here)
            self._press(key)
            step['presses'] += self.adapter.press_count - n0   # own: reposition + this press
            after = self.adapter.fingerprint(self.adapter.capture())

            if same_node(src_fp, after):            # dead key — nothing here
                continue

            existing = self.adapter.identify(after, list(self.nodes.values()))
            is_new = existing is None
            next_depth = depth + 1 if key == 'OK' else depth
            if existing:
                dst = existing
                self.node_depth[dst] = min(self.node_depth.get(dst, next_depth), next_depth)
            else:
                cap2 = self.adapter.capture()
                dst = self.adapter.suggest_label(self.adapter.dom(cap2), after)
                if dst in self.nodes:
                    is_new = False
                    self.node_depth[dst] = min(
                        self.node_depth.get(dst, next_depth), next_depth)
                else:
                    self._create_node(
                        dst, cap2, after, self.adapter.dom(cap2), depth=next_depth)
                    step['new_nodes'] += 1
                    self.log(f"  + {node} --{key}--> {dst} (new, depth={next_depth})")
            self._create_edge(node, dst, [key])
            step['transitions'].append({'keys': key, 'dst': dst, 'new': is_new})
            # focus moves are reversible — record the inverse edge without pressing it
            if key != 'OK' and OPPOSITE.get(key):
                self._create_edge(dst, node, [OPPOSITE[key]])
            self.current = dst

            if is_new:
                self._explore(dst, via_key=key, depth=next_depth)

        if len(self.nodes) % self.flush_every == 0:
            self.sink.flush()

    def build(self) -> Dict[str, Any]:
        self.sink.ensure_ui()
        self._t0 = time.time()

        # bootstrap: we assume the device starts on `home`
        cap = self.adapter.capture()
        dom = self.adapter.dom(cap)
        fp = self.adapter.fingerprint(cap)
        home_key = self.adapter.suggest_label(dom, fp)
        self._create_node(home_key, cap, fp, dom, is_root=True, depth=0)
        self.current = home_key
        self.log(f"[home] {home_key}")

        # depth-first: dive into each screen and return before moving sideways
        import sys
        sys.setrecursionlimit(10000)
        self._explore(home_key, via_key=None)

        self.sink.flush()
        return {
            'success': True,
            'nodes': len(self.nodes),
            'edges': len(self.edges),
            'iterations': len(self.steps),         # nodes explored
            'presses': self.adapter.press_count,   # total device key actions
            'duration_ms': round((time.time() - self._t0) * 1000, 1),
            'max_depth': self.max_depth,
            'steps': self.steps,
            'walk': self.walk,                     # chronological per-keypress log
            'node_keys': list(self.nodes.keys()),  # discovery order
        }
