"""Docs excerpts for the website widget, found BEFORE the first model call.

The old public path let the model discover the docs itself: read INDEX.md, read the FAQ, search, read a
file, answer, i.e. 4-5 round trips (40 s once). Here the server ranks the doc sections that match the
question and puts the best ones in the prompt, so most questions need one model call.

The index is built once per process from the public doc sections (same sensitive / internal path gates
as the MCP docs tools) and holds heading-split sections with an inverted index; a query is a dictionary
walk (a few ms). Ranking is idf-weighted term frequency with bonuses for a word in the heading or the
file name; ``grounded`` is true only when the sections cover most of the question's rare words, so an
off-topic or unrelated question falls to the model's own decline / tool path instead of being forced
onto a random excerpt.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from mcp.tools.docs_tools import _docs_root, _is_internal_path, _is_sensitive_path

from .faqs_public import token_list

# Reference docs only. Tasks, bug reports and release notes are history, not answers.
DOC_ROOTS = ("faq", "features", "get-started", "user-guide", "integrations", "goals", "technical", "mcp", "ai", "agent")
MIN_BODY_CHARS = 120
MAX_SECTION_CHARS = 2200
MAX_CONTEXT_CHARS = 6500
TOP_SECTIONS = 3
# Share of the question's idf mass the best section must cover to count as grounded.
GROUNDED_COVERAGE = 0.6
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _frontmatter(text: str) -> str:
    """Title, summary and keywords of a doc: the author's own statement of what the file answers."""
    m = _FRONT.match(text)
    if not m:
        return ""
    return " ".join(line.split(":", 1)[1] for line in m.group(1).splitlines()
                    if line.split(":", 1)[0].strip() in ("title", "summary", "keywords") and ":" in line)


_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


@dataclass(frozen=True)
class Section:
    path: str
    heading: str
    text: str


@dataclass(frozen=True)
class Context:
    sections: List[Section]
    grounded: bool

    @property
    def sources(self) -> List[str]:
        out: List[str] = []
        for s in self.sections:
            if s.path not in out:
                out.append(s.path)
        return out

    def render(self) -> str:
        parts, used = [], 0
        for s in self.sections:
            chunk = f"[{s.path} - {s.heading}]\n{s.text[:MAX_SECTION_CHARS]}"
            if used + len(chunk) > MAX_CONTEXT_CHARS:
                break
            parts.append(chunk)
            used += len(chunk)
        return "\n\n".join(parts)


class _DocIndex:
    def __init__(self, root: Path):
        self.sections: List[Section] = []
        self.postings: Dict[str, List[Tuple[int, int]]] = {}      # token -> [(section id, tf)]
        self.heading_tokens: List[frozenset] = []
        self.file_tokens: List[frozenset] = []              # name + title + keywords of the section's file
        self.file_all: Dict[str, frozenset] = {}            # every word of the file
        for top in DOC_ROOTS:
            base = root / top
            if not base.is_dir():
                continue
            for md in sorted(base.rglob("*.md")):
                rel = str(md.relative_to(root))
                if _is_sensitive_path(rel) or _is_internal_path(rel):
                    continue
                try:
                    self._add_file(rel, md.read_text(encoding="utf-8"))
                except OSError:
                    continue
        self.n = max(1, len(self.sections))

    def _add_file(self, rel: str, text: str) -> None:
        meta = _frontmatter(text)
        stem_tokens = frozenset(token_list(Path(rel).stem.replace("_", " ").replace("-", " ") + " " + meta))
        everything = set(stem_tokens)
        title, body, in_fence = Path(rel).stem, [], False
        blocks: List[Tuple[str, List[str]]] = []
        for line in text.splitlines():
            if line.startswith("```"):
                in_fence = not in_fence
            m = None if in_fence else _HEADING.match(line)
            if m:
                blocks.append((title, body))
                title, body = m.group(2), []
            else:
                body.append(line)
        blocks.append((title, body))
        for heading, lines in blocks:
            content = "\n".join(lines).strip()
            if len(content) < MIN_BODY_CHARS:
                continue
            sid = len(self.sections)
            self.sections.append(Section(rel, heading, content))
            self.heading_tokens.append(frozenset(token_list(heading)))
            self.file_tokens.append(stem_tokens)
            for token, tf in Counter(token_list(heading + " " + content)).items():
                self.postings.setdefault(token, []).append((sid, tf))
                everything.add(token)
        self.file_all[rel] = frozenset(everything)

    def idf(self, token: str) -> float:
        return math.log(1 + self.n / (1 + len(self.postings.get(token, ()))))

    def search(self, question: str) -> Context:
        query = [t for t in dict.fromkeys(token_list(question)) if t in self.postings]
        if not query:
            return Context([], False)
        mass = sum(self.idf(t) for t in query)
        scores: Dict[int, float] = {}
        for t in query:
            w = self.idf(t)
            for sid, tf in self.postings[t]:
                bonus = (2.0 if t in self.heading_tokens[sid] else 0.0) + (3.0 if t in self.file_tokens[sid] else 0.0)
                scores[sid] = scores.get(sid, 0.0) + w * (tf / (tf + 1.2) + bonus)
        ranked = sorted(scores, key=lambda sid: -scores[sid])
        picked: List[int] = []
        per_file: Counter = Counter()
        for sid in ranked:
            path = self.sections[sid].path
            if per_file[path] >= 2:
                continue
            per_file[path] += 1
            picked.append(sid)
            if len(picked) == TOP_SECTIONS:
                break
        # Coverage is measured over the question's words found anywhere in the docs, plus the words the
        # docs lack entirely: "fixnet pricing in mars" must not look grounded on "fixnet" alone.
        all_words = [t for t in dict.fromkeys(token_list(question))]
        missing = [t for t in all_words if t not in self.postings]
        total = mass + sum(math.log(1 + self.n) for _ in missing)
        in_file = self.file_all[self.sections[picked[0]].path] if picked else frozenset()
        covered = sum(self.idf(t) for t in query if t in in_file)
        grounded = bool(picked) and covered / total >= GROUNDED_COVERAGE
        return Context([self.sections[sid] for sid in picked], grounded)


_index = None
_lock = threading.Lock()


def _get() -> _DocIndex:
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                _index = _DocIndex(_docs_root())
    return _index


def find(question: str) -> Context:
    """Best doc sections for a question. Never raises: an index problem means no context (old tool path)."""
    try:
        return _get().search(question)
    except Exception as exc:  # noqa: BLE001
        print(f"[@public_ask] docs context skipped: {exc}")
        return Context([], False)
