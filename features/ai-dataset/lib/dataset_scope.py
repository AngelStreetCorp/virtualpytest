"""Which navigation trees feed the AI dataset, and what a "screen" is (TASK-27 step 4h).

One place for the scope shared by ``scripts/seed_from_trees.py``, ``scripts/coverage_report.py``
and the ``/server/training-samples/coverage`` route:

* ``CANONICAL_USERINTERFACES``: the apps the dataset covers, each with its platform. Every
  other userinterface of a team is a copy, a variant, a generated tree or a test fixture of one
  of these (``stb3_autobuild``, ``stb_tv_settings``, ``__smoke_*`` ...). It is never seeded and
  is listed as "not in scope" by the coverage report, so nothing is silently hidden.
* ``EXCLUDED_NAME_PATTERNS``: name patterns that are never in scope, even if someone adds
  them to the canonical list by mistake.
* a visible screen: a ``screen`` or ``menu`` node (never ``entry`` / ``action``) that is not
  ``hidden_in_base`` (a variant-only row). ``is_system_protected`` is **not** a filter: the
  ``home`` node is protected and is a real screen.
* the trees of an app: its root tree plus every nested subtree below it (walked by
  ``parent_tree_id``). A nested subtree repeats its parent node, so one screen can appear on
  several node rows; the coverage unit is the distinct ``node_id`` per app.

Mobile comes later: add the app here with platform ``android_mobile`` (or ``ios``) once core
``training_samples.EXCLUDED_DEVICE_MODELS`` allows phone frames (TASK-27 §9). Until then the
seed refuses a phone userinterface because core would drop every sample anyway.

The DB readers at the bottom are read-only and team-scoped (CONTRACTS rule 7).
"""
from __future__ import annotations

import fnmatch
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

# name -> platform. Platform names follow the device-model families
# (shared/src/lib/config/device_capabilities.py): stb, android_tv, android_mobile, web ...
CANONICAL_USERINTERFACES: Dict[str, str] = {
    'stb_tv': 'stb',
    # 'iad_gui' (web) is out of scope: its gateway page (192.168.0.1) is not reachable from any
    # collecting host (human decision 2026-09-30). Its 6 seeded train rows stay.
    'youtube-web': 'web',
    'web_tv': 'web',
}

# Same app as a canonical one (generated, copied, depth-limited, simulated, a settings
# slice, a live-only slice) or a test fixture. Matched with fnmatch on the full name.
EXCLUDED_NAME_PATTERNS: tuple = (
    '*_autobuild*', '*_copy', '*_depth*', '*_sim', '*_settings*', '*_live', '__smoke*', '__ci*',
)

# Temporary trees whose samples are filed under a canonical app by
# ``scripts/fold_temp_trees.py`` (owner, 2026-10-04): the stb4 acceptance pipeline's per-run
# copies of the STB tree. Matched with fnmatch on the userinterface name.
TEMP_TREE_ALIASES: Dict[str, str] = {
    'acceptance-*-stb': 'stb_tv',
    'qa-*-stb': 'stb_tv',
}
# Screen names of those copies that differ from the canonical app's, checked on a frame each
# (2026-10-05): full-screen live TV, the options menu over live, the TV Guide grid, the audio
# picker over live. Spelling variants of the same names are included; unverified names are not.
TEMP_TREE_SCREEN_SYNONYMS: Dict[str, str] = {
    'live_channel': 'live', 'live_channel5': 'live', 'live_channel_5': 'live',
    'live_options': 'live_menu', 'live_options_menu': 'live_menu', 'live-options-menu': 'live_menu',
    'tv-guide': 'tvguide',
    'live_audio': 'live_menu_audio', 'live_audio_menu': 'live_menu_audio', 'live-audio-menu': 'live_menu_audio',
}

SCREEN_NODE_TYPES = ('screen', 'menu')
ENTRY_NODE_IDS = ('entry-node',)

