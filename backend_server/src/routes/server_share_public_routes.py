"""
Public Share Routes (TASK-49) - the viewer for one shared report snapshot. No user account.

GET  /server/share/<key>                      301 -> /server/share/<key>/
GET  /server/share/<key>/                      the report (or the unlock form / 404 / 410)
GET  /server/share/<key>/assets/<n>.<ext>      302 -> 1 h presigned URL of the copied object
POST /server/share/<key>/unlock                password form -> signed cookie -> 303 ./
GET  /server/share/delete/<delete_key>         confirm page
POST /server/share/delete/<delete_key>         revoke

Authentication: the 128-bit URL key (only its SHA-256 is stored) plus, when set, a password
cookie. The path is listed in UNAUTHENTICATED_SERVER_PREFIXES in app.py for that reason.

Security notes (see docs/tasks/TASK-49-report-share-snapshot.md section 4):
- The snapshot HTML is served from the app's own origin. It carries `Content-Security-Policy:
  sandbox allow-scripts ...` WITHOUT allow-same-origin, so its scripts run in an opaque origin and
  cannot read a logged-in viewer's session storage. Do not add allow-same-origin.
- Because the page is sandboxed, its asset requests are cross-site. Browsers that block
  third-party cookies (Safari, strict Chrome) never send the unlock cookie with them, so on a
  password-protected link every asset reference in the served HTML carries its own signed
  token (`?t=`), minted only after the cookie was checked. The cookie still gates the page.
- The row is looked up by the key alone; nothing here trusts a team_id from the request.
"""

import hashlib
import hmac
import html as html_lib
import os
import re
import secrets
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from flask import Blueprint, Response, request
from werkzeug.security import check_password_hash

from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.routes.server_report_snapshots_routes import purge_now
from shared.src.lib.database import report_snapshots_db
from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
from shared.src.lib.utils.report_theme import report_theme_head

server_share_public_bp = Blueprint('server_share_public', __name__, url_prefix='/server/share')

KEY_RE = re.compile(r'^[A-Za-z0-9_-]{16,64}$')
# Same whitelist as report_snapshot_builder.COPYABLE_EXTENSIONS: never redirect to an HTML/SVG/JS
# object, the presign endpoint can share the app's origin.
ASSET_NAME_RE = re.compile(r'^[0-9]+\.(?:jpg|jpeg|png|webp|gif|mp4|webm)$')
COOKIE_NAME = 'vpt_share_unlock'
COOKIE_MAX_AGE = 12 * 3600
ASSET_PRESIGN_SECONDS = 3600

# Unlock attempts: (max attempts, window seconds). Per client IP, and per link.
IP_LIMIT = (5, 60)
KEY_LIMIT = (20, 3600)
_rate_lock = threading.Lock()
RATE_BUCKET_CAP = 10000
_rate_buckets: 'OrderedDict[str, deque]' = OrderedDict()

# Used only when the server has none of the usual secrets; cookies then die on restart.
_fallback_secret = secrets.token_bytes(32)

PAGE_CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
# No allow-popups-to-escape-sandbox: a window the report opens stays sandboxed too.
REPORT_CSP = "sandbox allow-scripts allow-popups; frame-ancestors 'none'"

_PAGE_STYLE = (
    'body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--vpt-page);color:var(--vpt-text);'
    'display:flex;justify-content:center;padding:15vh 16px}main{background:var(--vpt-surface);border-radius:8px;'
    'padding:28px 32px;max-width:380px;width:100%;box-shadow:var(--vpt-shadow);border:1px solid var(--vpt-border)}'
    'h1{font-size:18px;margin:0 0 12px}p{margin:0 0 16px;color:var(--vpt-text-2)}'
    'input{width:100%;box-sizing:border-box;padding:8px;margin:0 0 12px;font-size:15px;'
    'background:var(--vpt-surface);color:var(--vpt-text);border:1px solid var(--vpt-border);border-radius:4px}'
    'button{padding:8px 18px;font-size:15px;cursor:pointer;background:var(--vpt-accent);color:var(--vpt-on-accent);'
    'border:1px solid var(--vpt-accent);border-radius:4px}.err{color:var(--vpt-error)}'
)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

