"""
DeviceAdapter — the only thing the builder uses to touch "the device".

Two implementations:
  - LiveAdapter   : real STB via the device singleton (remote/av) + generate_dom via GPT-5.5
  - ReplayAdapter : a simulated STB driven by an exported fixture (graph.json + screenshots);
                    no hardware, no OpenAI, deterministic. Pressing a key walks the
                    ground-truth edges, capture/dom/fingerprint return the stored data.

Keep this module's top-level imports stdlib-only; everything heavy (cv2, the device
registry, generate_dom) is imported lazily inside the live methods so the offline path
never pulls device/OpenAI deps.
"""
import os
import json
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

DPAD_KEYS = ['UP', 'DOWN', 'LEFT', 'RIGHT', 'OK']


def dhash_hamming(a: str, b: str) -> int:
    """Hamming distance between two hex dHash strings (256-bit). Big = unrelated."""
    if not a or not b or len(a) != len(b):
        return 9999
    try:
        return bin(int(a, 16) ^ int(b, 16)).count('1')
    except ValueError:
        return 9999


def focus_agree(a: Optional[Dict], b: Optional[Dict]) -> bool:
    """Do two focus signatures point at the same sibling? (LOCALIZE layer 2)."""
    a = a or {}
    b = b or {}
    ka, kb = a.get('kind'), b.get('kind')
    if ka != kb:
        return False
    if ka == 'nav':
        return abs((a.get('x') or 0) - (b.get('x') or 0)) <= 0.06 and \
               abs((a.get('width') or 0) - (b.get('width') or 0)) <= 0.10
    if ka == 'box':
        return abs((a.get('x') or 0) - (b.get('x') or 0)) <= 0.08 and \
               abs((a.get('y') or 0) - (b.get('y') or 0)) <= 0.08
    return True  # both 'none'


def fp_same_node(a: Optional[Dict], b: Optional[Dict], family: int = 8) -> bool:
    """Same screen: dHash family match AND focus agreement (LOCALIZE two-layer).

    dHash alone over-merges siblings (e.g. home vs home_tvshop differ by ~6 because the
    hero dominates but the menu underline is at a different x) — the focus layer separates
    them.
    """
    if not a or not b:
        return False
    return dhash_hamming(a.get('dhash'), b.get('dhash')) <= family and \
        focus_agree(a.get('focus'), b.get('focus'))


class DeviceAdapter(ABC):
    """Everything the builder needs from the device, mode-agnostic."""

    @abstractmethod
    def press_key(self, key: str) -> None:
        """Press a single remote key (UP/DOWN/LEFT/RIGHT/OK/BACK/HOME/...)."""

    @abstractmethod
    def goto(self, node_key: str) -> bool:
        """Return the device to an already-known node (replay home position / live navigate)."""

    @abstractmethod
    def capture(self) -> str:
        """Return a path to the current screenshot."""

    @abstractmethod
    def dom(self, screenshot_path: str) -> Dict[str, Any]:
        """Return the DOM (focusable_elements + navigation + focused_element_id) of a frame."""

    @abstractmethod
    def fingerprint(self, screenshot_path: str) -> Optional[Dict[str, Any]]:
        """Return the v4 fingerprint {dhash, focus, title, text} of a frame."""

    @abstractmethod
    def identify(self, fp: Dict[str, Any], created: List[Dict[str, Any]]) -> Optional[str]:
        """Which already-created node IS this frame? Returns the created node_key or None.

        `created` is a list of {node_key, fingerprint} the builder has made this run.
        """

    @abstractmethod
    def suggest_label(self, dom: Dict[str, Any], fp: Dict[str, Any]) -> str:
        """A stable label for a newly discovered screen.

        Called only AFTER identify() returns None (genuinely new), so dedup is still done by
        fingerprint. Replay returns the ground-truth label (readable diff); Live derives one
        from the DOM title via node_generator's canonical sanitizer.
        """


