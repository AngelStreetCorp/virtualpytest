"""
Docs Tools

Read and search VirtualPyTest documentation files so agents can answer
user questions about the platform accurately.
"""

import os
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


# Readable doc formats: markdown guides + OpenAPI specs (docs/api/specs/*.yaml)
READABLE_SUFFIXES = {".md", ".yaml", ".yml"}


def _iter_doc_files(search_root: Path):
    """Yield readable doc files (markdown + YAML specs) under search_root, sorted."""
    files = [p for p in search_root.rglob("*") if p.suffix in READABLE_SUFFIXES]
    return sorted(files)


class DocsTools:
    """Tools for reading VirtualPyTest documentation"""

    def list_docs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List available documentation files organised by section.
        Returns a tree of all markdown files and OpenAPI YAML specs in docs/ so the agent can pick which one to read.

        Example: list_docs()
        Example: list_docs(section='agent')
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
            if _is_sensitive_path(str(relative)):
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
        Read the contents of a documentation file. Path is relative to docs/ (e.g. 'agent/MAP.md').
        Supports markdown guides and OpenAPI YAML specs (docs/api/specs/*.yaml for API questions).
        Unsure which file answers the question? read_doc(path='INDEX.md') is the master index.

        Example: read_doc(path='INDEX.md')
        Example: read_doc(path='user-guide/getting-started.md')
        Example: read_doc(path='api/specs/server-script-management.yaml')
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

        if not target.exists():
            return {"success": False, "error": f"File not found: {path}"}

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

        query_lower = query.lower()
        matches = []

        for md_file in _iter_doc_files(search_root):
            # Skip sensitive/hidden files
            relative_path = str(md_file.relative_to(root))
            if _is_sensitive_path(relative_path):
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            lines = text.splitlines()
            file_matches = []
            for i, line in enumerate(lines):
                if query_lower in line.lower():
                    start = max(0, i - 1)
                    end = min(len(lines), i + 2)
                    excerpt = "\n".join(lines[start:end]).strip()
                    file_matches.append({"line": i + 1, "excerpt": excerpt[:300]})
                    if len(file_matches) >= 3:
                        break

            if file_matches:
                matches.append({
                    "path": str(md_file.relative_to(root)),
                    "match_count": len(file_matches),
                    "matches": file_matches,
                })
                if len(matches) >= max_results:
                    break

        return {
            "success": True,
            "query": query,
            "total_files_matched": len(matches),
            "results": matches,
        }
