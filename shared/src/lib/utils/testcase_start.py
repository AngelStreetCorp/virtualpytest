"""
Every Test Prompt run starts at the interface's home screen (TASK-36).

Reaching home is the gate: it wakes the device and launches the app (the interface's
go-home path handles power, app launch, screensaver). If it fails, the prompt itself does not
run. Explore does it as its pre-navigation; a graph run gets it as its first block, added here
both to a generated graph (host, /testcase/execute-from-prompt) and to a replayed one (server).
"""

import copy
from typing import Any, Dict, Optional


def first_block(graph: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The block START's success edge leads to, or None."""
    nodes = {n.get('id'): n for n in (graph or {}).get('nodes', [])}
    start = next((n for n in nodes.values() if n.get('type') == 'start'), None)
    if not start:
        return None
    target = next((e.get('target') for e in (graph or {}).get('edges', [])
                   if e.get('source') == start['id'] and (e.get('sourceHandle') or 'success') == 'success'), None)
    return nodes.get(target)


def starts_at(graph: Dict[str, Any], label: str) -> bool:
    block = first_block(graph)
    data = (block or {}).get('data') or {}
    return bool(block) and block.get('type') == 'navigation' and label in (
        data.get('target_node_label'), data.get('target_node_id'))


def with_start_node(graph: Dict[str, Any], label: str) -> Dict[str, Any]:
    """The graph with a navigation to ``label`` as its first block (a copy; unchanged when it
    already starts there). The new block has no failure edge: if home is not reached, the run
    fails there, before any of the test's own steps."""
    if not label or not isinstance(graph, dict) or starts_at(graph, label):
        return graph
    out = copy.deepcopy(graph)
    nodes, edges = out.setdefault('nodes', []), out.setdefault('edges', [])
    start = next((n for n in nodes if n.get('type') == 'start'), None)
    if not start:
        return graph
    old = next((e for e in edges
                if e.get('source') == start['id'] and (e.get('sourceHandle') or 'success') == 'success'), None)
    pos = start.get('position') or {'x': 250, 'y': 100}
    node_id = 'start_home'
    nodes.append({
        'id': node_id,
        'type': 'navigation',
        'position': {'x': pos.get('x', 250), 'y': pos.get('y', 100) + 60},
        'data': {'label': f'go_home:{label}', 'target_node_label': label, 'target_node_id': label,
                 'action_type': 'navigation', 'transitions': []},
    })
    if old:
        edges.append({'id': f'e_{node_id}_{old["target"]}', 'source': node_id, 'target': old['target'],
                      'sourceHandle': 'success', 'type': 'success'})
        old['target'] = node_id
        old['id'] = f'e_{start["id"]}_{node_id}'
    else:
        edges.append({'id': f'e_{start["id"]}_{node_id}', 'source': start['id'], 'target': node_id,
                      'sourceHandle': 'success', 'type': 'success'})
    return out
