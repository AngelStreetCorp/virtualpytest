"""
Report snapshot builder (TASK-49).

Turns one stored test report (``report.html`` plus the images and video it points at) into a
frozen, self-contained copy under ``shared-snapshots/<snapshot_id>/`` in the same bucket:

    shared-snapshots/<id>/report.html      every reference rewritten to ``assets/<n>.<ext>``
    shared-snapshots/<id>/manifest.json    what was copied (never served)
    shared-snapshots/<id>/assets/<n>.<ext> server-side copies of the original objects

What an outside viewer must not, or cannot, open is removed at build time: presigned URLs (they
carry the storage access key id and endpoint), ``/host/`` links (gated host paths), execution
logs / script source / metadata (``script-logs/``), links to the platform itself and the zap / kpi
sub-reports. The visible text stays; the link is replaced by a muted "not included" label.

The page is parsed with regexes over the whole document instead of per attribute: report URLs
live in src/href/poster/srcset, CSS ``url()``, ``onclick`` handlers and JS strings alike, and a
URL that is missed is a leak.
"""

import bisect
import html as html_lib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils

SNAPSHOT_PREFIX_ROOT = 'shared-snapshots/'
MAX_SNAPSHOT_BYTES = 150 * 1024 * 1024  # 100 MB video cap + images
VIDEO_EXTENSIONS = ('.mp4', '.webm', '.mov', '.m4v', '.mkv', '.m3u8', '.ts')
# The only object types a snapshot copies. Assets are served by a redirect to a presigned URL,
# and the presign endpoint can share the app's origin: a copied HTML, SVG or script would run
# there outside the report's sandbox (and a nested report keeps its own unrewritten links).
# Anything else is dropped like a sub-report link.
COPYABLE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp4', '.webm')

# Where a snapshot may copy from: the report's own folder (script-reports/<model>/<folder>/), plus
# the two shared folders every report legitimately points into. Any other key named in a report
# (navigation/, captures/, another snapshot's assets, another team's reports) is neutralised, not
# copied: a report is user-influenced content and must not be able to pull arbitrary objects.
SHARED_COPY_PREFIXES = ('script-screenshots/', 'reference-images/')

# Storage prefixes a report can reference (see cloudflare_utils upload_* helpers).
BARE_PREFIXES = (
    'script-reports', 'script-logs', 'reference-images', 'navigation',
    'zap-reports', 'kpi_measurement', 'script-screenshots', 'restart-reports',
)
# Inside a storage URL path a few more prefixes are safe to recognise; as bare text they are
# ordinary words ("reports/summary"), so the bare scan sticks to BARE_PREFIXES.
KNOWN_PREFIXES = BARE_PREFIXES + ('reports', 'captures', 'thumbnails')
_PREFIX_ALT = '|'.join(re.escape(p) for p in BARE_PREFIXES)

# One scan finds both absolute URLs and bare storage keys. Absolute URLs are matched first
# (left to right), so the key inside a presigned URL is consumed with it.
_TOKEN_RE = re.compile(
    r'https?://(?:(?!&quot;|&#x27;|&#39;|&lt;|&gt;)[^\s"\'<>`\\)])+'
    r'|(?<![\w.\-])/?(?:' + _PREFIX_ALT + r')/[^\s"\'<>`\\)?#]+'
)
_ANCHOR_RE = re.compile(r'<a\b([^>]*)>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r'''\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')''', re.IGNORECASE)
_VIDEO_THUMB_RE = re.compile(
    r'<div\s+class="video-thumbnail".*?</video>\s*<div\s+class="play-overlay"[^>]*>.*?</div>\s*</div>',
    re.IGNORECASE | re.DOTALL,
)
_VIDEO_TAG_RE = re.compile(r'<video\b.*?</video>', re.IGNORECASE | re.DOTALL)
_HLS_SCRIPT_RE = re.compile(r'<script\b[^>]*\bsrc="https?://[^"]*hls[^"]*"[^>]*>\s*</script>', re.IGNORECASE)
_BODY_RE = re.compile(r'<body\b[^>]*>', re.IGNORECASE)
# Leftovers after the structured pass: any remaining token that still names something forbidden.
_LEFTOVER_HOST_RE = re.compile(r'(?:https?://[^\s"\'<>`\\)]*)?/host/[^\s"\'<>`\\)]*')
_LEFTOVER_LOGS_RE = re.compile(r'[^\s"\'<>`\\)]*script-logs/[^\s"\'<>`\\)]*')
_LEFTOVER_AMZ_RE = re.compile(r'[^\s"\'<>`\\)]*X-Amz-[^\s"\'<>`\\)]*')

