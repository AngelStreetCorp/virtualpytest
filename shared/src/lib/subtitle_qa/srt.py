"""SRT parsing and text normalisation for subtitle QA."""
import re
from dataclasses import dataclass
from typing import List

_TIME = re.compile(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)')
_TAGS = re.compile(r'<[^>]+>|\{\\[^}]*\}')


@dataclass(frozen=True)
class Cue:
    index: int
    start: float
    end: float
    text: str  # raw, lines joined with '\n'

    @property
    def norm(self) -> str:
        return normalize(self.text)


def _secs(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, '0')[:3]) / 1000.0


def parse_srt(content: str) -> List[Cue]:
    cues: List[Cue] = []
    for block in re.split(r'\r?\n\s*\r?\n', content.strip().lstrip('﻿')):
        lines = [l for l in block.splitlines() if l.strip() != '']
        for i, line in enumerate(lines):
            m = _TIME.search(line)
            if m:
                g = m.groups()
                text = '\n'.join(_TAGS.sub('', l).strip() for l in lines[i + 1:])
                cues.append(Cue(len(cues) + 1, _secs(*g[:4]), _secs(*g[4:]), text))
                break
    return cues


def normalize(text: str) -> str:
    """Lowercase, drop tags, collapse whitespace, keep letters/digits/apostrophes only."""
    text = _TAGS.sub(' ', text).lower()
    text = re.sub(r"[^\w' ]+", ' ', text, flags=re.UNICODE).replace('_', ' ')
    return re.sub(r'\s+', ' ', text).strip()