# Device model -> platform, for userinterfaces outside the canonical list and for banner
# rows (which carry a device_model but no userinterface).
_MODEL_PLATFORM = {
    'stb': 'stb',
    'android_tv': 'android_tv', 'fire_tv_fireos': 'android_tv',
    'android_mobile': 'android_mobile', 'cloud_android_mobile': 'android_mobile',
    'runner_android_mobile': 'android_mobile', 'phone_agent': 'android_mobile',
    'android_tablet': 'android_tablet', 'runner_android_tablet': 'android_tablet',
    'ios': 'ios', 'ios_mobile': 'ios', 'ios_phone': 'ios', 'cloud_ios_mobile': 'ios',
    'web': 'web', 'host_vnc': 'desktop', 'desktop': 'desktop',
}


# ---- scope ------------------------------------------------------------------------------

def excluded_pattern(name: str) -> Optional[str]:
    """The exclusion pattern ``name`` matches, or None."""
    for pattern in EXCLUDED_NAME_PATTERNS:
        if fnmatch.fnmatchcase(name or '', pattern):
            return pattern
    return None


def scope_refusal(name: str) -> Optional[str]:
    """Why ``name`` may not be seeded or counted as canonical, or None when it may."""
    pattern = excluded_pattern(name)
    if pattern:
        return f"'{name}' matches the exclusion pattern '{pattern}' (a copy or a fixture of a canonical app)"
    if name not in CANONICAL_USERINTERFACES:
        return (f"'{name}' is not in CANONICAL_USERINTERFACES "
                f"({', '.join(sorted(CANONICAL_USERINTERFACES))})")
    return None


def platform_of_model(model: Optional[str]) -> str:
    return _MODEL_PLATFORM.get(model or '', model or 'unknown')


def platform_of(name: str, models: Optional[Sequence[str]] = None) -> str:
    """Canonical platform of an app, else the platform of its first device model."""
    if name in CANONICAL_USERINTERFACES:
        return CANONICAL_USERINTERFACES[name]
    return platform_of_model((list(models or []) or [None])[0])


def device_model_for(models: Optional[Sequence[str]]) -> Optional[str]:
    """The device model a seeded sample is stored under: the userinterface's first model."""
    models = [m for m in (models or []) if m]
    return models[0] if models else None


# ---- nodes and trees (pure) ------------------------------------------------------------------

def node_type(node: Dict[str, Any]) -> str:
    data = node.get('data') if isinstance(node.get('data'), dict) else {}
    return str(node.get('node_type') or data.get('type') or '').lower()


def is_visible_screen(node: Dict[str, Any]) -> bool:
    """A ``screen``/``menu`` node that is not a variant-only row and not the entry point."""
    if node_type(node) not in SCREEN_NODE_TYPES:
        return False
    if node.get('hidden_in_base'):
        return False
    if node.get('node_id') in ENTRY_NODE_IDS or str(node.get('label') or '').strip().upper() == 'ENTRY':
        return False
    return bool(node.get('node_id'))