NOT_INCLUDED_NOTE = (
    '<span style="color:#888;font-size:11px;font-style:italic;"> (not included in the snapshot)</span>'
)
NO_VIDEO_NOTE = (
    '<div style="text-align:center;color:#888;font-style:italic;padding:12px;font-size:12px;">'
    'Video not included in this snapshot</div>'
)
REMOVED_HREF = '#not-included-in-snapshot'


def _result(success: bool, snapshot_id: str, **extra) -> Dict:
    base = {
        'success': success,
        'storage_prefix': f'{SNAPSHOT_PREFIX_ROOT}{snapshot_id}/',
        'size_bytes': 0,
        'assets': [],
        'error': None,
        'error_code': None,
    }
    base.update(extra)
    return base


def _fail(snapshot_id: str, code: str, message: str) -> Dict:
    return _result(False, snapshot_id, error=message, error_code=code)


def _first_segment_key(path: str) -> Optional[str]:
    """Object key inside a URL path: everything from the first known prefix segment on."""
    segments = [s for s in unquote(path or '').split('/') if s != '']
    for i, seg in enumerate(segments):
        if seg in KNOWN_PREFIXES and i < len(segments) - 1:
            return '/'.join(segments[i:])
    return None


def _storage_hosts() -> set:
    hosts = set()
    for name in ('MINIO_PUBLIC_URL', 'MINIO_ENDPOINT', 'MINIO_PRESIGN_ENDPOINT',
                 'CLOUDFLARE_R2_PUBLIC_URL', 'CLOUDFLARE_R2_ENDPOINT'):
        value = (os.environ.get(name) or '').strip()
        if value:
            parsed = urlparse(value if '://' in value else f'//{value}')
            if parsed.netloc:
                hosts.add(parsed.netloc.lower())
    return hosts


def _platform_hosts(extra: Optional[List[str]]) -> set:
    hosts = set()
    for name in ('FRONTEND_URL', 'SERVER_URL', 'BACKEND_SERVER_URL', 'PUBLIC_URL', 'VITE_SERVER_URL'):
        value = (os.environ.get(name) or '').strip()
        if value:
            parsed = urlparse(value if '://' in value else f'//{value}')
            if parsed.netloc:
                hosts.add(parsed.netloc.lower())
    for host in extra or []:
        if host:
            hosts.add(str(host).lower())
    return hosts


def _is_host_path(value: str) -> bool:
    """A gated host path (/host/<name>/...), relative or absolute. Not a storage key that merely
    contains a 'host' folder, like script-screenshots/host/capture_1.jpg."""
    path = urlparse(value).path if value.lower().startswith(('http://', 'https://', '//')) else value
    return path.split('?')[0].startswith('/host/')


def _is_html_key(key: str) -> bool:
    return key.lower().split('?')[0].endswith(('.html', '.htm'))


