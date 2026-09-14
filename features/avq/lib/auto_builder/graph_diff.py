"""
graph_diff — compare a rebuilt graph against the ground-truth UI (node/edge coverage).

Offline: ground truth = the fixture (ReplayAdapter.ground_truth_nodes/edges).
Live: ground truth = the real example_tv (export a fixture for it, or query the DB).
"""
from typing import Dict, Set, Tuple, Any


def diff_graphs(built_nodes: Set[str], built_edges: Set[Tuple[str, str]],
                truth_nodes: Set[str], truth_edges: Set[Tuple[str, str]]) -> Dict[str, Any]:
    node_hit = built_nodes & truth_nodes
    edge_hit = built_edges & truth_edges
    return {
        'nodes': {
            'truth': len(truth_nodes), 'built': len(built_nodes),
            'covered': len(node_hit),
            'coverage': round(len(node_hit) / max(1, len(truth_nodes)), 3),
            'missing': sorted(truth_nodes - built_nodes),
            'extra': sorted(built_nodes - truth_nodes),
        },
        'edges': {
            'truth': len(truth_edges), 'built': len(built_edges),
            'covered': len(edge_hit),
            'coverage': round(len(edge_hit) / max(1, len(truth_edges)), 3),
            'missing': sorted(truth_edges - built_edges),
            'extra': sorted(built_edges - truth_edges),
        },
    }


def print_diff(d: Dict[str, Any], log=print) -> None:
    n, e = d['nodes'], d['edges']
    log(f"NODES  truth={n['truth']} built={n['built']} covered={n['covered']} "
        f"({n['coverage']*100:.0f}%)")
    if n['missing']:
        log(f"  missing: {n['missing']}")
    if n['extra']:
        log(f"  extra:   {n['extra']}")
    log(f"EDGES  truth={e['truth']} built={e['built']} covered={e['covered']} "
        f"({e['coverage']*100:.0f}%)")
    if e['missing']:
        log(f"  missing: {e['missing']}")
    if e['extra']:
        log(f"  extra:   {e['extra']}")
