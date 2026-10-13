"""
Build userinterface bundles (.vptree) for the game showcases (TASK-33).

A bundle is a zip holding manifest.json: one root navigation tree with its nodes and edges,
imported with POST /server/userinterface/import (file=<bundle>, name=<name>).
"""

import json
import uuid
import zipfile
from datetime import datetime, timezone

TREE_SCHEMA = "1.0"


def node(tree_id, node_id, label, node_type, x, y, verifications=None, parent=None):
    data = {"type": node_type}
    if node_type == "entry":
        data.update({"is_root": True, "description": "Entry point for navigation", "verification_pass_condition": "all"})
    if parent:
        data["parent"] = [parent]
    return {
        "id": str(uuid.uuid4()), "tree_id": tree_id, "node_id": node_id, "node_type": node_type,
        "label": label, "position_x": x, "position_y": y, "data": data, "style": {},
        "has_subtree": False, "subtree_count": 0, "verifications": verifications or [], "hidden_in_base": False,
    }


def edge(tree_id, source, target, actions, wait=0, back=False):
    """An edge with its default action set; back=True adds an empty reverse set (action nodes)."""
    set_id = f"{source}_to_{target}"
    action_sets = [{"id": set_id, "label": f"{source} → {target}", "actions": actions,
                    "retry_actions": [], "failure_actions": [], "final_wait_time": wait}]
    if back:
        action_sets.append({"id": f"{target}_to_{source}", "label": f"{target} → {source}", "actions": [],
                            "retry_actions": [], "failure_actions": [], "final_wait_time": 0})
    return {
        "id": str(uuid.uuid4()), "tree_id": tree_id, "edge_id": f"edge-{source}-{target}",
        "source_node_id": source, "target_node_id": target, "label": f"{source}→{target}",
        "data": {"priority": "p3", "sourceHandle": "bottom-right-menu-source", "targetHandle": "top-right-menu-target"},
        "action_sets": action_sets, "hidden_in_base": False, "default_action_set_id": set_id,
    }


def manifest(name, models, tree_id, nodes, edges):
    tree_name = f"{name}_navigation"
    return {
        "schema": TREE_SCHEMA,
        "kind": "vptree",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": {"name": name, "models": models, "min_version": "", "max_version": ""},
        "trees": [{
            "tree_id": tree_id,
            "tree": {"id": tree_id, "name": tree_name, "is_root_tree": True, "tree_depth": 0,
                     "parent_tree_id": None, "parent_node_id": None, "viewport_x": 0, "viewport_y": 0,
                     "viewport_zoom": 1},
            "tree_info": {"name": tree_name, "is_root_tree": True, "tree_depth": 0,
                          "parent_tree_id": None, "parent_node_id": None},
            "nodes": nodes,
            "edges": edges,
        }],
        "variants": [],
        "references": [],
    }


def write_bundle(path, data):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(data, indent=2))