class _Classifier:
    """Decides what to do with each URL token found in the report."""

    def __init__(self, bucket_name: str, extra_platform_hosts: Optional[List[str]], include_video: bool,
                 report_folder: str = ''):
        self.bucket = (bucket_name or '').strip('/')
        # 'script-reports/<model>/<folder>/' or '' (a report stored too shallow has no own folder).
        folder = (report_folder or '').lstrip('/')
        self.report_folder = folder if folder.endswith('/') and folder.count('/') >= 3 else ''
        self.storage_hosts = _storage_hosts()
        self.platform_hosts = _platform_hosts(extra_platform_hosts)
        self.include_video = include_video

    def storage_key(self, token: str) -> Optional[str]:
        """Storage key if `token` points into our bucket, else None."""
        raw = html_lib.unescape(token)
        if raw.lower().startswith(('http://', 'https://')):
            parsed = urlparse(raw)
            host = parsed.netloc.lower()
            presigned = 'X-Amz-' in (parsed.query or '')
            segments = [s for s in unquote(parsed.path).split('/') if s]
            in_bucket = bool(self.bucket) and self.bucket in segments
            # Only our own storage hosts: a URL that merely has /<bucket>/ in its path on some other
            # host is not ours (and is never copied).
            if host not in self.storage_hosts:
                return None
            if host in self.platform_hosts and not (presigned or in_bucket):
                return None
            key = _first_segment_key(parsed.path)
            if key:
                return key
            if in_bucket:
                idx = segments.index(self.bucket)
                rest = '/'.join(segments[idx + 1:])
                return rest or None
            return '/'.join(segments) if segments else None
        path = raw.split('?')[0].split('#')[0].lstrip('/')
        return unquote(path) or None

    def may_copy(self, key: str) -> bool:
        """Is `key` a place a snapshot is allowed to copy from?"""
        parts = key.split('/')
        if '..' in parts or '.' in parts or '' in parts or '\\' in key:
            return False
        if self.report_folder and key.startswith(self.report_folder):
            return True
        return key.startswith(SHARED_COPY_PREFIXES)

    def action(self, token: str) -> Tuple[str, Optional[str]]:
        """('copy', key) | ('drop', None) | ('skip_video', key) | ('keep', None)."""
        raw = html_lib.unescape(token)
        if _is_host_path(raw):
            return 'drop', None
        key = self.storage_key(token)
        if key is None:
            return 'keep', None
        if key.startswith('script-logs/') or '/script-logs/' in key:
            return 'drop', None
        if key.startswith(('zap-reports/', 'kpi_measurement/')) and _is_html_key(key):
            return 'drop', None
        if not self.may_copy(key):
            return 'drop', None
        if key.lower().endswith(VIDEO_EXTENSIONS) and not self.include_video:
            return 'skip_video', key
        if not key.lower().split('?')[0].endswith(COPYABLE_EXTENSIONS):
            return 'drop', None
        return 'copy', key

    def is_storage_object_url(self, href: str) -> bool:
        """An absolute URL to an object in our bucket (presigned, or under /<bucket>/)."""
        raw = html_lib.unescape(href or '').strip()
        if not raw.lower().startswith(('http://', 'https://')):
            return False
        parsed = urlparse(raw)
        segments = [s for s in unquote(parsed.path).split('/') if s]
        return 'X-Amz-' in (parsed.query or '') or (bool(self.bucket) and self.bucket in segments[:1])

    def is_platform_link(self, href: str) -> bool:
        """An href that leads back into the platform (an outside viewer has no session there)."""
        value = html_lib.unescape(href or '').strip()
        if not value or value.startswith('#'):
            return False
        if value.startswith('//'):
            return urlparse('https:' + value).netloc.lower() in self.platform_hosts
        if value.startswith('/'):
            return True
        if value.lower().startswith(('http://', 'https://')):
            return urlparse(value).netloc.lower() in self.platform_hosts
        return False


# ---------------------------------------------------------------------------
# Where a storage reference may be copied from: attribute values and CSS url() only
# ---------------------------------------------------------------------------

