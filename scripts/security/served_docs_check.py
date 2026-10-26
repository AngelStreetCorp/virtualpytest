#!/usr/bin/env python3
"""Fail if a doc served over MCP (docs_tools.py) holds non-anonymized data.

The served set comes from backend_server/src/mcp/tools/docs_tools.py (the single source of truth);
no filter rule is copied here. Rules: docs/agent/release/ANONYMIZATION.md ("Docs served over MCP").
Output: <path>:<line>:<match>, exit 1 on any hit. Stdlib only.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend_server" / "src" / "mcp" / "tools"))
import docs_tools as dt  # noqa: E402

# Generic tutorial / documentation address blocks that may stay (get-started, user-guide, technical
# examples). Any other private or tailnet address (lab 192.168.0.x, 10.10.41.x, 100.64/10 ...) fails.
ALLOWED_IP_PREFIXES = ("192.168.1.", "10.10.10.", "10.0.0.", "10.0.1.", "10.0.2.", "10.0.3.",
                       "10.200.200.", "10.128.0.", "10.255.255.")
IP_RE = re.compile(r"(?<![\d.])(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
                   r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})(?![\d.]*\d)")

# Lab subnets with a placeholder octet (192.168.0.xxx, 192.168.0.<VMID>, 10.10.41.{n} ...): the network itself leaks.
LAB_SUBNET_RE = re.compile(r"(?<![\d.])(?:192\.168\.0|10\.10\.41)\.(?=[A-Za-z<{$*])")

PATTERNS = [  # (label, regex)
    ("internal-host", re.compile(r"(?<![\w-])(?!virtualpytest\.angelstreet\.io)[\w-]+\.angelstreet\.io\b", re.I)),
    ("home-path", re.compile(r"/Users/[A-Za-z0-9._-]+/")),
    ("domain-email", re.compile(r"[\w.+-]+@angelstreet\.io", re.I)),
    ("clear-password", re.compile(r"PGPASSWORD=(?![\s$<\"'`]|\{)\S+")),
    ("secret", re.compile(r"sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{10,}|xox[bap]-(?!X|YOUR)[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{20,}\.")),
]


def served_files():
    root = dt._docs_root()
    for p in dt._iter_doc_files(root):
        rel = p.relative_to(root).as_posix()
        if not dt._is_sensitive_path(rel) and not dt._is_internal_path(rel):
            yield p, rel


def scan(text):
    for n, line in enumerate(text.splitlines(), 1):
        for m in IP_RE.finditer(line):
            if not m.group(0).startswith(ALLOWED_IP_PREFIXES):
                yield n, "private-ip", m.group(0)
        for m in LAB_SUBNET_RE.finditer(line):
            yield n, "lab-subnet", line[m.start():m.start() + 16]
        for label, rx in PATTERNS:
            for m in rx.finditer(line):
                yield n, label, m.group(0)


def main():
    hits = 0
    count = 0
    for p, rel in served_files():
        count += 1
        for n, label, match in scan(p.read_text(encoding="utf-8", errors="replace")):
            print(f"docs/{rel}:{n}:{label}: {match}")
            hits += 1
    if hits:
        print(f"served_docs_check: {hits} hit(s) in {count} served docs; anonymize them "
              "(docs/agent/release/ANONYMIZATION.md)", file=sys.stderr)
        return 1
    print(f"served_docs_check: {count} served docs clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