# --------------------------------------------------------------------------------------
# Replay (offline) — a simulated STB built from an exported fixture
# --------------------------------------------------------------------------------------
class ReplayAdapter(DeviceAdapter):
    """Simulated STB from a `graph.json` fixture (see export_ui_fixture.py).

    State = current ground-truth node_id. A keypress is resolved against the fixture's
    edges leaving the current node (forward action_set key sequence, supporting multi-key
    edges via a small pending buffer). A key with no matching edge = boundary no-op (stay).
    capture/dom/fingerprint return the current node's stored screenshot/DOM/fingerprint.
    """

    FAMILY_MATCH = 8  # dHash Hamming <= this => same screen (offline identify)

    def __init__(self, fixture_dir: str, start_label: str = 'home'):
        self.fixture_dir = fixture_dir
        with open(os.path.join(fixture_dir, 'graph.json')) as f:
            self.fx = json.load(f)
        self.shots_dir = os.path.join(fixture_dir, 'screenshots')

        # node_id -> node (prefer non-parent-reference copies on label collisions)
        self._by_id: Dict[str, Dict] = {}
        for n in self.fx['nodes']:
            self._by_id[n['node_id']] = n
        # label -> a representative node_id (root-tree node wins, then non-ref)
        root_tree = next((t['id'] for t in self.fx['trees'] if t['is_root_tree']), None)
        self._label2id: Dict[str, str] = {}
        for n in self.fx['nodes']:
            lbl = n['label']
            cur = self._label2id.get(lbl)
            if cur is None:
                self._label2id[lbl] = n['node_id']
            elif n['tree_id'] == root_tree and self._by_id[cur]['tree_id'] != root_tree:
                self._label2id[lbl] = n['node_id']

        # forward transitions: source_node_id -> [(key_seq, target_node_id)]
        self._fwd: Dict[str, List] = {}
        for e in self.fx['edges']:
            asets = e.get('action_sets') or []
            if not asets:
                continue
            fwd = asets[0]
            keyseq = [a.get('params', {}).get('key') for a in fwd.get('actions', [])]
            keyseq = [k for k in keyseq if k]
            if keyseq:
                self._fwd.setdefault(e['source_node_id'], []).append((keyseq, e['target_node_id']))
            # reverse direction (BACK etc.)
            if len(asets) > 1:
                rev = asets[1]
                rkeys = [a.get('params', {}).get('key') for a in rev.get('actions', [])]
                rkeys = [k for k in rkeys if k]
                if rkeys:
                    self._fwd.setdefault(e['target_node_id'], []).append((rkeys, e['source_node_id']))

        self.start_id = self._label2id.get(start_label)
        if not self.start_id:
            raise ValueError(f"start node '{start_label}' not in fixture")
        self.current_id = self.start_id
        self._pending: List[str] = []
        self._back_stack: List[str] = []   # OK pushes, BACK pops (real STB back behavior)
        self.press_log: List[str] = []
        self.press_count = 0

    # -- helpers ----------------------------------------------------------------
    def label(self, node_id: str) -> str:
        n = self._by_id.get(node_id)
        return n['label'] if n else node_id

    @property
    def current_label(self) -> str:
        return self.label(self.current_id)

    def _node(self) -> Dict:
        return self._by_id[self.current_id]

    # -- DeviceAdapter ----------------------------------------------------------
    def _shortest_keypath(self, src_id: str, dst_id: str) -> Optional[List[str]]:
        """BFS over ground-truth forward transitions → flat list of keys (or None).

        Stand-in for the live `execute_navigation`/`find_shortest_path`: it produces a REAL
        key sequence to walk from one node to another (no teleport)."""
        if src_id == dst_id:
            return []
        from collections import deque
        q = deque([(src_id, [])])
        seen = {src_id}
        while q:
            cur, keys = q.popleft()
            for keyseq, tgt in self._fwd.get(cur, []):
                if tgt in seen:
                    continue
                seen.add(tgt)
                nk = keys + keyseq
                if tgt == dst_id:
                    return nk
                q.append((tgt, nk))
        return None

    def press_key(self, key: str) -> None:
        """ONE key at a time: a press transitions only if a SINGLE-key edge [key] leaves the
        current node; otherwise it's a no-op (stay). Compound authored edges (e.g.
        DOWN+HOME+DOWN) are therefore unreachable one-key — by design (they're hand-authored
        shortcuts; a real device would walk them one DOM key at a time)."""
        self.press_count += 1
        self.press_log.append(key)
        for keyseq, target in self._fwd.get(self.current_id, []):
            if keyseq == [key]:                       # single-key edge only
                if key == 'OK':                       # entering a screen → remember opener
                    self._back_stack.append(self.current_id)
                self.current_id = target
                return
        # BACK with no authored single-key edge → universal "close screen" (DOM says BACK:back)
        if key == 'BACK' and self._back_stack:
            self.current_id = self._back_stack.pop()
            return
        # no single-key edge from here → no-op (stay)

    def goto(self, node_key: str) -> bool:
        """Navigate to a node by pressing REAL keys along the shortest path (no teleport)."""
        target = self._label2id.get(node_key) or (node_key if node_key in self._by_id else None)
        if not target:
            return False
        if self.current_id == target:
            self._pending = []
            return True
        path = self._shortest_keypath(self.current_id, target)
        if path is None:
            return False
        for k in path:
            self.press_key(k)
        self._pending = []
        return self.current_id == target

    def capture(self) -> str:
        key = (self._node().get('data') or {}).get('screenshot')
        base = os.path.basename(key) if key else None
        if base:
            p = os.path.join(self.shots_dir, base)
            if os.path.exists(p):
                return p
        return ''  # screen with no stored screenshot (e.g. ENTRY)

    def dom(self, screenshot_path: str) -> Dict[str, Any]:
        return (self._node().get('data') or {}).get('dom') or {}

    def fingerprint(self, screenshot_path: str) -> Optional[Dict[str, Any]]:
        return (self._node().get('data') or {}).get('fingerprint')

    def identify(self, fp: Dict[str, Any], created: List[Dict[str, Any]]) -> Optional[str]:
        """Match by dHash family AND focus agreement (mirrors match_fingerprint two-layer)."""
        if not fp or not fp.get('dhash'):
            return None
        best_key, best_dist = None, 9999
        for c in created:
            cfp = c.get('fingerprint') or {}
            if not fp_same_node(fp, cfp, self.FAMILY_MATCH):
                continue
            d = dhash_hamming(fp['dhash'], cfp.get('dhash'))
            if d < best_dist:
                best_dist, best_key = d, c['node_key']
        return best_key

    def suggest_label(self, dom: Dict[str, Any], fp: Dict[str, Any]) -> str:
        return self.current_label

    def label_here(self) -> str:
        return self.current_label

    # -- ground-truth helpers (used by the diff / test) -------------------------
    def ground_truth_nodes(self) -> List[str]:
        return sorted({n['label'] for n in self.fx['nodes']
                       if n['node_type'] not in ('entry',)})

    def ground_truth_edges(self) -> set:
        out = set()
        for e in self.fx['edges']:
            s, t = self.label(e['source_node_id']), self.label(e['target_node_id'])
            out.add((s, t))
        return out

