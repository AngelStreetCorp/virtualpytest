"""
Context extraction from tool outputs.
"""

import json
import re
from typing import Dict, Any


def extract_context_from_result(tool_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract contextual values from tool outputs. Output values override inputs.
    """
    updates: Dict[str, Any] = {}
    if not isinstance(result, dict):
        return updates

    content_items = result.get("content") or []
    texts = [
        c.get("text", "")
        for c in content_items
        if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str)
    ]
    merged_text = "\n".join(texts)

    parsed_json = None
    if merged_text:
        try:
            parsed_json = json.loads(merged_text)
        except Exception:
            parsed_json = None

    # list_hosts → hosts list
    if tool_name == "list_hosts":
        hosts = []
        if parsed_json and isinstance(parsed_json, dict) and isinstance(parsed_json.get("hosts"), list):
            hosts = [h.get("host_name") for h in parsed_json.get("hosts", []) if h.get("host_name")]
        else:
            hosts = re.findall(r"✅\s*([^\s]+)", merged_text)

        if hosts:
            deduped = []
            seen = set()
            for h in hosts:
                if h not in seen:
                    seen.add(h)
                    deduped.append(h)
            updates["hosts"] = deduped

    # get_device_info → devices list + individual device context
    if tool_name == "get_device_info":
        devices = []
        if parsed_json and isinstance(parsed_json, dict) and isinstance(parsed_json.get("devices"), list):
            devices = parsed_json.get("devices", [])
        if devices:
            updates["devices"] = devices
            # If only 1 device, extract its details for easy reuse
            if len(devices) == 1:
                device = devices[0]
                if device.get("host_name"):
                    updates["host_name"] = device["host_name"]
                if device.get("device_id"):
                    updates["device_id"] = device["device_id"]
                if device.get("device_model"):
                    updates["device_model"] = device["device_model"]

    # get_compatible_hosts → host/device/tree/userinterface hints
    if tool_name == "get_compatible_hosts":
        host_match = re.search(r"Host:\s*([^\n]+)", merged_text)
        device_id_match = re.search(r"Device ID:\s*([^\s]+)", merged_text)
        tree_id_match = re.search(r"Tree ID:\s*([^\s]+)", merged_text)
        ui_match = re.search(r"compatible host\(s\) for '([^']+)'", merged_text)

        if host_match:
            updates["host_name"] = host_match.group(1).strip()
        if device_id_match:
            updates["device_id"] = device_id_match.group(1).strip()
        if tree_id_match:
            updates["tree_id"] = tree_id_match.group(1).strip()
        if ui_match:
            updates["userinterface_name"] = ui_match.group(1).strip()

    # get_userinterface_complete → tree/userinterface context
    if tool_name == "get_userinterface_complete":
        if parsed_json and isinstance(parsed_json, dict):
            ui_name = parsed_json.get("userinterface_name")
            ui_id = parsed_json.get("userinterface_id")
            tree_id = parsed_json.get("tree_id")
            if ui_name:
                updates["userinterface_name"] = ui_name
            if ui_id:
                updates["userinterface_id"] = ui_id
            if tree_id:
                updates["tree_id"] = tree_id
        else:
            tree_match = re.search(r"tree_id:([^\s]+)", merged_text)
            if tree_match:
                updates["tree_id"] = tree_match.group(1).strip()

    return updates

