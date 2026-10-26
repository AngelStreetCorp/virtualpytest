"""
Video Tools

Search the VirtualPyTest video library (docs/videos/videos.json) so agents can
answer user questions with the right tutorial, demo, or walkthrough — and embed
it inline in chat with the [[video:<id>]] token the frontend renders as a
click-to-play card.

The data file is the same one the in-app Videos page and the README block use
(scripts/gen_readme_videos.py generates both from it), so the tag taxonomy here
is the one shown to humans too.
"""

import json
import re
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, List, Optional


# YouTube video IDs are 11 chars from [A-Za-z0-9_-]. Same regex as the
# frontend VideoShowcase (idFromHash in frontend/src/components/docs/VideoShowcase.tsx).
_VIDEO_ID_RE = re.compile(r"[\w-]{11}")

# Stopwords kept out of word-level scoring so 'how to fly the drone' doesn't
# match every video that contains 'the' in its title.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "do", "for",
    "from", "has", "have", "how", "i", "in", "is", "it", "its", "of", "on",
    "or", "so", "that", "the", "their", "this", "to", "was", "we", "what",
    "when", "where", "which", "who", "why", "will", "with", "you", "your",
    "can", "do", "does", "use", "using",
}


def _videos_path() -> Path:
    """Resolve docs/videos/videos.json regardless of where the server is launched from.

    backend_server/src/mcp/tools/ → project root → docs/videos/videos.json
    """
    return Path(__file__).resolve().parents[4] / "docs" / "videos" / "videos.json"


def _normalize(s: str) -> str:
    """Lowercase + collapse non-alphanumeric so 'fingerprint', 'finger-print',
    'Finger print' all match the same query."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _score(video: Dict[str, Any], q_norm: str, q_words: List[str]) -> float:
    """Score a video against a normalized query string.

    Returns 0.0 when nothing relevant matches. Otherwise:
      - exact tag hit:                       +1.0
      - tag substring hit (q is a substring of any tag): +0.5
      - any non-stopword query word in title: +0.3
      - any non-stopword query word in summary: +0.1
      - any non-stopword query word in tags:  +0.4

    Recency is used as a TIE-BREAKER, not added to the score (every video in
    the library is < 60 days old, so a recency bonus would push everything
    into the result set).
    """
    if not q_norm:
        return 0.0

    tags = [_normalize(t) for t in video.get("tags") or []]
    title = _normalize(video.get("title") or "")
    summary = _normalize(video.get("summary") or "")

    score = 0.0

    if q_norm in tags:
        score += 1.0
    elif any(q_norm in t for t in tags if t):
        score += 0.5

    if q_words and any(w in t for t in tags if t for w in q_words):
        score += 0.4

    if q_words and any(w in title for w in q_words):
        score += 0.3

    if q_words and any(w in summary for w in q_words):
        score += 0.1

    return score


def _recency_key_sortable(video: Dict[str, Any]) -> int:
    """Sort key: newer videos win ties. Returns 0 when 'added' is missing/invalid
    so untagged videos sort together at the end."""
    added = video.get("added")
    if not added:
        return 0
    try:
        return date.fromisoformat(added).toordinal()
    except ValueError:
        return 0


class VideoTools:
    """Tools for searching the VirtualPyTest video library."""

    def search_videos(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search the video library by free-text query. Returns the top matches
        ranked by tag hit → title hit → summary hit → recency, with the
        YouTube id, title, summary, URL, thumbnail, tags and categories
        for each hit. Use this whenever the user asks for a tutorial, demo,
        walkthrough, or "show me a video about X".

        After calling this tool, include the chosen video's id in your reply
        as a [[video:<id>]] token (e.g. [[video:YWJ1uz8KHCo]]). The token
        MUST be exactly `[[video:<id>]]` — TWO opening brackets and TWO
        closing brackets, no spaces, no backticks, no markdown code fence.
        The chat UI's regex is `\[+video:<id>\]+` so it accepts 1-2 brackets
        on each side, but the documented form is double brackets. The chat UI
        replaces the token with a click-to-play card — never paste the raw
        YouTube URL or an <iframe>, the renderer only understands the token.

        params:
            'query': str (REQUIRED) - what the user wants to see (e.g. 'drone', 'how to fly a tello', 'Grafana', 'AI charts')
            'category': str (OPTIONAL) - restrict to one category key (e.g. 'ai', 'test', 'device', 'scripts', 'stream')
            'max_results': int (OPTIONAL) - cap the response, default 3, max 10

        Returns:
            success=true with `videos: [{id, title, summary, url, thumb, tags, categories, added, score}]`
            success=false with `error` if the data file is missing or the query is empty.

        Example: search_videos(query='how to fly the drone')
        Example: search_videos(query='atlas', category='ai', max_results=5)
        """
        query: Optional[str] = params.get("query")
        category: Optional[str] = params.get("category")
        try:
            max_results = max(1, min(int(params.get("max_results", 3)), 10))
        except (TypeError, ValueError):
            max_results = 3

        if not query or not query.strip():
            return {"success": False, "error": "query parameter is required"}

        data_path = _videos_path()
        if not data_path.exists():
            return {"success": False, "error": f"videos.json not found at {data_path}"}

        try:
            data = json.loads(data_path.read_text(encoding="utf-8"))
        except Exception as e:
            return {"success": False, "error": f"failed to read videos.json: {e}"}

        videos: List[Dict[str, Any]] = data.get("videos") or []
        q_norm = _normalize(query)
        # Word-level fallback so 'fly drone' still matches a video tagged 'flying' + 'tello'.
        # Drop stopwords (so 'the'/'a'/'how' don't match every title) and very short tokens.
        q_words = [
            w for w in re.split(r"[^a-z0-9]+", query.lower())
            if len(w) >= 3 and w not in _STOPWORDS
        ]

        scored: List[Dict[str, Any]] = []
        for v in videos:
            if category:
                cats = v.get("categories") or []
                if category not in cats:
                    continue
            s = _score(v, q_norm, q_words)
            if s <= 0:
                continue
            vid = v.get("id") or ""
            if not _VIDEO_ID_RE.fullmatch(vid or ""):
                continue
            scored.append({
                "id": vid,
                "title": (v.get("title") or "").replace(" | VirtualPyTest", "").strip(),
                "summary": v.get("summary") or "",
                "url": f"https://www.youtube.com/watch?v={vid}",
                "thumb": v.get("thumb") or f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
                "tags": v.get("tags") or [],
                "categories": v.get("categories") or [],
                "added": v.get("added"),
                "score": round(s, 3),
            })

        scored.sort(key=lambda x: (-x["score"], -_recency_key_sortable(x), x["id"]))
        top = scored[:max_results]

        return {
            "success": True,
            "query": query,
            "category": category,
            "total_matched": len(scored),
            "returned": len(top),
            "videos": top,
        }
