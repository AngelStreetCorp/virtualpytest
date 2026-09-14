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
                try:
                    val = ast.literal_eval(node.value)
                    if isinstance(val, dict):
                        return {str(k): str(v) for k, v in val.items()}
                except Exception:
                    return None
    return None


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
                try:
                    val = ast.literal_eval(node.value)
                    if isinstance(val, dict):
                        return {str(k): str(v) for k, v in val.items()}
                except Exception:
                    return None
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
