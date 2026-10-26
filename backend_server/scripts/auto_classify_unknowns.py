#!/usr/bin/env python3
"""auto_classify_unknowns.py — the scheduled arm of the unknown-screen pipeline.

TASK-115.  The live matcher (verify_node, the Localize button, the future
monitor bridge) writes one row to ``screen_fingerprints`` for every
abstention, bumping ``seen_count`` on each hit.  This script is what turns
that counter into a "name this screen" suggestion the operator can
accept on the existing UserInterfaceUnknown page.

PICKER
    Every screen_fingerprints row where
        verdict = 'unknown' AND
        seen_count >= AUTO_CLASSIFY_THRESHOLD (5) AND
        classification_attempts < MAX_ATTEMPTS (3) AND
        sample_image_path IS NOT NULL
    is fed to the classifier (usage ``vision.classify``) and the result is
    upserted into userinterface_unknown_screens as a pending proposal.  The
    screen shows up on the operator's "Needs a name" list with a
    proposed_name pre-filled, ready to accept, merge or dismiss.

CLASSIFIER MODE
    **Default: ``--classifier qwen``** — Qwen3-VL open-set naming only.  No
    Jev call is made, so no closed-choice node can suppress Qwen.  This is
    the product default after the 2026-10-17 Jev-vs-Qwen benchmark (TASK-67
    §4f: on unknown screens Qwen-only 90 % vs hybrid 60 %, at ~1/6.8 the
    cost).

    **Experimental/advisory: ``--classifier hybrid``** — Jev closed choice
    over the interface's real node ids, then Qwen on ``none``/error.  It is
    never selected implicitly; the deployment unit runs the Qwen default.
    The candidate options are the node labels of the interface that abstained
    (``screen_fingerprints.userinterface``); a row without an interface simply
    gets the open-set answer.

LOCAL FLEET ONLY
    The DB is central and holds rows from every server, but a sample is only
    readable by the server that owns the host (the host API is on that LAN).
    Each server runs this timer; rows whose ``scope`` host is not registered
    locally are skipped WITHOUT bumping ``classification_attempts``, so the
    owning server's timer picks them up.

WHAT THE CLASSIFIER MAY AND MAY NOT DO
    In the default Qwen-only mode no node id is proposed.  In the explicit
    hybrid mode a choice outside the option set is discarded and the open-set
    answer is used instead: an invalid selection can never become a name, a
    node or a fingerprint.  A valid node id is recorded on the proposal
    (``dom.known_node_id``) so the operator can merge; it is never written to
    navigation_nodes.  Nothing in this script creates a node or changes a
    fingerprint — that still happens only when a human accepts.

    sample_image_path can be a server-local file, a /host/<name>/... URL
    (the live matcher's frame_url), or a /var/www/html/... host path.  The
    classifier resolves all three through the existing authenticated
    server->host fetch; a missing/rotated sample is skipped and the
    attempts counter is bumped.

WHY A SEPARATE CRON, NOT A SUPABASE TRIGGER
    The classifier is an LLM call.  It is not safe to run inside a SQL
    trigger.  This script is a normal Python cron so the AI cost is
    auditable in the same place every other AI call lives (ai_endpoints,
    usage_caller).

DRY RUN BY DEFAULT
    Pass --apply to actually write.  The systemd unit runs with --apply
    via Environment= in auto-classify.service.  Operators can re-run
    with --dry-run to see what would be picked this cycle.

WHY ONLY verdict='unknown' ROWS
    'expected' and 'bad' rows are the alert-path memory: they came from
    a freeze alert, the operator already decided what they are.  The
    auto-classify job is for the things the operator has not seen yet.

PRUNE PASS
    Before picking, this script ALSO runs a one-shot retention DELETE
    on screen_fingerprints so the table does not grow unbounded on
    one-off glitches.  Bounded by KEEP_MIN_HITS, KEEP_MAX_AGE_DAYS, and
    a hard LIMIT 500 safety net.

Run on the vpt-server host:
    sudo -u vpt_user /opt/virtualpytest/venv/bin/python3 \\
        /opt/virtualpytest/backend_server/scripts/auto_classify_unknowns.py \\
        --team-id <uuid> --apply

The team id is --team-id, then VIRTUALPYTEST_TEAM_ID, then the app-wide default
constant, so the nightly unit needs no environment change.  main() loads the
project .env (the unit sets only REPO/PYTHONPATH).  Each server runs its own
timer and classifies only rows whose host is registered locally; rows from
another server's fleet are skipped (no attempts bump) for that server's timer.
"""
import argparse
import os
import re
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple


