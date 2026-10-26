#!/usr/bin/env python3
"""Generate docs/agent/game/lol/champions/<champion>.md from <champion>.yaml (never hand-edit the .md).

    python3 scripts/gen_lol_champion_pages.py          # write
    python3 scripts/gen_lol_champion_pages.py --check  # exit 1 when a page is stale
"""
import sys
from pathlib import Path

import yaml

DIR = Path(__file__).resolve().parent.parent / "docs" / "agent" / "game" / "lol" / "champions"


def _short(v):
    return not isinstance(v, (dict, list)) or (isinstance(v, list) and all(not isinstance(x, (dict, list)) and len(str(x)) < 25 for x in v))


def _inline(v):
    return ", ".join(map(str, v)) if isinstance(v, list) else str(v)


def _fmt(v, depth=0):
    """Markdown bullets, one per key / list item; short scalar lists stay on one line."""
    pad = "  " * depth
    if isinstance(v, dict):
        out = ""
        for k, x in v.items():
            out += f"{pad}- **{k}**: {_inline(x)}\n" if _short(x) else f"{pad}- **{k}**:\n{_fmt(x, depth + 1)}"
        return out
    if isinstance(v, list):
        if _short(v):
            return f"{pad}{_inline(v)}\n"
        return "".join(f"{pad}- {x}\n" if _short(x) else f"{pad}-\n{_fmt(x, depth + 1)}" for x in v)
    return f"{pad}{v}\n"


def render(path: Path) -> str:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    name = d["champion"]
    out = [f"---\ntitle: {name} (League of Legends)\nsummary: Per-role knowledge for {name}: kit, skill order, runes, build, power spikes, matchups and the scorecard reference numbers, each with its sources.\n"
           f"tags: [agent, game, lol]\nkeywords: [league of legends, {name.lower()}, {', '.join(d['roles'])}, matchups, build, scorecard reference]\n---\n",
           f"<!-- GENERATED from {path.name} by scripts/gen_lol_champion_pages.py. Do not edit; edit the YAML. -->\n",
           f"# {name}\n"]
    for role, body in d["roles"].items():
        out.append(f"## {role}\n")
        for key, val in body.items():
            out.append(f"### {key}\n\n{_fmt(val)}")
    out.append("\n---\n← [LoL knowledge](../README.md) · [Agent docs index](../../../README.md)\n")
    return "\n".join(out)


def main() -> int:
    stale = False
    for y in sorted(DIR.glob("*.yaml")):
        md, text = y.with_suffix(".md"), render(y)
        if "--check" in sys.argv:
            if not md.exists() or md.read_text(encoding="utf-8") != text:
                print(f"stale: {md}")
                stale = True
        else:
            md.write_text(text, encoding="utf-8")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
