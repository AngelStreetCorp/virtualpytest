#!/usr/bin/env python3
"""hls_pick_720p.py — local HLS master-playlist inspector used by pick_720p_variants.sh.

Reads TSV rows of (device_index<TAB>device_name<TAB>source_url) on stdin and
emits TSV rows of (device_index<TAB>device_name<TAB>chosen_url_or_reason).

Reasons (column 4):
  OK             — picked the 1280x720 variant from the master; column 3 is the new URL
  ALREADY_720P   — the source URL already resolves to a 1280x720 playlist; left alone
  NO_MASTER      — the source is not a master playlist (single-variant, SMIL, raw media)
  NO_720P        — the master exposes variants, but none at 1280x720
  FETCH_ERROR    — could not fetch the master; column 3 is the error text

This runs on the operator's machine, not on the host (no Python on the host is
required). Pure stdlib, no third-party deps.
"""
import ssl
import sys
import urllib.parse
import urllib.request

try:
    import certifi  # type: ignore
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    # No certifi — fall back to the system default context (works on Linux
    # with /etc/ssl/certs, fails on stock macOS Python). The /opt/homebrew
    # and pyenv builds usually ship certifi already.
    _SSL_CTX = ssl.create_default_context()

RESOLUTION = "1280x720"


def fetch(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "vpt-pick-720p/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        return r.read().decode("utf-8", errors="ignore")


def find_720p(master_url):
    """Return (chosen_url, reason). chosen_url is None when reason != OK / ALREADY_720P."""
    try:
        content = fetch(master_url)
    except Exception as exc:
        return None, "FETCH_ERROR", str(exc)

    lines = [l.strip() for l in content.splitlines() if l.strip()]
    has_stream_inf = any(l.startswith("#EXT-X-STREAM-INF") for l in lines)
    if not has_stream_inf:
        # Could be a media playlist (no variants) or a non-HLS response.
        return None, "NO_MASTER", None

    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        if f"RESOLUTION={RESOLUTION}" not in line:
            continue
        # The variant URI is the first non-comment line after this STREAM-INF.
        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if nxt.startswith("#"):
                continue
            chosen = nxt if nxt.startswith(("http://", "https://")) else urllib.parse.urljoin(master_url, nxt)
            return chosen, "OK", None

    return None, "NO_720P", None


def looks_already_720p(url):
    """If the URL itself (or the playlist it points to) already declares 1280x720 in a
    STREAM-INF line, treat it as already-720p and leave it alone. Cheap check that
    avoids rewriting DEVICE<N>_VIDEO that someone hand-pointed at the 720p variant
    already."""
    try:
        content = fetch(url, timeout=8)
    except Exception:
        return False
    for line in content.splitlines():
        if line.startswith("#EXT-X-STREAM-INF") and f"RESOLUTION={RESOLUTION}" in line:
            return True
        if line.startswith("#EXT-X-MEDIA"):
            continue
    return False


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--tsv":
        mode = "tsv"
    else:
        mode = "url"
        for url in sys.argv[1:]:
            chosen, reason, err = find_720p(url)
            if reason == "OK":
                print(chosen)
            elif err:
                print(f"{reason}: {err}", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"{reason}: {url}", file=sys.stderr)
                sys.exit(2)
        return

    for raw in sys.stdin:
        raw = raw.rstrip("\n")
        if not raw:
            continue
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        idx, name, url = parts[0], parts[1], parts[2]
        chosen, reason, err = find_720p(url)
        # \x1f (Unit Separator) is the field delimiter. Bash's `read -r` with
        # IFS=$'\x1f' preserves empty fields and treats it as a single
        # character. URLs never contain it, names never contain it, and the
        # reason vocabulary is fixed.
        if reason == "OK":
            print(f"{idx}\x1f{name}\x1f{chosen}\x1fOK")
        elif reason == "FETCH_ERROR":
            print(f"{idx}\x1f{name}\x1f{err or ''}\x1fFETCH_ERROR")
        elif reason == "NO_MASTER":
            print(f"{idx}\x1f{name}\x1f\x1fNO_MASTER")
        elif reason == "NO_720P":
            if looks_already_720p(url):
                print(f"{idx}\x1f{name}\x1f\x1fALREADY_720P")
            else:
                print(f"{idx}\x1f{name}\x1f\x1fNO_720P")


if __name__ == "__main__":
    main()