_CONTEXT_RE = re.compile(
    r'(?P<so><script\b(?:"[^"]*"|\'[^\']*\'|[^\'">])*>)(?P<sb>.*?)(?:</script\s*>|\Z)'
    r'|(?P<yo><style\b(?:"[^"]*"|\'[^\']*\'|[^\'">])*>)(?P<yb>.*?)(?:</style\s*>|\Z)'
    r'|(?P<comment><!--.*?(?:-->|\Z))'
    r'|(?P<tag><[A-Za-z](?:"[^"]*"|\'[^\']*\'|[^\'">])*>)',
    re.IGNORECASE | re.DOTALL,
)
_CSS_URL_RE = re.compile(r'url\(\s*(?:"[^"]*"|\'[^\']*\'|[^)]*)\)', re.IGNORECASE)


def _copyable_spans(text: str) -> List[Tuple[int, int]]:
    """Character spans where a storage reference counts as a real reference: inside a tag (an
    attribute value, onclick JSON included) or inside a CSS url(). Plain text nodes, script bodies
    and comments are not in any span, so a URL typed into a step message is never copied."""
    spans: List[Tuple[int, int]] = []
    for m in _CONTEXT_RE.finditer(text):
        if m.group('so') is not None:
            spans.append(m.span('so'))
        elif m.group('yo') is not None:
            spans.append(m.span('yo'))
            body_start = m.start('yb')
            for u in _CSS_URL_RE.finditer(m.group('yb')):
                spans.append((body_start + u.start(), body_start + u.end()))
        elif m.group('tag') is not None:
            spans.append(m.span('tag'))
    return spans


# ---------------------------------------------------------------------------
# Action parameters that can carry secrets
# ---------------------------------------------------------------------------

MASK = '•••'
# Not `key`: press_key(key='OK') is a remote key press, the substance of an STB report.
_SECRET_PARAM_NAMES = ('text', 'password', 'passwd', 'pin', 'code', 'token', 'secret', 'value',
                       'api_key', 'apikey')
_URL_PARAM_NAMES = ('url', 'href')
_SECRET_NAME = '(?:' + '|'.join(_SECRET_PARAM_NAMES) + ')'
_URL_NAME = '(?:' + '|'.join(_URL_PARAM_NAMES) + ')'
_Q = r"(?:&#x27;|&#39;|')"          # a quote as report_step_formatter emits it (raw or escaped)
_DQ = r'(?:&quot;|")'
# name='value' / name=&#x27;value&#x27;: the value runs to the quote followed by ", next=", ")" or
# the end of the markup (a value may itself contain an apostrophe).
_PY_END = r"(?=,\s*[A-Za-z_]\w*\s*=|\)|\s*<|\s*$)"
_JSON_VALUE = r'((?:\\&quot;|\\"|\\\\|[^"&\\]|&(?!quot;))*)'


def _param_patterns(names: str):
    py = re.compile(r'(?<![\w-])(' + names + r')(=)(' + _Q + r')(.*?)(' + _Q + r')' + _PY_END,
                    re.IGNORECASE | re.MULTILINE)
    js = re.compile(r'(' + _DQ + r')(' + names + r')(' + _DQ + r')(\s*:\s*)(' + _DQ + r')'
                    + _JSON_VALUE + r'(' + _DQ + r')', re.IGNORECASE)
    return py, js


_SECRET_PY, _SECRET_JSON = _param_patterns(_SECRET_NAME)
_URL_PY, _URL_JSON = _param_patterns(_URL_NAME)


def _strip_query(value: str) -> str:
    """scheme + host + path of a URL; query string and fragment can carry tokens."""
    raw = html_lib.unescape(value)
    if not raw.lower().startswith(('http://', 'https://')):
        return value
    cut = min([i for i in (raw.find('?'), raw.find('#')) if i >= 0] or [len(raw)])
    return html_lib.escape(raw[:cut], quote=False) if '&' in value else raw[:cut]


