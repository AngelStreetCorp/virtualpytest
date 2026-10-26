#!/usr/bin/env python3
"""Check docs/release_note/README.md against the entry rules in docs/release_note/AUTHORING.md.

- every `## ` list uses only these headings, each at most once: Features, Improvements,
  Bug fixes, Security, Internal, Upgrade;
- every Features and Improvements bullet ends with ` · area: <slug>`, slug from the fixed list.

Exit 1 with one line per problem. Run from anywhere: python3 scripts/release/check_release_notes.py
"""
import re
import sys
from pathlib import Path

AREAS = {"device-control", "monitoring", "testing", "ai", "integrations", "platform", "entertainment"}
HEADINGS = {"features", "improvements", "bug fixes", "security", "internal", "upgrade"}
NOTE = Path(__file__).resolve().parents[2] / "docs" / "release_note" / "README.md"


MAX_FEATURES = 30  # one feature = one entry: a build with more is a list of improvements in disguise


def title_of(line):
    m = re.match(r"^- \*\*(.+?)\*\*", line)
    return re.sub(r"[^a-z0-9]+", " ", (m.group(1) if m else line[2:60]).lower()).strip()


def check(text):
    errors, build, seen, kind, fence = [], None, set(), None, False
    counts, titles = {}, {}
    for no, line in enumerate(text.split("\n"), 1):
        if line.startswith("```"):
            fence = not fence
        if fence or line.startswith("```"):
            continue
        if line.startswith("## "):
            build, seen, kind = line[3:].strip(), set(), None
            counts, titles = {}, {}
            continue
        m = re.match(r"^### (.*)$", line)
        if m and build:
            name = m.group(1).strip().lower()
            if name not in HEADINGS:
                errors.append(f"{no}: '{build}' has an unknown heading '### {m.group(1).strip()}' (allowed: Features, Improvements, Bug fixes, Security, Internal, Upgrade)")
                kind = None
            elif name in seen:
                errors.append(f"{no}: '{build}' has '### {m.group(1).strip()}' twice; each heading appears once")
            seen.add(name)
            kind = name
            continue
        if build and kind in ("features", "improvements") and line.startswith("- "):
            t = title_of(line)
            if t in titles.get(kind, set()):
                errors.append(f"{no}: duplicate {kind[:-1]} '{t}': update the existing entry instead of adding one")
            titles.setdefault(kind, set()).add(t)
            if kind == "features":
                counts[build] = counts.get(build, 0) + 1
                if counts[build] == MAX_FEATURES + 1:
                    errors.append(f"{no}: '{build}' has more than {MAX_FEATURES} Features; merge related entries or move polish to Improvements")
            am = re.search(r" · area: ([\w-]+)\s*$", line)
            if not am:
                errors.append(f"{no}: {kind[:-1]} without ' · area: <slug>': {line[:70]}")
            elif am.group(1) not in AREAS:
                errors.append(f"{no}: unknown area '{am.group(1)}' (allowed: {', '.join(sorted(AREAS))})")
    return errors


if __name__ == "__main__":
    errs = check(NOTE.read_text())
    for e in errs:
        print(f"release_note/README.md:{e}", file=sys.stderr)
    sys.exit(1 if errs else 0)