@server_share_public_bp.after_request
def _security_headers(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def _page(title: str, body_html: str, status: int = 200) -> Response:
    doc = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        f'{report_theme_head()}<title>{html_lib.escape(title)}</title><style>{_PAGE_STYLE}</style></head>'
        f'<body><main>{body_html}</main></body></html>'
    )
    response = Response(doc, status=status, mimetype='text/html')
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Content-Security-Policy'] = PAGE_CSP
    return response


def _not_found() -> Response:
    return _page('Not found', '<h1>Not found</h1><p>This link does not exist.</p>', 404)


def _gone() -> Response:
    return _page('Link expired', '<h1>This shared report has expired or was revoked</h1>'
                 '<p>Ask the person who sent you the link for a new one.</p>', 410)


def _unlock_form(error: Optional[str] = None, status: int = 200) -> Response:
    err = f'<p class="err">{html_lib.escape(error)}</p>' if error else ''
    body = (
        '<h1>This report is password protected</h1>' + err +
        '<form method="post" action="unlock">'
        '<input type="password" name="password" placeholder="Password" autocomplete="off" '
        'autofocus required maxlength="200"><button type="submit">Open report</button></form>'
    )
    return _page('Password required', body, status)


# ---------------------------------------------------------------------------
# Lookup, expiry, cookie, rate limit
# ---------------------------------------------------------------------------

def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _sharing_enabled() -> bool:
    return (os.getenv('REPORT_SHARING_ENABLED') or '').strip().lower() in ('1', 'true', 'yes')


def _this_server_name() -> str:
    return (os.getenv('SERVER_NAME') or '').strip()