_REPO = os.environ.get('VIRTUALPYTEST_REPO') or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

# The systemd unit only sets REPO/PYTHONPATH; main() loads the project .env
# itself for SUPABASE_*.
from dotenv import load_dotenv  # noqa: E402

from shared.src.lib.config.constants import get_team_id  # noqa: E402
from shared.src.lib.utils.supabase_utils import get_supabase_client  # noqa: E402
from shared.src.lib.utils.screen_classifier import classify_open, classify_screen  # noqa: E402

# ---- knobs (all overrideable by --flag) ----
AUTO_CLASSIFY_THRESHOLD = 5     # row needs to have been seen at least this often
AUTO_CLASSIFY_MIN_HOSTS = 2    # not yet wired to scope; placeholder for cross-host noise filter
MAX_ATTEMPTS = 3               # give up on the AI after this many failed attempts
KEEP_MIN_HITS = 3              # never delete a row seen fewer than this
KEEP_MAX_AGE_DAYS = 14         # and the row must be older than this
PRUNE_TOP_N_FLOOR = 500        # safety net: never delete below the top-N
INTERFACE_OPTION_LIMIT = 60    # closed-choice options sent to the model (cost/latency)
# A recurring screen that is one kind of screen whatever picture it shows (e.g. the operator's full-screen
# poster: no menu, a different artwork each time). Open-set naming would call
# every poster by its title and never converge, and a 60-option closed choice picked the wrong tab (measured
# 2026-10-19), so a state is a yes/no check asked of Qwen first: answer == `answer` -> the row is named `label`
# and linked to the node labelled `node`. [(node label, stored label, question, answer)], asked in order on the image of every unnamed row
STATE_HINTS = [
    (None, 'Splash screen',
     'This is a TV screen. Is it a full-screen splash, welcome or start-up screen (a logo or a greeting such as '
     'Welcome on a plain or decorative background, no menu bar, no movie artwork)? Answer SPLASH or OTHER.',
     'SPLASH'),
    ('home', 'Full-screen poster',
     'This is a TV screen. Does it show a menu bar or tab names or a title header (readable words '
     'arranged as a menu)? Answer MENU or NOMENU. A picture with only a logo or a movie title in the '
     'artwork counts as NOMENU.',
     'NOMENU'),
]
# The STATE_HINTS describe the operator set-top box ("This is a TV screen", its full-screen poster and its welcome
# splash). Asked of anything else they name the wrong thing, and a name is never replaced (TASK-159 G4): a Clash of Clans
# village has no menu bar, answers NOMENU and became "Full-screen poster" (116 rows on a phone), an Apple TV aerial
# screensaver became "Splash screen" (measured 2026-10-25). So they are asked only of rows whose device model is listed
# here; every other row is named open-set.
STATE_HINT_MODELS = frozenset({'stb'})
_device_models: Dict[str, str] = {}


def device_model_of(scope: Optional[str]) -> str:
    """The device model of a ``<host>/<device>`` scope, from that device's latest metrics row; '' when unknown.
    Cached for the run. ``system_device_metrics`` has no team_id: it is keyed by host and device."""
    scope = scope or ''
    if scope not in _device_models:
        host, _, device = scope.partition('/')
        model = ''
        if host and device:
            try:
                res = (get_supabase_client().table('system_device_metrics').select('device_model')
                       .eq('host_name', host).eq('device_id', device)
                       .order('timestamp', desc=True).limit(1).execute())
                model = ((res.data or [{}])[0].get('device_model') or '').strip()
            except Exception as exc:
                print(f'[auto_classify] device model lookup failed for {scope}: {exc}')
        _device_models[scope] = model
    return _device_models[scope]


def state_hints_for(row: Dict[str, Any]) -> list:
    """The STATE_HINTS when the row's device is one they were written for, else none."""
    return STATE_HINTS if device_model_of(row.get('scope')) in STATE_HINT_MODELS else []


