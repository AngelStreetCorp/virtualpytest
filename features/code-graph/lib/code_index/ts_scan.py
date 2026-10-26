"""Scan a frontend file for /server/... and /host/... URL literals (regex; TS is not parsed)."""
from typing import List

from .constants import TS_TEMPLATE_VAR_RE, URL_LITERAL_RE, WILDCARD
from .types import UrlRef


def scan_ts_urls(rel_path: str, source: str) -> List[UrlRef]:
    refs: List[UrlRef] = []
    for lineno, line in enumerate(source.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(("//", "*", "/*")):
            continue
        for m in URL_LITERAL_RE.finditer(line):
            refs.append(UrlRef(TS_TEMPLATE_VAR_RE.sub(WILDCARD, m.group(1)), rel_path, lineno))
    return refs
