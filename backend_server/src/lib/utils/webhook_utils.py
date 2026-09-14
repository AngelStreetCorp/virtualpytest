"""
Webhook callback URL helpers.
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urljoin, urlparse


def _is_absolute_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def resolve_callback_url(raw_callback_url: Optional[str]) -> Optional[str]:
    """
    Resolve callback URL using WEBHOOK_BASE_URL for relative values.

    Rules:
    - absolute http/https URL => returned as-is
    - relative URL => prepend WEBHOOK_BASE_URL if configured and valid
    - invalid / unresolved => None
    """
    if not raw_callback_url:
        return None

    callback_url = raw_callback_url.strip()
    if not callback_url:
        return None

    if _is_absolute_http_url(callback_url):
        return callback_url

    webhook_base = (os.getenv("WEBHOOK_BASE_URL") or "").strip()
    if not _is_absolute_http_url(webhook_base):
        return None

    # Ensure URL join behaves as expected for paths without leading slash.
    base = webhook_base if webhook_base.endswith("/") else f"{webhook_base}/"
    relative = callback_url[1:] if callback_url.startswith("/") else callback_url
    resolved = urljoin(base, relative)
    return resolved if _is_absolute_http_url(resolved) else None

