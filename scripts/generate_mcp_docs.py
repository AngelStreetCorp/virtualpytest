#!/usr/bin/env python3
"""
Generate MCP tool reference markdown from backend tool definition files.

Source of truth:
  backend_server/src/mcp/tool_definitions/*_definitions.py
Output:
  docs/mcp/mcp_tools_generated.md
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFS_DIR = ROOT / "backend_server" / "src" / "mcp" / "tool_definitions"
OUT_FILE = ROOT / "docs" / "mcp" / "mcp_tools_generated.md"

NAME_RE = re.compile(r'"name"\s*:\s*"([a-z_]+)"')


def humanize_category(stem: str) -> str:
    base = stem.replace("_definitions", "")
    return base.replace("_", " ").title()


def collect_tools() -> dict[str, list[str]]:
    by_category: dict[str, list[str]] = defaultdict(list)
    for path in sorted(DEFS_DIR.glob("*_definitions.py")):
        text = path.read_text(encoding="utf-8")
        tools = sorted(set(NAME_RE.findall(text)))
        if not tools:
            continue
        by_category[path.stem] = tools
    return dict(by_category)


def write_markdown(by_category: dict[str, list[str]]) -> None:
    total = sum(len(v) for v in by_category.values())
    lines: list[str] = []
    lines.append("# MCP Tools (Generated)")
    lines.append("")
    lines.append("This file is auto-generated. Do not edit manually.")
    lines.append("")
    lines.append(f"- Total tools: **{total}**")
    lines.append(f"- Categories: **{len(by_category)}**")
    lines.append("- Source: `backend_server/src/mcp/tool_definitions/*_definitions.py`")
    lines.append("")
    for stem, tools in by_category.items():
        lines.append(f"## {humanize_category(stem)} ({len(tools)})")
        lines.append("")
        for tool in tools:
            lines.append(f"- `{tool}`")
        lines.append("")
    OUT_FILE.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if not DEFS_DIR.exists():
        print(f"[mcp-docs] ERROR: definitions dir missing: {DEFS_DIR}")
        return 1
    by_category = collect_tools()
    if not by_category:
        print("[mcp-docs] ERROR: no tools discovered")
        return 1
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(by_category)
    total = sum(len(v) for v in by_category.values())
    print(f"[mcp-docs] Generated {OUT_FILE} ({total} tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