def mask_sensitive_parameters(text: str) -> str:
    """Hide what an action parameter typed or sent: the value of text / password / PIN / token /
    key-like parameters becomes bullets, and url / href parameters lose their query string."""
    text = _SECRET_PY.sub(lambda m: f'{m.group(1)}={m.group(3)}{MASK}{m.group(5)}', text)
    text = _SECRET_JSON.sub(
        lambda m: f'{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{m.group(5)}{MASK}{m.group(7)}', text)
    text = _URL_PY.sub(lambda m: f'{m.group(1)}={m.group(3)}{_strip_query(m.group(4))}{m.group(5)}', text)
    text = _URL_JSON.sub(
        lambda m: f'{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{m.group(5)}'
                  f'{_strip_query(m.group(6))}{m.group(7)}', text)
    return text


def _ext_of(key: str) -> str:
    base = key.rsplit('/', 1)[-1].lower()
    ext = base.rsplit('.', 1)[-1] if '.' in base else ''
    ext = re.sub(r'[^a-z0-9]', '', ext)[:5]
    return ext or 'bin'


def _strip_anchor(match, classifier: _Classifier) -> str:
    attrs, inner = match.group(1), match.group(2)
    href_match = _HREF_RE.search(attrs)
    href = (href_match.group(1) if href_match and href_match.group(1) is not None
            else (href_match.group(2) if href_match else '')) or ''
    if not href:
        return match.group(0)
    unescaped = html_lib.unescape(href)
    # The storage host can be the platform host (one public domain for both): a presigned object
    # link is a storage link, copied below, not a link back into the platform.
    removed = classifier.is_platform_link(href) and not classifier.is_storage_object_url(href)
    if not removed:
        for tok in _TOKEN_RE.findall(unescaped):
            if classifier.action(tok)[0] == 'drop':
                removed = True
                break
    if _is_host_path(unescaped.strip()):
        removed = True
    if removed:
        # One element, not two: inside the report's link grid (icon | label | link) a second
        # sibling would take a cell of its own and shift every row after it.
        return f'<span class="snapshot-removed-link">{inner}{NOT_INCLUDED_NOTE}</span>'
    return match.group(0)


_SHARE_BUTTON_RE = re.compile(r'<a\b[^>]*\breport-share-btn\b[^>]*>.*?</a>', re.IGNORECASE | re.DOTALL)


def rewrite_report_html(report_html: str, classifier: _Classifier) -> Tuple[str, Dict[str, str]]:
    """Return (html with every storage reference rewritten, {key: asset_name}).

    Asset names are assigned in first-seen order and are not yet copied; a key whose copy later
    fails is a build error, never a dangling reference.
    """
    # 0. Typed values (text, PIN, password, token...) and URL query strings in action parameters.
    text = mask_sensitive_parameters(report_html)

    # The report's own Share button leads back into the platform: gone, not "not included".
    text = _SHARE_BUTTON_RE.sub('', text)

    # 1. Links that must go entirely (platform, /host/, logs, sub-reports): keep text, drop href.
    text = _ANCHOR_RE.sub(lambda m: _strip_anchor(m, classifier), text)
    text = _HLS_SCRIPT_RE.sub('', text)  # third-party player script; snapshots only carry mp4

    # 2. Video excluded: replace the players before their URLs are looked at.
    if not classifier.include_video:
        text = _VIDEO_THUMB_RE.sub(NO_VIDEO_NOTE, text)
        text = _VIDEO_TAG_RE.sub(NO_VIDEO_NOTE, text)

    # 3. Every remaining storage token -> assets/<n>.<ext>, or neutralised.
    names: Dict[str, str] = {}
    spans = _copyable_spans(text)
    span_starts = [a for a, _ in spans]

    def in_reference_context(pos: int) -> bool:
        # Spans are disjoint and in document order.
        i = bisect.bisect_right(span_starts, pos) - 1
        return i >= 0 and pos < spans[i][1]

    def replace(match) -> str:
        token = match.group(0)
        action, key = classifier.action(token)
        if action == 'keep':
            return token
        if action in ('drop', 'skip_video'):
            return REMOVED_HREF
        if not in_reference_context(match.start()):
            return REMOVED_HREF  # a storage name in plain text or a script is text, not a reference
        if key not in names:
            names[key] = f'{len(names) + 1}.{_ext_of(key)}'
        return f'assets/{names[key]}'

    text = _TOKEN_RE.sub(replace, text)

    # 4. Belt and braces: nothing forbidden may survive in any form.
    text = _LEFTOVER_HOST_RE.sub(REMOVED_HREF, text)
    text = _LEFTOVER_LOGS_RE.sub(REMOVED_HREF, text)
    text = _LEFTOVER_AMZ_RE.sub(REMOVED_HREF, text)
    return text, names


