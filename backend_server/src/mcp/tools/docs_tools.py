"""
Docs Tools

Read and search VirtualPyTest documentation files so agents can answer
user questions about the platform accurately.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, List, Optional


# Patterns that indicate sensitive/hidden files — never expose via MCP
SENSITIVE_PATTERNS = {
    '.env', '.env.example', '.env.local', '.env.production',
    '.git', '.gitignore', '.gitmodules',
    '.ssh', '.aws', '.docker', '.npmrc', '.pypirc',
    'credentials', 'secrets', 'token', 'private_key',
    'id_rsa', 'id_ed25519', '.pem', '.key', '.p12', '.pfx',
}


def _is_sensitive_path(path: str) -> bool:
    """Check if a file path references a sensitive/hidden file."""
    path_lower = path.lower()
    parts = Path(path_lower).parts
    for part in parts:
        # Block dotfiles/dotdirs (except the docs root itself)
        if part.startswith('.'):
            return True
        # Block known sensitive filenames
        for pattern in SENSITIVE_PATTERNS:
            if pattern in part:
                return True
    return False


def _docs_root() -> Path:
    """Resolve the docs/ directory regardless of where the server is launched from."""
    # backend_server/src/mcp/tools/ → project root → docs/
    return Path(__file__).resolve().parents[4] / "docs"


# Bug reports and release notes are history, not reference: they rank below the guides in search_docs
_LOG_SECTIONS = ("bugs/", "release_note/")

# Readable doc formats: markdown guides + OpenAPI specs (docs/api/specs/*.yaml)
READABLE_SUFFIXES = {".md", ".yaml", ".yml"}

# Entries of scripts/security/internal-paths.txt that are NOT applied here. `docs/agent/` is the
# public-snapshot rule ("agent docs never publish"); this MCP deliberately serves the agent docs
# (anonymised, see docs/agent/release/ANONYMIZATION.md). Every finer entry still applies.
_SERVED_DESPITE_PUBLIC_STRIP = {"docs/agent/"}


def _repo_root() -> Path:
    return _docs_root().parent


def _entry_regex(entry: str, gitignore: bool) -> "re.Pattern[str]":
    """Compile a docs/ path rule. `*` stays inside one segment. gitignore entries match the
    path or a directory prefix of it; internal-paths entries are plain prefixes."""
    body = re.escape(entry.casefold()).replace(r"\*", "[^/]*")
    if gitignore and not entry.endswith("/"):
        body += "(?:/|$)"
    return re.compile("^" + body)


@lru_cache(maxsize=1)
def _internal_rules() -> List["re.Pattern[str]"]:
    """Parse the repo-root .gitignore and scripts/security/internal-paths.txt once.
    Only `docs/` lines matter; `!` negations are not supported and skipped; a missing file is skipped."""
    rules: List["re.Pattern[str]"] = []
    sources = ((".gitignore", True), ("scripts/security/internal-paths.txt", False))
    for rel, is_gitignore in sources:
        try:
            lines = (_repo_root() / rel).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            entry = line.strip()
            if entry.startswith("/docs/"):
                entry = entry[1:]
            if not entry.startswith("docs/") or entry in _SERVED_DESPITE_PUBLIC_STRIP:
                continue
            rules.append(_entry_regex(entry, is_gitignore))
    return rules


def _is_internal_path(relative: str) -> bool:
    """True if a path relative to docs/ is internal-only (gitignored or on the internal-paths list).
    Path rules only, no git at runtime, so tracked-but-gitignored files are blocked too."""
    full = "docs/" + relative.replace("\\", "/").lstrip("/").casefold()
    return any(rule.match(full) for rule in _internal_rules())


def _iter_doc_files(search_root: Path):
    """Yield readable doc files (markdown + YAML specs) under search_root, sorted."""
    files = [p for p in search_root.rglob("*") if p.suffix in READABLE_SUFFIXES and p.is_file()]
    return sorted(files)


class DocsTools:
    """Tools for reading VirtualPyTest documentation"""

    def list_docs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List available documentation files organised by section.
        Returns a tree of all markdown files and OpenAPI YAML specs in docs/ so the agent can pick which one to read.

        Example: list_docs()
        Example: list_docs(section='agent')

        Args:
            params: {
                'section': str (OPTIONAL) - Restrict the listing to one docs/ section such as 'agent' or 'user-guide'
            }
        """
        section: Optional[str] = params.get("section")
        root = _docs_root()

        if not root.exists():
            return {"success": False, "error": f"docs/ directory not found at {root}"}

        search_root = root / section if section else root
        if not search_root.exists():
            return {"success": False, "error": f"Section '{section}' not found in docs/"}

        tree: Dict[str, List[str]] = {}
        for md_file in _iter_doc_files(search_root):
            relative = md_file.relative_to(root)
            # Skip sensitive/hidden files and directories
            if _is_sensitive_path(str(relative)) or _is_internal_path(relative.as_posix()):
                continue
            parts = relative.parts
            folder = str(parts[0]) if len(parts) > 1 else "."
            tree.setdefault(folder, []).append(str(relative))

        total = sum(len(v) for v in tree.values())
        return {
            "success": True,
            "docs_root": str(root),
            "total_files": total,
            "sections": tree,
        }

    def read_doc(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Read the contents of a documentation file. Path is relative to docs/ (e.g. 'agent/navigation/MAP.md').
        Supports markdown guides and OpenAPI YAML specs (docs/api/specs/*.yaml for API questions).
        Unsure which file answers the question? read_doc(path='INDEX.md') is the master index.

        Internal-only docs are never served.

        Example: read_doc(path='INDEX.md')
        Example: read_doc(path='user-guide/getting-started.md')
        Example: read_doc(path='api/specs/server-script-management.yaml')

        Args:
            params: {
                'path': str (REQUIRED) - File path relative to docs/, e.g. 'agent/navigation/MAP.md'
            }
        """
        path: Optional[str] = params.get("path")
        if not path:
            return {"success": False, "error": "path parameter is required"}

        # Sanitize: no absolute paths, no traversal outside docs/
        clean = path.lstrip("/").replace("..", "")

        # Block sensitive/hidden files
        if _is_sensitive_path(clean):
            return {"success": False, "error": "Access denied: cannot read sensitive or hidden files"}

        target = (_docs_root() / clean).resolve()
        docs_root_resolved = _docs_root().resolve()

        if not str(target).startswith(str(docs_root_resolved)):
            return {"success": False, "error": "Path outside docs/ directory"}

        if _is_internal_path(target.relative_to(docs_root_resolved).as_posix()) or _is_internal_path(clean):
            return {"success": False, "error": "Access denied: internal-only doc, not served"}

        if not target.exists():
            # Docs move between folders (agent/INFRARED.md -> agent/devices/INFRARED.md): name the
            # served files with the same filename so the agent reads the right one next.
            same_name = [p.relative_to(docs_root_resolved).as_posix()
                         for p in _iter_doc_files(docs_root_resolved) if p.name.lower() == target.name.lower()]
            same_name = [p for p in same_name if not _is_sensitive_path(p) and not _is_internal_path(p)]
            hint = f" Did you mean: {', '.join(same_name)}" if same_name else ""
            return {"success": False, "error": f"File not found: {path}.{hint}", "suggestions": same_name}

        if target.suffix not in READABLE_SUFFIXES:
            return {"success": False, "error": "Only markdown (.md) and OpenAPI spec (.yaml/.yml) files are readable"}

        content = target.read_text(encoding="utf-8")
        return {
            "success": True,
            "path": path,
            "size_chars": len(content),
            "content": content,
        }

    def search_docs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search for a keyword across all documentation files.
        Returns matching file paths with a short excerpt around each match.
        Use this to find which doc file to read_doc when you don't know the exact path.

        Example: search_docs(query='navigation tree')
        Example: search_docs(query='redis queue', section='agent')

        Args:
            params: {
                'query': str (REQUIRED) - Keyword to search for across documentation files,
                'section': str (OPTIONAL) - Restrict the search to a documentation section,
                'max_results': int (OPTIONAL) - Maximum number of files to return (default 10)
            }

        Returns:
            MCP-formatted response with matching file paths and excerpts.
        """
        query: Optional[str] = params.get("query")
        section: Optional[str] = params.get("section")
        max_results: int = int(params.get("max_results", 10))

        if not query:
            return {"success": False, "error": "query parameter is required"}

        root = _docs_root()
        search_root = root / section if section else root
        if not search_root.exists():
            return {"success": False, "error": f"Section '{section}' not found"}

        # Every word must appear somewhere in the file (not as one phrase): "IR key map" finds the
        # infrared doc. A word matches at a word start ("ir" is not found inside "their"). Files are
        # ranked by hits per word, capped so a huge file does not win on size, plus a bonus when the
        # word is a word of the file name. Bug reports and release notes rank at half score.
        words = [w for w in re.split(r"\s+", query.lower()) if w]
        patterns = [re.compile(r"(?<![a-z0-9])" + re.escape(w)) for w in words]
        matches = []

        for md_file in _iter_doc_files(search_root):
            # Skip sensitive/hidden files
            relative_path = str(md_file.relative_to(root))
            if _is_sensitive_path(relative_path) or _is_internal_path(relative_path):
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            text_lower = text.lower()
            counts = [len(pat.findall(text_lower)) for pat in patterns]
            if not all(counts):
                continue

            lines = text.splitlines()
            line_hits = {i: sum(bool(pat.search(line.lower())) for pat in patterns) for i, line in enumerate(lines)}
            # Excerpts: the lines holding the most query words
            best = sorted((i for i, n in line_hits.items() if n), key=lambda i: -line_hits[i])[:3]
            file_matches = []
            for i in sorted(best):
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                excerpt = "\n".join(lines[start:end]).strip()
                file_matches.append({"line": i + 1, "excerpt": excerpt[:300]})

            name_tokens = set(re.split(r"[-_.]", md_file.stem.lower()))
            score = sum(min(c, 10) for c in counts) + sum(20 for w in words if w in name_tokens)
            if relative_path.startswith(_LOG_SECTIONS):
                score //= 2
            matches.append({
                "path": relative_path,
                "match_count": sum(counts),
                "score": score,
                "matches": file_matches,
            })

        matches.sort(key=lambda m: -m["score"])
        matches = matches[:max_results]

        return {
            "success": True,
            "query": query,
            "total_files_matched": len(matches),
            "results": matches,
        }
