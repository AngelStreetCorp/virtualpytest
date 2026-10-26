"""Device identity for Localize (TASK-107 goal 4): name the node without pixels when the device can say
where it is.

- android_mobile / android_tablet: the foreground activity (``package/.Activity``), plus the visible
  texts of the UI dump to tell apart screens that share one activity.
- web (and host_vnc when its browser runs): the page URL, plus the title.

A node's identity is stored with its fingerprint (``data.fingerprint.identity``) when its
screenshot is captured, so it rides every fingerprint path (variants, corrections carry-over).
Localize matches the live identity first; pixels decide only when identity does not.

Shape: {kind: 'android'|'web', package?, activity?, texts?, url?, title?}. Pure functions only.
"""
from typing import Any, Dict, Iterable, List, Optional, Tuple
import fnmatch
import re
from urllib.parse import urlsplit

ANDROID_MODELS = ('android_mobile', 'android_tablet')
WEB_MODELS = ('web', 'host_vnc')
MAX_TEXTS = 40
# Two screens of one activity: the texts must agree this much better than the runner-up.
TEXT_MIN_SCORE = 0.35
TEXT_MARGIN = 0.15


def identity_kind(device_model: Optional[str]) -> Optional[str]:
    if device_model in ANDROID_MODELS:
        return 'android'
    if device_model in WEB_MODELS:
        return 'web'
    return None


def parse_activity(dumpsys: str) -> Optional[Tuple[str, str]]:
    """(package, activity) from `dumpsys activity activities` / `dumpsys window` output: the resumed
    activity line (`mResumedActivity` / `topResumedActivity`), else the focused window."""
    lines = (dumpsys or '').splitlines()
    for keys in (('topResumedActivity', 'mResumedActivity', 'ResumedActivity:'), ('mCurrentFocus', 'mFocusedApp')):
        for line in lines:
            if any(k in line for k in keys):
                for tok in line.replace('}', ' ').split():
                    if '/' in tok and '.' in tok.split('/')[0]:
                        pkg, act = tok.split('/', 1)
                        if act.startswith('.'):
                            act = pkg + act
                        return pkg, act
    return None


def normalize_text(s: str) -> str:
    return ' '.join(''.join(ch.lower() if ch.isalnum() else ' ' for ch in (s or '')).split())


def screen_texts(elements: Iterable[Any]) -> List[str]:
    """The visible texts of a UI dump (focused window first), normalised, deduped, capped."""
    out: List[str] = []
    seen = set()
    elems = list(elements)
    focused = [e for e in elems if getattr(e, 'in_focused_window', True)]
    for e in focused or elems:
        for raw in (getattr(e, 'text', ''), getattr(e, 'content_desc', '')):
            t = normalize_text(raw)
            if t and len(t) <= 60 and t not in seen:
                seen.add(t)
                out.append(t)
                if len(out) >= MAX_TEXTS:
                    return out
    return out