# Team id: --team-id, then VIRTUALPYTEST_TEAM_ID, then the app-wide default
# constant (shared/src/lib/config/constants.py) so the unit needs no env.
DEFAULT_TEAM_ID = get_team_id()   # shared/src/lib/config/constants.py (TEAM_ID or its fallback)

# The actual DELETE is a Postgres function (created in migration
# 20261016c_prune_screen_fingerprints_fn.sql) so it can express the
# NOT-IN-subquery that supabase-py's chainable filter builder cannot.
# Calling it via RPC is one round-trip.
PRUNE_RPC = 'prune_unnamed_screen_noise'   # TASK-159: skips named rows (20261022f); 20261016c's function is no longer called
NAME_RPC = 'name_screen_row'
# TASK-159: a row is unnamed while its label is NULL or the registry's placeholder unknown_<N>.
UNNAMED_RE = '^unknown_[0-9]+$'


def _team_id_arg() -> Optional[str]:
    # The unit's VIRTUALPYTEST_TEAM_ID is empty by default; fall through to the
    # app-wide default so the nightly run needs no environment change.
    return os.environ.get('VIRTUALPYTEST_TEAM_ID') or get_team_id()


def pick_candidates(db, team_id: str, threshold: int) -> List[Dict[str, Any]]:
    """Every screen_fingerprints row that crossed the auto-classify threshold.

    The partial index (idx_screen_fingerprints_auto_classify, defined in
    migration 20261016b) keeps this query sub-millisecond on a 100k-row
    table.  The leading column is ``seen_count`` so the planner stops
    on the threshold predicate.
    """
    res = (db.table('screen_fingerprints')
           .select('id, dhash, scope, userinterface, seen_count, sample_image_path, '
                   'classification_attempts, last_seen, fingerprint')
           .eq('team_id', team_id)
           .eq('verdict', 'unknown')
           .is_('merged_into', 'null')
           .or_(f'label.is.null,label.match.{UNNAMED_RE}')   # a real name is never offered again (G4)
           .gte('seen_count', threshold)
           .lt('classification_attempts', MAX_ATTEMPTS)
           .not_.is_('sample_image_path', 'null')
           .order('seen_count', desc=True)
           .limit(100)  # one cycle picks at most 100 — keep the AI bill bounded
           .execute())
    return res.data or []


def prune_noise(db, team_id: str) -> int:
    """Drop the noise: low-count, old, never-classified rows.  Idempotent.

    The actual DELETE is a Postgres function
    (prune_unnamed_screen_noise) created in migration
    20261022f_screen_prune_guard.sql — it expresses the
    NOT-IN-subquery that supabase-py's chainable filter builder cannot.
    Returns the number of rows deleted.  Never raises — a failed prune is
    a noisy table, not a broken pipeline.
    """
    try:
        res = db.rpc(PRUNE_RPC, {
            'p_team_id': team_id,
            'p_min_hits': KEEP_MIN_HITS,
            'p_max_age_days': KEEP_MAX_AGE_DAYS,
            'p_floor': PRUNE_TOP_N_FLOOR,
        }).execute()
        # RPCs return a list with one row (the count).
        if res.data and isinstance(res.data, list):
            return int(res.data[0].get('deleted_count') or 0)
        return 0
    except Exception as exc:
        print(f'[auto_classify] prune failed (non-fatal): {exc}')
        return 0


def row_userinterface(row: Dict[str, Any]) -> str:
    """The interface recorded on the row, '' when there is none. An unmatched screen is not linked to an interface
    (TASK-159 G6): the scope's device part is no interface name and is never used as one."""
    return (row.get('userinterface') or '').strip()


