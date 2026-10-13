#!/usr/bin/env python3
"""Utilities for extracting script target rules from script files."""

from __future__ import annotations

import ast
import os
from typing import Any, Dict, List, Optional


def _safe_parse(source: str, filename: str = "<source>") -> Optional[ast.Module]:
    try:
        return ast.parse(source, filename=filename)
    except (SyntaxError, ValueError):
        return None


def extract_script_target_rules_from_source(source: str) -> Optional[Dict[str, Any]]:
    """Extract `_target_rules` or `main._target_rules` from Python source text."""
    tree = _safe_parse(source)
    if tree is None:
        return None

    def _literal_dict(node: ast.AST) -> Optional[Dict[str, Any]]:
        if not isinstance(node, ast.Dict):
            return None

        result: Dict[str, Any] = {}
        for key_node, value_node in zip(node.keys, node.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                return None
            try:
                result[key_node.value] = ast.literal_eval(value_node)
            except Exception:
                return None
        return result

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "_target_rules":
                return _literal_dict(node.value)
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "main"
                and target.attr == "_target_rules"
            ):
                return _literal_dict(node.value)

    return None


def extract_script_target_rules_from_path(script_path: str) -> Optional[Dict[str, Any]]:
    """Extract `_target_rules` or `main._target_rules` from a script file."""
    try:
        with open(script_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, filename=script_path)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    def _literal_dict(node: ast.AST) -> Optional[Dict[str, Any]]:
        if not isinstance(node, ast.Dict):
            return None

        result: Dict[str, Any] = {}
        for key_node, value_node in zip(node.keys, node.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                return None
            try:
                result[key_node.value] = ast.literal_eval(value_node)
            except Exception:
                return None
        return result

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "_target_rules":
                return _literal_dict(node.value)
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "main"
                and target.attr == "_target_rules"
            ):
                return _literal_dict(node.value)

    return None


def extract_script_description_from_source(source: str) -> Optional[str]:
    """Extract `_script_description` from Python source text."""
    tree = _safe_parse(source)
    if tree is None:
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            name_match = (isinstance(target, ast.Name) and target.id == "_script_description") or (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "main"
                and target.attr == "_script_description"
            )
            if name_match:
                try:
                    val = ast.literal_eval(node.value)
                    return str(val) if isinstance(val, str) else None
                except Exception:
                    return None
    return None


def extract_script_libs(source: str) -> List[str]:
    """Extract `_script_libs` (a list of virtual-script names) from Python source.

    A virtual script may declare its shared-library dependencies with a top-level
    ``_script_libs = ["name_a", "name_b"]`` marker — the names of OTHER virtual
    scripts (same team) whose source should be made importable at run time.

    Returns a de-duplicated, order-preserving list of string names. Tolerates
    absence, a non-list value, or unparseable source by returning ``[]``. Only
    plain string entries are kept; anything else is ignored.
    """
    tree = _safe_parse(source)
    if tree is None:
        return []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            name_match = (isinstance(target, ast.Name) and target.id == "_script_libs") or (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "main"
                and target.attr == "_script_libs"
            )
            if not name_match:
                continue
            try:
                val = ast.literal_eval(node.value)
            except Exception:
                return []
            if not isinstance(val, (list, tuple)):
                return []
            seen: set[str] = set()
            names: List[str] = []
            for item in val:
                if isinstance(item, str):
                    trimmed = item.strip()
                    if trimmed and trimmed not in seen:
                        seen.add(trimmed)
                        names.append(trimmed)
            return names
    return []


def extract_arg_descriptions_from_source(source: str) -> Optional[Dict[str, str]]:
    """Extract `_arg_descriptions` dict from Python source text."""
    tree = _safe_parse(source)
    if tree is None:
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            name_match = (isinstance(target, ast.Name) and target.id == "_arg_descriptions") or (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "main"
                and target.attr == "_arg_descriptions"
            )
            if name_match:
                return _descriptions_from_dict_node(node.value, _module_string_constants(tree))
    return None


def _module_string_constants(tree: ast.Module) -> Dict[str, str]:
    """Module-level ``NAME = 'literal'`` assignments, to fill f-strings in descriptions."""
    consts = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, (str, int, float))):
            consts[node.targets[0].id] = str(node.value.value)
    return consts