def normalize_url(url: Optional[str]) -> Optional[str]:
    """host + path, lower-case host, no query, no trailing slash; a hash route (`#/page`) is kept
    because single-page apps route on it."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    if not parts.netloc and not parts.path:
        return None
    path = parts.path.rstrip('/') or ''
    frag = parts.fragment if parts.fragment.startswith('/') else ''
    frag = frag.split('?', 1)[0].rstrip('/')
    return f"{parts.netloc.lower()}{path}" + (f"#{frag}" if frag else '')


# UI-language path prefixes a web app puts first in the path (`/de/home`, `/en/home`). A tree built in one
# language must still match in another: identity ignores this segment (BUG-0703).
LOCALE_SEGMENTS = frozenset({'de', 'en', 'fr', 'it', 'es', 'pt', 'nl', 'sv', 'da', 'no', 'fi', 'pl', 'cs', 'ro', 'ru', 'tr'})


def strip_locale(path: str) -> str:
    """Drop a leading `/<lang>` (or `/<lang>-<REGION>`) path segment, keep the rest (`/de/home` -> `/home`)."""
    m = re.match(r'^/([A-Za-z]{2})(?:[-_][A-Za-z]{2})?(?=/|$)', path or '')
    if m and m.group(1).lower() in LOCALE_SEGMENTS:
        return path[m.end():] or '/'
    return path or ''


def url_path(url: Optional[str]) -> str:
    """Language-free path of a URL: no host, no query, no trailing slash, no leading language segment."""
    if not url:
        return ''
    parts = urlsplit(url.strip())
    path = strip_locale(parts.path or '/')
    return path.rstrip('/') or '/'


def current_locale(url: Optional[str]) -> str:
    """The UI-language path segment of a URL (`/de/home` -> `de`), '' when it has none."""
    path = urlsplit((url or '').strip()).path
    m = re.match(r'^/([A-Za-z]{2}(?:[-_][A-Za-z]{2})?)(?=/|$)', path)
    return m.group(1) if m and m.group(1)[:2].lower() in LOCALE_SEGMENTS else ''


def resolve_app_url(url: str, current_url: Optional[str]) -> str:
    """Make an edge's navigate_to_url language-free: `/{lang}/settings` or `/settings` opens the page in the
    language the app is showing now, never in the one the tree was built in. A path without a language
    segment gets the current one; a full URL (https://...) is left alone. `/{lang}/` is the explicit form."""
    u = (url or '').strip()
    if '://' in u or not u.startswith('/') and '{lang}' not in u:
        return u
    cur = urlsplit((current_url or '').strip())
    if not cur.scheme or not cur.netloc:
        return u
    loc = current_locale(current_url)
    u = u.replace('{lang}', loc).replace('//', '/') if '{lang}' in u else u
    path = u if u.startswith('/') else '/' + u
    if loc and not current_locale('https://x' + path):
        path = f'/{loc}{path}'
    return f"{cur.scheme}://{cur.netloc}{path}"


def url_matches(url: Optional[str], pattern: str) -> bool:
    """Language-free URL check for web nodes. `pattern` is a path glob (`*` = anything, also across `/`);
    host, query and the language segment are ignored on both sides: `/*/epg/initial`, `/epg/initial` and
    `https://x/de/epg/initial?a=1` all describe the same place."""
    if not url or not pattern or not pattern.strip():
        return False
    want = pattern.strip()
    if '://' in want:
        want = urlsplit(want).path or '/'
    want = want if want.startswith('/') else '/' + want
    want = want.split('?', 1)[0].split('#', 1)[0]
    want = strip_locale(want).rstrip('/') or '/'
    got = url_path(url).lower()
    wants = [want.lower()]
    if want.startswith('/*/'):          # `/*/epg` written for "any language": the language is already ignored
        wants.append(want[2:].lower())
    return any(fnmatch.fnmatchcase(got, w) for w in wants)


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    a, b = set(a or []), set(b or [])
    return len(a & b) / len(a | b) if a and b else 0.0


def node_identity(node_fp: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    ident = (node_fp or {}).get('identity')
    return ident if isinstance(ident, dict) and ident.get('kind') else None


def same_place(live: Dict[str, Any], stored: Dict[str, Any]) -> bool:
    """Same activity (android) / same normalised URL (web)."""
    if live.get('kind') != stored.get('kind'):
        return False
    if live['kind'] == 'android':
        return bool(live.get('activity')) and live.get('activity') == stored.get('activity')
    if live['kind'] == 'web':
        lu, su = normalize_url(live.get('url')), normalize_url(stored.get('url'))
        if not lu or not su:
            return False
        if lu == su:
            return True
        # same host, same path once the UI-language segment is ignored (the tree was built in another language)
        lh, sh = lu.split('/', 1)[0], su.split('/', 1)[0]
        return lh == sh and url_path(live.get('url')) == url_path(stored.get('url')) != '/' 
    return False


def match_identity(live: Optional[Dict[str, Any]], node_fps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Match the live identity against nodes that carry one.

    Returns {decided: node|None, candidates: [node_fp...], reason}. `decided` is set when exactly
    one node shares the place, or a tie at one place is broken by the texts (android) / the title
    (web). `candidates` (2+) narrows the pixel matcher to those nodes; empty means identity says
    nothing (no node carries one, or the place is not in the tree) and pixels run on every node.
    """
    if not live or not live.get('kind'):
        return {'decided': None, 'candidates': [], 'reason': 'no live identity'}
    with_id = [n for n in node_fps if node_identity(n.get('fingerprint'))]
    if not with_id:
        return {'decided': None, 'candidates': [], 'reason': 'no node has an identity'}
    same = [n for n in with_id if same_place(live, node_identity(n['fingerprint']))]
    if not same:
        return {'decided': None, 'candidates': [], 'reason': 'place not in the tree'}
    if len(same) == 1:
        return {'decided': {**same[0], 'score': 1.0}, 'candidates': same, 'reason': 'unique place'}
    if live['kind'] == 'android':
        scored = sorted(((_jaccard(live.get('texts'), node_identity(n['fingerprint']).get('texts')), n) for n in same),
                        key=lambda x: -x[0])
        (best, top), second = scored[0], scored[1][0]
        if best >= TEXT_MIN_SCORE and best - second >= TEXT_MARGIN:
            return {'decided': {**top, 'score': round(best, 3)}, 'candidates': same, 'reason': 'texts'}
    else:
        title = normalize_text(live.get('title') or '')
        titled = [n for n in same if title and normalize_text(node_identity(n['fingerprint']).get('title') or '') == title]
        if len(titled) == 1:
            return {'decided': {**titled[0], 'score': 1.0}, 'candidates': same, 'reason': 'title'}
    return {'decided': None, 'candidates': same, 'reason': 'shared place'}


def identity_verdict(match: Dict[str, Any], live: Dict[str, Any]) -> Dict[str, Any]:
    """kind=node from a decided identity match: same shape as the pixel verdict, evidence.identity."""
    node = match['decided']
    tied = [n['node_id'] for n in match.get('candidates') or [] if n['node_id'] != node['node_id']]
    evidence = {'identity': {k: live.get(k) for k in ('kind', 'package', 'activity', 'url', 'title') if live.get(k)},
                'by': match.get('reason')}
    if tied:
        evidence['same_place'] = tied
    return {'kind': 'node', 'node_id': node['node_id'], 'label': node.get('label') or node['node_id'],
            'confidence': node.get('score', 1.0), 'evidence': evidence}