def _inject_banner(page: str, banner_text: str) -> str:
    banner = (
        # Palette banner: the report's own variables (script report, then generated pages), with the
        # light palette as the last fallback for older reports that define neither.
        '<div id="snapshot-banner" style="position:sticky;top:0;z-index:99999;'
        'background:var(--bg-tertiary, var(--vpt-subtle, #ebe7e0));color:var(--text-primary, var(--vpt-text, #141414));'
        'border-bottom:1px solid var(--border-color, var(--vpt-border, #d9d4cc));padding:8px 16px;font:13px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;'
        'text-align:center;">' + html_lib.escape(banner_text or 'Shared report snapshot') + '</div>'
    )
    match = _BODY_RE.search(page)
    if match:
        return page[:match.end()] + banner + page[match.end():]
    return banner + page


def _head_total(cu, keys: List[str]) -> Tuple[Dict[str, int], List[str]]:
    sizes: Dict[str, int] = {}
    missing: List[str] = []
    for key in keys:
        head = cu.head_file(key)
        if head.get('success'):
            sizes[key] = int(head.get('content_length') or 0)
        else:
            missing.append(key)
    return sizes, missing


def build_snapshot(report_r2_path: str, snapshot_id: str, include_video: bool, banner_text: str,
                   platform_hosts: Optional[List[str]] = None, quota_left_bytes: Optional[int] = None) -> Dict:
    """Build the frozen copy. Returns {success, storage_prefix, size_bytes, assets, error, error_code}.

    error_code: 'report_gone' (report.html missing), 'too_large' (> 150 MB, checked before any
    copy), 'quota' (more than quota_left_bytes, the team's remaining snapshot quota, also checked
    before any copy), 'storage_error' (anything else). On failure after objects were written the prefix is
    cleaned up.
    """
    prefix = f'{SNAPSHOT_PREFIX_ROOT}{snapshot_id}/'
    try:
        cu = get_cloudflare_utils()
    except Exception as e:
        return _fail(snapshot_id, 'storage_error', f'Storage not available: {e}')

    report_key = cu.resolve_remote_path(report_r2_path) if report_r2_path else ''
    if not report_key:
        return _fail(snapshot_id, 'report_gone', 'The report has no stored page')

    tmp_dir = tempfile.mkdtemp(prefix='vpt_snapshot_')
    wrote_objects = False
    try:
        local_report = os.path.join(tmp_dir, 'source_report.html')
        dl = cu.download_file(report_key, local_report)
        if not dl.get('success'):
            err = str(dl.get('error') or '')
            if 'not found' in err.lower() or 'nosuchkey' in err.lower():
                return _fail(snapshot_id, 'report_gone', 'The report page no longer exists in storage')
            return _fail(snapshot_id, 'storage_error', f'Could not read the report: {err}')
        with open(local_report, 'r', encoding='utf-8', errors='replace') as f:
            source_html = f.read()

        report_folder = report_key.rsplit('/', 1)[0] + '/' if '/' in report_key else ''
        classifier = _Classifier(getattr(cu, 'bucket_name', ''), platform_hosts, include_video, report_folder)
        rewritten, names = rewrite_report_html(source_html, classifier)

        # Size gate BEFORE copying anything. A reference whose object is gone (a screenshot
        # already past the 14-day lifecycle) is not fatal: it is neutralised in the page.
        sizes, missing = _head_total(cu, list(names.keys()))
        total = sum(sizes.values()) + len(rewritten.encode('utf-8'))
        if total > MAX_SNAPSHOT_BYTES:
            mb = total / (1024 * 1024)
            return _fail(snapshot_id, 'too_large',
                         f'Snapshot would be {mb:.0f} MB, the limit is {MAX_SNAPSHOT_BYTES // (1024 * 1024)} MB')
        if quota_left_bytes is not None and total > quota_left_bytes:
            return _fail(snapshot_id, 'quota',
                         f'Snapshot would be {total / (1024 * 1024):.0f} MB, the team has '
                         f'{max(quota_left_bytes, 0) / (1024 * 1024):.0f} MB of snapshot quota left; '
                         'revoke an old link first')
        for key in missing:
            rewritten = re.sub(re.escape(f'assets/{names[key]}') + r'(?![A-Za-z0-9])', REMOVED_HREF, rewritten)
            del names[key]

        assets = []
        for key, name in names.items():
            copied = cu.copy_file(key, f'{prefix}assets/{name}')
            wrote_objects = True
            if not copied.get('success'):
                raise RuntimeError(f"copy failed for {key}: {copied.get('error')}")
            assets.append({'name': name, 'source_key': key, 'size': sizes.get(key, 0)})

        page = _inject_banner(rewritten, banner_text)
        manifest = {
            'snapshot_id': snapshot_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'include_video': bool(include_video),
            'assets': assets,
            'missing_sources': missing,
        }
        local_page = os.path.join(tmp_dir, 'report.html')
        local_manifest = os.path.join(tmp_dir, 'manifest.json')
        with open(local_page, 'w', encoding='utf-8') as f:
            f.write(page)
        with open(local_manifest, 'w', encoding='utf-8') as f:
            json.dump(manifest, f)
        wrote_objects = True
        up = cu.upload_files([
            {'local_path': local_page, 'remote_path': f'{prefix}report.html',
             'content_type': 'text/html; charset=utf-8'},
            {'local_path': local_manifest, 'remote_path': f'{prefix}manifest.json',
             'content_type': 'application/json'},
        ])
        if not up.get('success'):
            raise RuntimeError(f"upload failed: {up.get('failed_uploads')}")

        size_bytes = sum(a['size'] for a in assets) + len(page.encode('utf-8'))
        print(f"[@snapshot_builder:build_snapshot] {prefix}: {len(assets)} assets, {size_bytes} bytes")
        return _result(True, snapshot_id, size_bytes=size_bytes, assets=assets)
    except Exception as e:
        print(f"[@snapshot_builder:build_snapshot] failed for {prefix}: {e}")
        if wrote_objects:
            try:
                cu.delete_prefix(prefix)
            except Exception as cleanup_error:
                print(f"[@snapshot_builder:build_snapshot] cleanup failed for {prefix}: {cleanup_error}")
        return _fail(snapshot_id, 'storage_error', str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def purge_snapshot(storage_prefix: str) -> bool:
    """Delete every object under a snapshot prefix. Refuses anything outside shared-snapshots/."""
    prefix = (storage_prefix or '').lstrip('/')
    if not prefix.startswith(SNAPSHOT_PREFIX_ROOT) or prefix == SNAPSHOT_PREFIX_ROOT or '..' in prefix:
        print(f"[@snapshot_builder:purge_snapshot] refusing prefix {storage_prefix!r}")
        return False
    if not prefix.endswith('/'):
        prefix += '/'
    result = get_cloudflare_utils().delete_prefix(prefix)
    return bool(result.get('success'))