def _descriptions_from_dict_node(value: ast.AST, consts: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Read a ``{name: description}`` dict entry by entry: one f-string or expression doesn't drop the rest."""
    if not isinstance(value, ast.Dict):
        return None
    out = {}
    for k, v in zip(value.keys, value.values):
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            continue
        if isinstance(v, ast.JoinedStr):
            parts = []
            for part in v.values:
                if isinstance(part, ast.Constant):
                    parts.append(str(part.value))
                elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
                    parts.append(consts.get(part.value.id, "{" + part.value.id + "}"))
                else:
                    parts.append("{" + ast.unparse(part.value) + "}")
            out[k.value] = "".join(parts)
            continue
        try:
            out[k.value] = str(ast.literal_eval(v))
        except Exception:
            continue
    return out or None


def extract_script_description_from_path(script_path: str) -> Optional[str]:
    """Extract `_script_description` or `main._script_description` string from a script file."""
    try:
        with open(script_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, filename=script_path)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            name_match = (isinstance(target, ast.Name) and target.id == "_script_description") or (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "main"
                and target.attr == "_script_description"
            )
            if name_match:
                try:
                    val = ast.literal_eval(node.value)
                    return str(val) if isinstance(val, str) else None
                except Exception:
                    return None
    return None


def extract_arg_descriptions_from_path(script_path: str) -> Optional[Dict[str, str]]:
    """Extract `_arg_descriptions` or `main._arg_descriptions` dict from a script file."""
    try:
        with open(script_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, filename=script_path)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            name_match = (isinstance(target, ast.Name) and target.id == "_arg_descriptions") or (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "main"
                and target.attr == "_arg_descriptions"
            )
            if name_match:
                return _descriptions_from_dict_node(node.value, _module_string_constants(tree))
    return None


def normalize_host_os_constraints(target_rules: Optional[Dict[str, Any]]) -> Optional[list[str]]:
    """Convert script target rules into campaign host OS constraints when applicable."""
    if not target_rules or target_rules.get("target_type") != "host":
        return None

    host_os = target_rules.get("host_os")
    if not host_os or host_os == "all":
        return None

    if isinstance(host_os, str):
        return [host_os]

    if isinstance(host_os, list):
        values = [str(item) for item in host_os if item]
        return values or None

    return None


# --- Target compatibility (backend twin of frontend/src/utils/targetCompatibility.ts) ---
# The frontend only offers targets a script's _target_rules accept; API callers
# (/server/script/execute) must be held to the same rules. Keep the two in step.

_TARGET_TYPES = ("all", "host", "device")
_HOST_OS_VALUES = ("all", "linux", "windows", "mac")


def normalize_target_rules(rules: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Same defaults as normalizeTargetRules(): device / all / all."""
    rules = rules or {}
    target_type = rules.get("target_type")
    host_os = rules.get("host_os")
    device_model = rules.get("device_model")
    return {
        "target_type": target_type if target_type in _TARGET_TYPES else "device",
        "host_os": host_os if host_os in _HOST_OS_VALUES else "all",
        "device_model": device_model.strip() if isinstance(device_model, str) and device_model.strip() else "all",
    }


def _normalize_platform(platform_name: Optional[str]) -> str:
    value = (platform_name or "").strip().lower()
    if not value:
        return "unknown"
    if "win" in value:
        return "windows"
    if "darwin" in value or "mac" in value:
        return "mac"
    if "linux" in value:
        return "linux"
    return "unknown"


def _device_matches_model(device: Dict[str, Any], device_model_rule: str) -> bool:
    if device_model_rule == "all":
        return True
    from shared.src.lib.config.device_capabilities import get_compatible_models

    device_model = (device.get("device_model") or "").strip().lower()
    rule_models = [m.strip() for m in device_model_rule.lower().split("|")]
    if any(m == "all" or m == device_model for m in rule_models):
        return True
    family_models = get_compatible_models(device_model)
    return any(m in family_models for m in rule_models)


def _has_host_target(host: Dict[str, Any]) -> bool:
    """The `host` device (host_vnc browser device) only exists on hosts set up with VNC + capture."""
    return any(
        d.get("device_id") == "host" or (d.get("device_model") or "").strip().lower() == "host_vnc"
        for d in (host.get("devices") or [])
    )


def target_incompatibility(
    rules_input: Optional[Dict[str, Any]], host: Dict[str, Any], device_id: str
) -> str:
    """Why `host_name:device_id` is not a valid target for a script, or "" when it is.

    Mirrors isTargetKeyCompatibleWithRules() in the frontend.
    """
    rules = normalize_target_rules(rules_input)
    host_name = host.get("host_name", "?")

    if rules["host_os"] != "all":
        platform_name = _normalize_platform((host.get("system_stats") or {}).get("platform"))
        if platform_name != rules["host_os"]:
            return f"script requires a {rules['host_os']} host; {host_name} is {platform_name}"

    if not device_id or device_id == "host":
        if rules["target_type"] == "device":
            return f"script runs on a device, not on the host target of {host_name}"
        if rules["target_type"] == "host" and not _has_host_target(host):
            return f"script runs on the host target, and {host_name} has no host target (no host_vnc device)"
        return ""

    if rules["target_type"] == "host":
        return f"script runs on the host target only (device_id 'host'), not on device '{device_id}'"

    device = next((d for d in (host.get("devices") or []) if d.get("device_id") == device_id), None)
    if device is None:
        return f"device '{device_id}' not found on {host_name}"
    if not _device_matches_model(device, rules["device_model"]):
        return (f"script requires device model '{rules['device_model']}'; "
                f"'{device_id}' on {host_name} is '{device.get('device_model')}'")
    return ""
