"""
Shared helpers for JavaScript-based web verifications.

Use this module from scripts to make it explicit that checks are
JavaScript/DOM verifications (not image-based verification).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict


def execute_javascript_verification(
    web_controller: Any,
    verification_name: str,
    script: str,
) -> Dict[str, Any]:
    """
    Execute a JavaScript verification against the Playwright web controller.

    Returns a standardized payload that always includes:
    - verification_type: "javascript"
    - verification_name: caller-defined label
    - success: execution status
    - result: JS evaluation result payload (if successful)
    - error: error message (if any)
    """
    if not web_controller:
        return {
            "success": False,
            "verification_type": "javascript",
            "verification_name": verification_name,
            "result": None,
            "error": "No web controller provided",
            "execution_time_ms": 0,
        }

    try:
        js_result = asyncio.run(web_controller.execute_javascript(script))
    except Exception as exc:
        return {
            "success": False,
            "verification_type": "javascript",
            "verification_name": verification_name,
            "result": None,
            "error": f"JavaScript verification failed: {exc}",
            "execution_time_ms": 0,
        }

    return {
        "success": bool(js_result.get("success")),
        "verification_type": "javascript",
        "verification_name": verification_name,
        "result": js_result.get("result"),
        "error": js_result.get("error", ""),
        "execution_time_ms": int(js_result.get("execution_time", 0) or 0),
    }

