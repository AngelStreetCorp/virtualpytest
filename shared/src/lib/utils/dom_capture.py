#!/usr/bin/env python3
"""Centralized per-execution DOM capture for web (Playwright) scripts.

Purpose: when a page's frontend DOM changes, script failures get blamed on the
script. Capturing the DOM of every navigated page per execution gives an
auditable artifact to compare across runs (like execution.txt for logs).

Capture policy: one DOM file per distinct page, keyed by normalized URL and
deduplicated by content hash — a page already captured is only re-captured
when what is displayed actually differs (hash changed).

State is process-global: one script execution == one process on every web
path (decorated scripts, local-debug CLI, and the in-process web controller),
so report generators can pull the captured files without any plumbing through
scripts. Capture never raises — a DOM failure must not fail a test step.
"""

import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit


def _slugify(value: str, max_length: int = 60) -> str:
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', value or '').strip('_').lower()
    return slug[:max_length] or 'page'


def page_name_from_url(url: str) -> str:
    """Derive a stable capture name from a URL (host + path)."""
    try:
        parts = urlsplit(url or '')
        return _slugify(f"{parts.netloc}{parts.path}")
    except Exception:
        return 'page'


def _strip_dom_noise(html: str) -> str:
    """Reduce a serialized DOM to what is displayed: drop script/style payloads
    (typically ~90% of app pages, and full of per-load nonces that would defeat
    the changed-content hash), then put each tag on its own line so two
    executions can be line-diffed."""
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.S | re.I)
    html = re.sub(r'<style\b[^>]*>.*?</style>', '', html, flags=re.S | re.I)
    html = re.sub(r'<noscript\b[^>]*>.*?</noscript>', '', html, flags=re.S | re.I)
    html = re.sub(r'<link\b[^>]*>', '', html, flags=re.I)
    html = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    html = html.replace('><', '>\n<')
    return re.sub(r'\n{3,}', '\n\n', html)


def _normalize_url(url: str) -> str:
    """URL identity for dedupe: drop fragment, keep query, strip trailing slash."""
    try:
        parts = urlsplit(url or '')
        path = parts.path.rstrip('/') or '/'
        normalized = f"{parts.scheme}://{parts.netloc}{path}"
        if parts.query:
            normalized += f"?{parts.query}"
        return normalized
    except Exception:
        return url or ''


class DomCaptureSession:
    """Per-execution DOM capture registry (see module docstring for lifecycle)."""

    def __init__(self):
        # Each capture: {name, title, url, path, sha256, captured_at}
        self.captures: List[Dict[str, Any]] = []
        self._hash_by_url: Dict[str, str] = {}
        self._default_dir: Optional[str] = None

    def default_dir(self) -> str:
        if not self._default_dir:
            self._default_dir = os.path.join(tempfile.gettempdir(), f"vpt_dom_{os.getpid()}")
        return self._default_dir


_session = DomCaptureSession()


async def capture_page_dom(*, page: Any, name: str = '', output_dir: str = '') -> str:
    """Capture the current page DOM if this page state wasn't captured yet.

    Returns the path of the capture representing this page state ('' on
    failure). Dedupe: same normalized URL + same content hash → returns the
    existing file without writing a new one.
    """
    try:
        html = _strip_dom_noise(await page.content())
        url = page.url
        try:
            title = (await page.title() or '').strip()
        except Exception:
            title = ''
        normalized_url = _normalize_url(url)
        digest = hashlib.sha256(html.encode('utf-8', errors='replace')).hexdigest()

        if _session._hash_by_url.get(normalized_url) == digest:
            for capture in _session.captures:
                if capture['sha256'] == digest and _normalize_url(capture['url']) == normalized_url:
                    return capture['path']
            return ''

        dom_dir = os.path.join(output_dir or _session.default_dir(), 'dom')
        os.makedirs(dom_dir, exist_ok=True)

        # Name preference: explicit step name, then page title, then URL slug
        capture_name = _slugify(name) if name else (_slugify(title) if title else page_name_from_url(url))
        captured_at = datetime.now(timezone.utc).isoformat()
        idx = len(_session.captures) + 1
        path = os.path.join(dom_dir, f"{idx:02d}_{capture_name}_dom.txt")

        header = (
            f"<!-- VirtualPyTest DOM capture (scripts/styles stripped) | name: {capture_name} "
            f"| title: {title} | url: {url} | captured_at: {captured_at} | sha256: {digest} -->\n"
        )
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(header)
            f.write(html)

        _session._hash_by_url[normalized_url] = digest
        _session.captures.append({
            'name': capture_name,
            'title': title,
            'url': url,
            'path': path,
            'sha256': digest,
            'captured_at': captured_at,
        })
        print(f"[@dom_capture] Captured DOM #{idx} '{capture_name}' ({len(html)} chars) -> {path}")
        return path
    except Exception as e:
        print(f"[@dom_capture] DOM capture skipped ({name or 'page'}): {e}")
        return ''


def get_dom_captures() -> List[Dict[str, Any]]:
    """All DOM captures recorded by this execution (for report upload/links)."""
    return list(_session.captures)


def reset_dom_captures() -> None:
    _session.captures = []
    _session._hash_by_url = {}
