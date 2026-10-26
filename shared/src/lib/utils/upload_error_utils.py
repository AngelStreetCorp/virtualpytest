"""Safe text for a failed artifact upload (BUG-0770).

The raw storage error carries endpoints, bucket paths and account detail. It lands in run
metadata and in a review pack that people paste into tickets, so only the error code and a
fixed phrase may be stored.
"""
import re

_CODE_RE = re.compile(r'\(([A-Za-z][A-Za-z0-9_.]{2,60})\)|\b([A-Z][A-Za-z0-9]{3,60}(?:Exception|Error|Denied|Mismatch|KeyId|Key|NotFound))\b')
_KEY_REJECTED = ('InvalidAccessKeyId', 'SignatureDoesNotMatch', 'AccessDenied', 'InvalidSecurity',
                 'InvalidToken', 'ExpiredToken', 'Forbidden', 'Unauthorized')
_MAX = 200


def sanitize_upload_error(raw) -> str:
    """Return "<Code>: <fixed phrase>" with no URLs, paths or backticks, at most 200 chars."""
    text = str(raw or '').strip()
    if not text:
        return ''
    code = ''
    m = _CODE_RE.search(text)
    if m:
        code = m.group(1) or m.group(2) or ''
    code = re.sub(r'[^A-Za-z0-9_.]', '', code)
    if any(k.lower() in (code or text).lower() for k in _KEY_REJECTED):
        phrase = 'storage key rejected'
    elif 'not found' in text.lower() or 'nosuch' in text.lower():
        phrase = 'storage target not found'
    else:
        phrase = 'storage upload failed'
    out = f'{code}: {phrase}' if code else phrase
    return out.replace('`', '')[:_MAX]