def _parse_time(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace('Z', '+00:00')
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            # Postgres can emit 5 fractional digits, which fromisoformat rejects before 3.11.7.
            match = re.match(r'^(.*?\.)(\d{1,6})\d*(.*)$', text)
            if not match:
                return None
            try:
                parsed = datetime.fromisoformat(f'{match.group(1)}{match.group(2).ljust(6, "0")}{match.group(3)}')
            except ValueError:
                return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_live(row: dict) -> bool:
    if row.get('revoked_at') or row.get('purged_at'):
        return False
    expires_at = _parse_time(row.get('expires_at'))
    return expires_at is not None and expires_at > datetime.now(timezone.utc)


def _resolve(key: str) -> Tuple[Optional[dict], Optional[Response]]:
    """Row for a URL key, or the response that ends the request (404 unknown / other server, 410 dead)."""
    # Kill switch: turning REPORT_SHARING_ENABLED off closes every existing link too.
    if not KEY_RE.match(key or '') or not _sharing_enabled():
        return None, _not_found()
    key_hash = _sha256(key)
    row = report_snapshots_db.get_snapshot_by_key_hash(key_hash)
    if not row:
        return None, _not_found()
    row = dict(row, key_hash=key_hash)
    server_name = _this_server_name()
    if not server_name or row.get('server_name') != server_name:
        # The objects live in another server's storage; this server cannot serve it.
        return None, _not_found()
    if not _is_live(row):
        return None, _gone()
    return row, None


def _cookie_secret() -> bytes:
    # Same fallback chain as the host-session cookie; no new required env var.
    secret = (os.getenv('HOST_SESSION_SECRET') or os.getenv('SUPABASE_JWT_SECRET')
              or os.getenv('FLASK_SECRET_KEY') or '')
    base = secret.encode('utf-8') if secret else _fallback_secret
    return hashlib.sha256(b'report-share-unlock|' + base).digest()


def _sign(key_hash: str, expires: int) -> str:
    mac = hmac.new(_cookie_secret(), f'{key_hash}|{expires}'.encode('utf-8'), hashlib.sha256).hexdigest()
    return f'{expires}.{mac}'


def _has_valid_unlock_cookie(row: dict) -> bool:
    value = request.cookies.get(COOKIE_NAME, '')
    expires_text, _, mac = value.partition('.')
    if not expires_text.isdigit() or not mac:
        return False
    expires = int(expires_text)
    if expires < time.time():
        return False
    return hmac.compare_digest(_sign(row['key_hash'], expires), value)


def _asset_token(key_hash: str, name: str, expires: int) -> str:
    mac = hmac.new(_cookie_secret(), f'asset|{key_hash}|{name}|{expires}'.encode('utf-8'),
                   hashlib.sha256).hexdigest()
    return f'{expires}.{mac}'


def _has_valid_asset_token(row: dict, name: str) -> bool:
    value = request.args.get('t', '')
    expires_text, _, mac = value.partition('.')
    if not expires_text.isdigit() or not mac or int(expires_text) < time.time():
        return False
    return hmac.compare_digest(_asset_token(row['key_hash'], name, int(expires_text)), value)


_ASSET_REF_RE = re.compile(r'(?<![\w/.-])assets/([0-9]+\.[a-z0-9]{1,5})(?![\w.?])')


def _with_asset_tokens(page_html: str, row: dict) -> str:
    """Append a signed token to every assets/<n>.<ext> reference (password-protected links)."""
    expires = int(time.time()) + COOKIE_MAX_AGE
    return _ASSET_REF_RE.sub(
        lambda m: f"assets/{m.group(1)}?t={_asset_token(row['key_hash'], m.group(1), expires)}",
        page_html)


_HEAD_RE = re.compile(r'<head\b[^>]*>', re.IGNORECASE)
_REFERRER_META = '<meta name="referrer" content="no-referrer">'


def _with_referrer_meta(page_html: str) -> str:
    """The proxy appends its own Referrer-Policy header after ours, and a browser applies the last
    one, so the policy also goes in the page, where a <meta> wins over the header."""
    match = _HEAD_RE.search(page_html)
    if not match:
        return _REFERRER_META + page_html
    return page_html[:match.end()] + _REFERRER_META + page_html[match.end():]


def _gate(key: str) -> Tuple[Optional[dict], Optional[Response]]:
    """Lookup plus the password check shared by the page and its assets."""
    row, response = _resolve(key)
    if response is not None:
        return None, response
    if row.get('password_hash') and not _has_valid_unlock_cookie(row):
        return None, _unlock_form()
    return row, None


def _client_ip() -> str:
    """The proxy chain's own header, never the first X-Forwarded-For entry (a client can send
    that one itself): CF-Connecting-IP when behind Cloudflare, else X-Real-IP, else the socket."""
    for header in ('CF-Connecting-IP', 'X-Real-IP'):
        value = (request.headers.get(header) or '').strip()
        if value:
            return value[:64]
    return request.remote_addr or 'unknown'


def _rate_limited(bucket_key: str, limit: Tuple[int, int]) -> bool:
    """Sliding window, in-process (same style as /server/public/ask). True = refuse."""
    max_attempts, window = limit
    now = time.time()
    with _rate_lock:
        bucket = _rate_buckets.get(bucket_key)
        if bucket is None:
            bucket = _rate_buckets[bucket_key] = deque()
            while len(_rate_buckets) > RATE_BUCKET_CAP:
                _rate_buckets.popitem(last=False)  # oldest bucket first, O(1)
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= max_attempts:
            return True
        bucket.append(now)
    return False


# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------

@server_share_public_bp.route('/<key>', methods=['GET'])
@handle_route_exceptions('share:redirect')
def share_redirect(key):
    if not KEY_RE.match(key):
        return _not_found()
    # Relative asset links (assets/1.jpg) only resolve under a trailing slash.
    response = Response(status=301)
    response.headers['Location'] = f'/server/share/{key}/'
    return response


@server_share_public_bp.route('/<key>/', methods=['GET'])
@handle_route_exceptions('share:view')
def share_view(key):
    row, response = _gate(key)
    if response is not None:
        return response
    fetched = get_cloudflare_utils().read_text_file(f"{row['storage_prefix']}report.html")
    if not fetched.get('success'):
        print(f"[@route:share:view] report.html unreadable for {row.get('id')}: {fetched.get('error')}")
        return _gone()
    try:
        report_snapshots_db.record_view(row['id'])
    except Exception as e:
        print(f"[@route:share:view] record_view failed: {e}")
    page_html = _with_referrer_meta(fetched['text'])
    if row.get('password_hash'):
        page_html = _with_asset_tokens(page_html, row)
    page = Response(page_html, mimetype='text/html')
    page.headers['Content-Type'] = 'text/html; charset=utf-8'
    # No allow-same-origin on purpose: report content must not reach the viewer's own session.
    page.headers['Content-Security-Policy'] = REPORT_CSP
    return page


@server_share_public_bp.route('/<key>/assets/<name>', methods=['GET'])
@handle_route_exceptions('share:asset')
def share_asset(key, name):
    if not ASSET_NAME_RE.match(name):
        return _not_found()
    row, response = _resolve(key)
    if response is not None:
        return response
    if row.get('password_hash') and not (_has_valid_asset_token(row, name) or _has_valid_unlock_cookie(row)):
        return Response(status=401)
    signed = get_cloudflare_utils().generate_presigned_url(
        f"{row['storage_prefix']}assets/{name}", ASSET_PRESIGN_SECONDS)
    if not signed.get('success') or not signed.get('url'):
        return _not_found()
    redirect = Response(status=302)
    redirect.headers['Location'] = signed['url']
    return redirect


@server_share_public_bp.route('/<key>/unlock', methods=['POST'])
@handle_route_exceptions('share:unlock')
def share_unlock(key):
    row, response = _resolve(key)
    if response is not None:
        return response
    if not row.get('password_hash'):
        redirect = Response(status=303)
        redirect.headers['Location'] = './'
        return redirect

    # Per-link bucket first: a flood from many addresses at one link is refused before it can
    # create a bucket per address.
    if (_rate_limited(f"key:{row['key_hash']}", KEY_LIMIT)
            or _rate_limited(f'ip:{_client_ip()}', IP_LIMIT)):
        return _page('Too many attempts', '<h1>Too many attempts</h1><p>Wait a minute and try again.</p>', 429)

    password = request.form.get('password') or ''
    if not password or len(password) > 200 or not check_password_hash(row['password_hash'], password):
        print(f"[@route:share:unlock] wrong password for {row.get('id')}")
        return _unlock_form('Wrong password.', 401)

    expires = int(time.time()) + COOKIE_MAX_AGE
    redirect = Response(status=303)
    redirect.headers['Location'] = './'
    redirect.set_cookie(
        COOKIE_NAME, _sign(row['key_hash'], expires),
        max_age=COOKIE_MAX_AGE, path=f'/server/share/{key}/',
        httponly=True, secure=True, samesite='None',
    )
    return redirect


# ---------------------------------------------------------------------------
# Delete link (Grafana-style, no login)
# ---------------------------------------------------------------------------

def _delete_row(delete_key: str) -> Optional[dict]:
    # The delete link keeps working while sharing is off: revoking is always allowed.
    if not KEY_RE.match(delete_key or ''):
        return None
    return report_snapshots_db.get_snapshot_by_delete_key_hash(_sha256(delete_key))


@server_share_public_bp.route('/delete/<delete_key>', methods=['GET'])
@handle_route_exceptions('share:delete_confirm')
def share_delete_confirm(delete_key):
    row = _delete_row(delete_key)
    if not row:
        return _not_found()
    if row.get('revoked_at'):
        return _page('Already revoked', '<h1>Link revoked</h1><p>This link was already revoked.</p>')
    return _page('Revoke link', (
        '<h1>Revoke this shared report?</h1><p>Anyone holding the link will lose access.</p>'
        '<form method="post"><button type="submit">Revoke link</button></form>'
    ))


@server_share_public_bp.route('/delete/<delete_key>', methods=['POST'])
@handle_route_exceptions('share:delete')
def share_delete(delete_key):
    row = _delete_row(delete_key)
    if not row:
        return _not_found()
    if not row.get('revoked_at'):
        if report_snapshots_db.revoke_snapshot_by_id(row['id']):
            purge_now(row)
        print(f"[@route:share:delete] revoked {row['id']} by delete link")
    return _page('Link revoked', '<h1>Link revoked</h1><p>The shared report is no longer available.</p>')
