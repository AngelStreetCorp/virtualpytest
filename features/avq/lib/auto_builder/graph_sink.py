"""
GraphSink — the only thing the builder uses to persist the graph it builds.

  - MemorySink : accumulates nodes/edges in RAM (offline test; the M5 diff compares this
                 in-memory graph to the fixture ground truth). No DB.
  - DbSink     : real create_userinterface / save_nodes_batch / save_edges_batch (live).
                 Always writes to a THROWAWAY UI (never the source UI).

Node/edge dict shapes match what node_generator + structure_creator already persist, so the
output is structurally comparable to a hand-authored UI.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class GraphSink(ABC):
    @abstractmethod
    def ensure_ui(self) -> str:
        """Create (or reuse) the target UserInterface + root tree. Returns root tree id."""

    @abstractmethod
    def upsert_node(self, node: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def upsert_edge(self, edge: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def flush(self) -> None:
        """Persist any buffered nodes/edges + invalidate caches."""


class MemorySink(GraphSink):
    """Offline sink — keep everything in dicts keyed by node_id / edge_id."""

    def __init__(self, ui_name: str = 'memory'):
        self.ui_name = ui_name
        self.nodes: Dict[str, Dict] = {}
        self.edges: Dict[str, Dict] = {}

    def ensure_ui(self) -> str:
        return 'mem-root'

    def upsert_node(self, node: Dict[str, Any]) -> None:
        self.nodes[node['node_id']] = node

    def upsert_edge(self, edge: Dict[str, Any]) -> None:
        self.edges[edge['edge_id']] = edge

    def flush(self) -> None:
        pass

    # convenience for the diff
    def node_labels(self) -> set:
        return {n.get('label') for n in self.nodes.values()}

    def edge_label_pairs(self) -> set:
        id2label = {nid: n.get('label') for nid, n in self.nodes.items()}
        out = set()
        for e in self.edges.values():
            s = id2label.get(e['source_node_id'], e['source_node_id'])
            t = id2label.get(e['target_node_id'], e['target_node_id'])
            out.add((s, t))
        return out