def interface_options(db, team_id: str,
                      userinterface: Optional[str]) -> List[Dict[str, Any]]:
    """The interface's real, fingerprinted node ids and labels.

    These are the only options the closed-choice model may pick from, so a
    choice it returns names a node that exists. Empty on a legacy row with no
    interface, an interface with no tree, or a tree with no fingerprinted node
    — the caller then uses the open-set answer.
    """
    name = (userinterface or '').strip()
    if not name:
        return []
    try:
        ui = (db.table('userinterfaces').select('id')
              .eq('team_id', team_id).eq('name', name).limit(1).execute())
        if not ui.data:
            return []
        trees = (db.table('navigation_trees').select('id')
                 .eq('team_id', team_id)
                 .eq('userinterface_id', ui.data[0]['id']).execute())
        tree_ids = [t['id'] for t in (trees.data or [])]
        if not tree_ids:
            return []
        rows = (db.table('navigation_nodes')
                .select('node_id, label, node_type, dhash:data->fingerprint->>dhash')
                .eq('team_id', team_id).in_('tree_id', tree_ids).limit(1000).execute())
    except Exception as exc:  # noqa: BLE001
        print(f'[auto_classify] interface_options({name}) failed: {exc}')
        return []

    seen = set()
    options: List[Dict[str, Any]] = []
    for r in rows.data or []:
        node_id = r.get('node_id')
        if not node_id or node_id in seen or not r.get('dhash'):
            continue
        if (r.get('node_type') or 'screen') in ('entry', 'action'):
            continue
        seen.add(node_id)
        options.append({'id': node_id, 'description': r.get('label') or node_id})
    options.sort(key=lambda o: o['id'])
    return options[:INTERFACE_OPTION_LIMIT]


def upsert_proposal(db, team_id: str, row: Dict[str, Any], dom: Dict[str, Any],
                     label: str) -> bool:
    """Push the proposal into userinterface_unknown_screens.

    Upserted on (team_id, userinterface, cluster_dhash) — re-running the
    scheduler on the same row OVERWRITES the previous proposal, so an
    improved AI call can fix a bad name without the operator cleaning up.
    """
    from datetime import datetime, timezone
    # The interface that abstained, recorded by the live matcher; legacy rows
    # fall back to the device part of the scope.
    userinterface = row_userinterface(row)
    if not userinterface:
        return False
    now_iso = datetime.now(timezone.utc).isoformat()
    # G3: keep the full v6 fingerprint the live matcher stored (dhash, regions,
    # crop, focus, title, text). Legacy rows have NULL → fall back to dhash-only,
    # which identify_screen reads through its v4 path.
    fingerprint = row.get('fingerprint')
    if not isinstance(fingerprint, dict) or not fingerprint.get('dhash'):
        fingerprint = {'dhash': row['dhash']}
    payload = {
        'team_id': team_id,
        'userinterface': userinterface,
        'cluster_dhash': row['dhash'],
        'classification': 'unknown',
        'status': 'pending',
        'proposed_name': label,
        'screen_type': dom.get('screen_type'),
        'frame_count': int(row.get('seen_count') or 0),
        'image_url': row.get('sample_image_path'),
        'fingerprint': fingerprint,
        'dom': dom,
        'last_scan_at': now_iso,
    }
    try:
        (db.table('userinterface_unknown_screens').upsert(
            payload, on_conflict='team_id,userinterface,cluster_dhash').execute())
        return True
    except Exception as exc:
        print(f'[auto_classify] upsert failed for dhash {row["dhash"]}: {exc}')
        return False


def name_row(db, team_id: str, row_id: str, label: str) -> bool:
    """Write the name on the screen_fingerprints row itself. Localize's known-screen step
    (localize_verdict.known_screen_verdict) reads ``label`` from this row, so this is what turns
    ``unknown_N`` into a named screen on the badge. The verdict stays 'unknown': naming is not
    triage. A name is written once: the SQL function only updates a row whose label is NULL or ``unknown_N``
    (TASK-159 G4). Returns True when the name was written."""
    try:
        res = db.rpc(NAME_RPC, {'p_team_id': team_id, 'p_id': row_id, 'p_label': label}).execute()
        return bool(res.data)
    except Exception as exc:
        print(f'[auto_classify] name_row failed for {row_id}: {exc}')
        return False


