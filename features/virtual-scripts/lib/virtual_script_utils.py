#!/usr/bin/env python3
"""
Virtual Script utilities — syntax/structure validation and metadata extraction
for DB-stored Python test scripts. See docs/agent/execution/VIRTUAL_SCRIPTS.md.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, Optional


def validate_python_syntax(source: str, filename: str = "virtual_script.py") -> Dict[str, Any]:
    """Compile the source to catch SyntaxError. Returns {valid, error?}.

    error = {line, offset, msg} so the editor can place an inline marker.
    """
    try:
        compile(source or "", filename, "exec")
        return {"valid": True}
    except SyntaxError as exc:
        return {
            "valid": False,
            "error": {
                "line": exc.lineno or 1,
                "offset": exc.offset or 1,
                "msg": exc.msg or "Syntax error",
                "text": (exc.text or "").rstrip("\n"),
            },
        }
    except (ValueError, TypeError) as exc:
        # e.g. source containing null bytes
        return {"valid": False, "error": {"line": 1, "offset": 1, "msg": str(exc), "text": ""}}


def _has_script_decorator_or_args(tree: ast.Module) -> Dict[str, bool]:
    """Detect the @script decorator and a *._script_args assignment in the AST."""
    has_decorator = False
    has_script_args = False

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Name) and target.id == "script":
                    has_decorator = True
                elif isinstance(target, ast.Attribute) and target.attr == "script":
                    has_decorator = True
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Attribute) and tgt.attr == "_script_args":
                    has_script_args = True
                elif isinstance(tgt, ast.Name) and tgt.id == "_script_args":
                    has_script_args = True

    return {"has_decorator": has_decorator, "has_script_args": has_script_args}


def validate_virtual_script(source: str) -> Dict[str, Any]:
    """Full save-time validation: syntax (hard) + structure (soft warnings).

    Returns {valid, error?, warnings: [str]}. `valid` is False only on a real
    SyntaxError — missing @script/_script_args are warnings, not blockers, so a
    user can save a work-in-progress.
    """
    syntax = validate_python_syntax(source)
    if not syntax.get("valid"):
        return {"valid": False, "error": syntax.get("error"), "warnings": []}

    warnings = []
    tree = ast.parse(source)  # safe: syntax already validated
    structure = _has_script_decorator_or_args(tree)
    if not structure["has_decorator"]:
        warnings.append("No @script(...) decorator found — the script may not run on the platform.")
    if not structure["has_script_args"]:
        warnings.append("No _script_args defined — no parameters will be parsed for this script.")

    return {"valid": True, "error": None, "warnings": warnings}


def extract_virtual_script_metadata(source: str) -> Dict[str, Optional[Any]]:
    """Pull _script_description and _target_rules out of the source (best-effort)."""
    from shared.src.lib.utils.script_target_rules_utils import (
        extract_script_description_from_source,
        extract_script_target_rules_from_source,
    )
    return {
        "description": extract_script_description_from_source(source),
        "target_rules": extract_script_target_rules_from_source(source),
    }