def visible_screens(nodes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [n for n in nodes if is_visible_screen(n)]


def screenshot_of(node: Dict[str, Any]) -> str:
    data = node.get('data') if isinstance(node.get('data'), dict) else {}
    return str(node.get('screenshot') or data.get('screenshot') or '').strip()


def tree_ids_from_root(trees: Sequence[Dict[str, Any]]) -> List[str]:
    """The root tree (``is_root_tree``, oldest first, as ``get_root_tree_for_interface``)
    plus every tree below it by ``parent_tree_id``, root first. [] without a root."""
    roots = sorted((t for t in trees if t.get('is_root_tree')), key=lambda t: str(t.get('created_at') or ''))
    if not roots:
        return []
    children: Dict[str, List[str]] = {}
    for t in trees:
        parent = t.get('parent_tree_id')
        if parent:
            children.setdefault(str(parent), []).append(str(t['id']))
    order, queue, seen = [], [str(roots[0]['id'])], set()
    while queue:
        tid = queue.pop(0)
        if tid in seen:
            continue
        seen.add(tid)
        order.append(tid)
        queue.extend(sorted(children.get(tid, [])))
    return order


def sanitize_label(label: str) -> str:
    """The object name the screenshot writers use for a node label
    (``capture_node_screenshots._sanitize_filename``, ``useNode.ts``)."""
    return re.sub(r'[^a-zA-Z0-9_-]', '', re.sub(r'\s+', '_', label or ''))


def screenshot_keys(node: Dict[str, Any], userinterface: str,
                    resolve: Callable[[str], str]) -> List[str]:
    """Object keys to try, in order: the path in ``data.screenshot`` (a URL or a key,
    resolved against the default bucket), then ``navigation/<ui>/<label>.jpg``.
    [] when the node has no ``data.screenshot``: a node without one is never seeded."""
    url = screenshot_of(node)
    if not url:
        return []
    keys = []
    resolved = resolve(url)
    if resolved:
        keys.append(resolved)
    fallback = f"navigation/{userinterface}/{sanitize_label(str(node.get('label') or ''))}.jpg"
    if fallback not in keys:
        keys.append(fallback)
    return keys


# ---- DB readers (read-only, team-scoped) -----------------------------------------------------

_PAGE = 1000


def _client():
    from shared.src.lib.utils.supabase_utils import get_supabase_client
    return get_supabase_client()


def _paged(build) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        page = build().range(offset, offset + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        offset += _PAGE


def load_userinterfaces(team_id: str) -> List[Dict[str, Any]]:
    """Every userinterface of the team (``mode='dev'`` rows; a published app also has a
    ``prod`` row with the same name, which is the same app)."""
    rows = _paged(lambda: _client().table('userinterfaces').select('id, name, models, mode')
                  .eq('team_id', team_id).order('created_at'))
    by_name: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        r['id'] = str(r['id'])
        if r['name'] not in by_name or (r.get('mode') == 'dev' and by_name[r['name']].get('mode') != 'dev'):
            by_name[r['name']] = r
    return list(by_name.values())


def load_trees(team_id: str, userinterface_ids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    def build():
        q = (_client().table('navigation_trees')
             .select('id, userinterface_id, is_root_tree, parent_tree_id, created_at')
             .eq('team_id', team_id))
        if userinterface_ids is not None:
            q = q.in_('userinterface_id', list(userinterface_ids))
        return q.order('created_at')
    if userinterface_ids is not None and not userinterface_ids:
        return []
    rows = _paged(build)
    for r in rows:
        r['id'] = str(r['id'])
        r['userinterface_id'] = str(r['userinterface_id']) if r.get('userinterface_id') else None
        r['parent_tree_id'] = str(r['parent_tree_id']) if r.get('parent_tree_id') else None
    return rows


# Trees per node query. Servers that reach the DB through the public proxy (Cloudflare ->
# nginx -> PostgREST, e.g. the Pi's rpitest server) got a 502 on 92 trees at once when the
# screenshot was read out of the large ``data`` column; 75 passed. 25 keeps a wide margin.
_TREE_CHUNK = 25


def load_screen_nodes(team_id: str, tree_ids: Sequence[str],
                      with_screenshot: bool = True) -> List[Dict[str, Any]]:
    """``screen``/``menu`` node rows of these trees. With ``with_screenshot`` the screenshot
    URL is read out of ``data`` (which also holds the large fingerprint): only the seed needs
    it, coverage passes False."""
    out: List[Dict[str, Any]] = []
    ids = [str(t) for t in tree_ids]
    cols = 'tree_id, node_id, label, node_type, hidden_in_base'
    if with_screenshot:
        cols += ', screenshot:data->>screenshot'
    for i in range(0, len(ids), _TREE_CHUNK):
        chunk = ids[i:i + _TREE_CHUNK]
        out.extend(_paged(lambda: _client().table('navigation_nodes')
                          .select(cols)
                          .eq('team_id', team_id).in_('tree_id', chunk)
                          .in_('node_type', list(SCREEN_NODE_TYPES)).order('node_id')))
    for r in out:
        r['tree_id'] = str(r['tree_id'])
    return out


def app_screen_nodes(ui: Dict[str, Any], trees: Sequence[Dict[str, Any]],
                     nodes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Visible screen node rows of one app: its root tree and nested subtrees only."""
    own = [t for t in trees if t.get('userinterface_id') == ui['id']]
    tree_ids = set(tree_ids_from_root(own))
    return [n for n in visible_screens(nodes) if n.get('tree_id') in tree_ids]