def bump_attempts(db, team_id: str, row_id: str) -> None:
    """Increment the attempts counter so a hash the AI cannot classify
    is given up on after MAX_ATTEMPTS.

    Read-then-write is fine: the counter is monotonic and the worst case
    is two cron cycles hitting the same row, which still respects the
    MAX_ATTEMPTS guard (the picker only picks rows with attempts < 3,
    and a bump that runs twice still only takes the row from 2 to 3 on
    the next cycle).
    """
    from datetime import datetime, timezone
    try:
        cur = (db.table('screen_fingerprints').select('classification_attempts')
               .eq('id', row_id).eq('team_id', team_id).limit(1).execute())
        if not cur.data:
            return
        nxt = int(cur.data[0].get('classification_attempts') or 0) + 1
        (db.table('screen_fingerprints')
         .update({'classification_attempts': nxt,
                  'updated_at': datetime.now(timezone.utc).isoformat()})
         .eq('id', row_id).eq('team_id', team_id).execute())
    except Exception as exc:
        print(f'[auto_classify] bump_attempts failed for {row_id}: {exc}')


def _fetch_sample_to_temp(sample: str, scope: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Fetch a host capture URL to a temp file; return ``(path, reason)``.

    The live matcher stores ``frame_url`` (a relative ``/host/<name>/stream/...``
    path, or an absolute URL), not a server-local path. Reuse the existing
    authenticated server->host fetch (`_fetch_screenshot_bytes`): a relative
    path is served by that host's nginx with the service key, an absolute URL
    is fetched as-is. No new storage is introduced.

    A row whose host is not in this server's registry is skipped before it
    reaches here: each server classifies only its own fleet, so the sample is
    always served by a host this process can call.
    """
    from backend_server.src.mcp.tools.screenshot_tools import _fetch_screenshot_bytes

    # The host is in the URL (`/host/<name>/...`); scope (`<host>/<device>`)
    # is the fallback when the URL has no host segment.
    host_name = scope.split('/', 1)[0] if scope and '/' in scope else None
    data, reason = _fetch_screenshot_bytes(sample, host_name=host_name)
    if not data:
        return None, reason or 'fetch returned no bytes'
    suffix = '.png' if data[:8] == b'\x89PNG\r\n\x1a\n' else '.jpg'
    fd, path = tempfile.mkstemp(prefix='vpt_unknown_', suffix=suffix)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(data)
    return path, None


def _host_local_to_url(sample: str, scope: Optional[str] = None) -> Optional[str]:
    """Map a host-local capture path to the host's nginx route.

    The host route is ``/host/<name>/stream/<device>/<content_type>/<file>``.
    The on-disk path adds the storage tier: ``/var/www/html/stream/<device>/hot/<content_type>/<file>``
    (hot) or ``.../<content_type>/<file>`` (cold). The ``hot`` segment is storage,
    not a content type, so it is dropped. The host name comes from the row's
    ``scope`` (``<host>/<device>``).
    """
    if not sample.startswith(('/var/www/html/stream/', '/var/www/html/')):
        return None
    host_name = scope.split('/', 1)[0] if scope and '/' in scope else None
    if not host_name:
        return None
    rel = sample[len('/var/www/html'):]
    rel = re.sub(r'^(/stream/[^/]+)/hot/', r'\1/', rel)
    return f"/host/{host_name}{rel}"


def resolve_sample_path(sample: Optional[str], scope: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a row's ``sample_image_path`` to a readable local path.

    Returns ``(path, None)`` when readable, ``(None, reason)`` when the sample
    is missing, has rotated away, or cannot be fetched. A temp file returned
    here is the caller's to delete.

    Accepts the three shapes the DB actually holds:
    - a server-local path (used as-is);
    - a relative host route ``/host/<name>/...`` (the live matcher's ``frame_url``);
    - a host-local ``/var/www/html/...`` path (the alert path), mapped to the
      host's nginx route using the row's ``scope`` host.
    """
    if not sample:
        return None, 'no sample image'
    if sample.startswith('data:image/'):
        import base64
        try:
            data = base64.b64decode(sample.split(',', 1)[1])
        except Exception:  # noqa: BLE001
            return None, 'bad data URI sample'
        fd, path = tempfile.mkstemp(prefix='vpt_unknown_', suffix='.jpg')
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        return path, None
    if os.path.exists(sample):
        return sample, None
    if sample.startswith(('http://', 'https://')) or sample.startswith('/host/'):
        return _fetch_sample_to_temp(sample, scope)
    host_url = _host_local_to_url(sample, scope)
    if host_url:
        return _fetch_sample_to_temp(host_url, scope)
    return None, 'sample is not a local path or a host URL'


def classify_state(path: str, team_id: str, hints: Optional[list] = None) -> Optional[Dict[str, Any]]:
    """The closed yes/no state checks (``hints``, default STATE_HINTS) on the image, in order: the first one answered
    with its answer names the row, or None (none of the states). No interface is consulted (TASK-159 G6)."""
    from shared.src.lib.utils.screen_classifier import _call, DEFAULT_OPEN_PROFILE
    for node_label, label, question, answer in (STATE_HINTS if hints is None else hints):
        out = _call(DEFAULT_OPEN_PROFILE, question, path, team_id, max_tokens=16)
        if not out.get('ok') or (out.get('content') or '').strip().upper().strip('.') != answer:
            continue
        return {'dom': {'screen_type': None, 'screen_summary': label, 'state_of_node': node_label,
                        'classifier': {'source': 'state_check', 'raw': out.get('content')}},
                'label': label, 'ok': True}
    return None


def classify_one(row: Dict[str, Any], team_id: str,
                 options: Optional[List[Dict[str, Any]]] = None,
                 mode: str = 'qwen') -> Optional[Dict[str, Any]]:
    """Run the classifier for one row, return {dom, label, ok} or None.

    ``mode='qwen'`` (default) calls Qwen open-set naming only: no Jev call and
    no node choice. ``mode='hybrid'`` is the explicitly selected experimental
    mode (Jev closed choice over ``options``, then Qwen on ``none``/error).

    G1: a live row's ``sample_image_path`` is a host capture URL, not a
    server-local file. Resolve it through the authenticated host fetch before
    classifying; a rotated/expired sample returns None so ``run_once`` bumps
    ``classification_attempts`` and stops retrying after MAX_ATTEMPTS.
    """
    sample = row.get('sample_image_path')
    path, reason = resolve_sample_path(sample, row.get('scope'))
    if not path:
        print(f'[auto_classify] skipping dhash {str(row.get("dhash"))[:16]}...: {reason}')
        # The sample is gone (rotated host frame): not the classifier's failure. The next sighting stores a
        # durable thumbnail; do not burn an attempt waiting for it.
        return {'ok': False, 'no_sample': True}
    temp = path != sample
    try:
        state = classify_state(path, team_id, state_hints_for(row))
        if state:
            return state
        if mode == 'hybrid':
            options = options or []
            result = classify_screen(path, team_id, options=options or None)
        else:
            result = classify_open(path, team_id)
        if not result.get('ok'):
            return None
        if mode == 'hybrid':
            by_id = {o['id']: o.get('description') or o['id'] for o in options}
            choice = result.get('choice')
            if result.get('source') == 'jev' and choice and choice != 'none':
                if choice not in by_id:
                    # Defence in depth: never let an id the interface does not
                    # have become a name. The parser only returns offered ids;
                    # this also covers a different classifier implementation.
                    result = classify_open(path, team_id)
                    if not result.get('ok'):
                        return None
                else:
                    label = by_id[choice]
                    return {'dom': {'screen_type': None, 'screen_summary': label,
                                    'known_node_id': choice, 'classifier': result},
                            'label': label, 'ok': True}
        label = result.get('label')
        if not label:
            return None   # no name: the row stays unknown_N and the attempt is counted
        return {'dom': {'screen_type': None, 'screen_summary': label,
                        'classifier': result}, 'label': label, 'ok': True}
    finally:
        if temp:
            try:
                os.unlink(path)
            except OSError:
                pass


def local_host_names() -> set:
    """Host names registered on THIS server (its own fleet).

    The central DB holds rows from every server, but a sample is only readable
    by the server that owns the host (the host API is on that LAN). Each server
    runs its own timer and must skip rows from another fleet; the owning
    server's timer will classify them.
    """
    try:
        from backend_server.src.lib.utils.server_utils import get_host_manager
        return set((get_host_manager().get_all_hosts() or {}).keys())
    except Exception as exc:  # noqa: BLE001
        print(f'[auto_classify] host registry unavailable: {exc}')
        return set()


def run_once(team_id: str, threshold: int, apply: bool, prune: bool,
             classifier: str = 'qwen') -> Dict[str, int]:
    db = get_supabase_client()
    if db is None:
        print('[auto_classify] no Supabase client — nothing to do')
        return {'picked': 0, 'proposed': 0, 'failed': 0, 'pruned': 0,
                'skipped_remote': 0}

    stats = {'picked': 0, 'proposed': 0, 'failed': 0, 'pruned': 0,
             'skipped_remote': 0}

    if prune:
        stats['pruned'] = prune_noise(db, team_id)

    candidates = pick_candidates(db, team_id, threshold)
    hosts = local_host_names()
    if hosts:
        local = [r for r in candidates
                 if (r.get('scope') or '').split('/', 1)[0] in hosts]
    else:
        # No host registered yet: classify nothing rather than hammering
        # samples this process cannot read.
        local = []
    stats['skipped_remote'] = len(candidates) - len(local)
    candidates = local
    stats['picked'] = len(candidates)
    skipped = (f' (skipped {stats["skipped_remote"]} from another server/fleet)'
               if stats['skipped_remote'] else '')
    print(f'[auto_classify] {len(candidates)} candidate(s) above threshold={threshold}{skipped} '
          f'classifier={classifier}')

    if not apply:
        for row in candidates:
            print(f'  [dry-run] dhash={row["dhash"][:16]}...  '
                  f'seen={row["seen_count"]}  attempts={row.get("classification_attempts", 0)}  '
                  f'sample={row.get("sample_image_path")}')
        return stats

    options_cache: Dict[str, List[Dict[str, Any]]] = {}
    for row in candidates:
        interface = row_userinterface(row)
        if classifier == 'hybrid':
            # Many candidates share one interface: read its nodes once per run.
            if interface not in options_cache:
                options_cache[interface] = interface_options(db, team_id, interface)
            outcome = classify_one(row, team_id, options=options_cache[interface],
                                   mode='hybrid')
        else:
            # Default: Qwen-only, no Jev call and no node options.
            outcome = classify_one(row, team_id, mode='qwen')
        if outcome and outcome.get('no_sample'):
            stats['no_sample'] = stats.get('no_sample', 0) + 1
            continue
        if not outcome:
            stats['failed'] += 1
            bump_attempts(db, team_id, row['id'])
            continue
        # a proposal needs the interface the row was seen on; an unmatched screen has none, it is only named
        ok = (upsert_proposal(db, team_id, row, outcome['dom'], outcome['label'])
              if row_userinterface(row) else True)
        named = name_row(db, team_id, row['id'], outcome['label'])
        bump_attempts(db, team_id, row['id'])
        if ok and named:
            stats['proposed'] += 1
            stats['named'] = stats.get('named', 0) + 1
        else:
            stats['failed'] += 1
    return stats


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--team-id', default=_team_id_arg(),
                   help='team UUID; falls back to VIRTUALPYTEST_TEAM_ID env var')
    p.add_argument('--threshold', type=int, default=AUTO_CLASSIFY_THRESHOLD,
                   help=f'min seen_count to classify (default {AUTO_CLASSIFY_THRESHOLD})')
    p.add_argument('--apply', action='store_true', default=False,
                   help='actually write proposals; default is dry-run')
    p.add_argument('--no-prune', action='store_true', default=False,
                   help='skip the retention DELETE (use when debugging the picker)')
    p.add_argument('--classifier', choices=('qwen', 'hybrid'), default='qwen',
                   help='qwen (default) = Qwen-only open-set naming; '
                        'hybrid = experimental Jev closed choice + Qwen fallback')
    return p.parse_args(argv)


def main(argv=None) -> int:
    # The unit has no EnvironmentFile: load the project .env for SUPABASE_* and
    # SUPABASE_* before resolving the team id or touching the DB.
    load_dotenv(os.path.join(_REPO, '.env'), override=False, encoding='utf-8-sig')
    args = parse_args(argv)
    if not args.team_id:
        print('[auto_classify] team_id is required (--team-id or VIRTUALPYTEST_TEAM_ID)',
              file=sys.stderr)
        return 2
    started = time.time()
    print(f'[auto_classify] team={args.team_id} threshold={args.threshold} '
          f'apply={args.apply} prune={not args.no_prune} classifier={args.classifier}')
    stats = run_once(args.team_id, args.threshold, args.apply,
                     prune=not args.no_prune, classifier=args.classifier)
    elapsed = time.time() - started
    print(f'[auto_classify] done in {elapsed:.1f}s — {stats}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
