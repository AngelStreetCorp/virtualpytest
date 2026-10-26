#!/usr/bin/env python3
"""
unknown_screen_scan.py — find the screens a device shows that have no node in its tree.

Runs on a host, where the capture archive lives. Walks the archive, clusters frames into distinct
screens, drops the ones that are not screens at all (black, no signal), separates broadcast/game
footage from genuinely unknown UI, and POSTs the result to the server's unknown-screens table.

WHY IT EXISTS
    The localizer abstains whenever nothing in the tree fingerprints strongly enough. Measured over
    4,507 processed cold frames, 2,029 abstentions reduced to just 15 distinct screens — 11 of them
    broadcast or game footage. That 15-vs-4 collapse is what this script automates.

WHY IT CLUSTERS RATHER THAN READING THE ABSTAIN LOG
    The localizer's own verdict is per frame-pair and includes transients (a screen mid-render, a
    single cut). Clustering first and asking about *screens* instead of frames is what turned a
    2,029-row bucket into something a person can read in a minute.

DRY RUN BY DEFAULT. Nothing is written to the server without --apply.

Run (on a host):
    sudo -n -u vpt_user env VIRTUALPYTEST_REPO=/opt/virtualpytest PYTHONPATH=/opt/virtualpytest \
      /opt/virtualpytest/venv/bin/python3 \
      features/avq/backend_host/localize/unknown_screen_scan.py \
        --capture-root /data/captures --userinterface stb_tv --team-id <uuid>

    ... add --apply to POST the findings.
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

_REPO = os.environ.get('VIRTUALPYTEST_REPO') or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from shared.src.lib.ai import screen_state_cv as scv           # noqa: E402
from shared.src.lib.utils.image_hash import dhash_hex, dhash_hamming  # noqa: E402

# dHash grid/bits match the fingerprint matcher (FP_DHASH_BITS = 256) so a cluster centre is
# directly comparable with a node's stored hash.
DHASH_GRID = 16
DHASH_BITS = 256

# Clustering radius, measured: at 25 the 778-frame tuning set collapsed to exactly the 15 distinct
# screens a human confirmed. Lower over-splits (one screen becomes two rows); higher merges two
# genuinely different screens into one.
CLUSTER_HAMMING = 25

# A cluster whose nearest node fingerprint is within this distance is that node, not an unknown.
# Deliberately tighter than the cluster radius: a cluster is a group of similar frames, so its
# centre can drift further from any single node than one frame would.
KNOWN_HAMMING = 25

FRAME_SUFFIXES = ('.png', '.jpg', '.jpeg')

# Directories that hold derived images rather than captures. The archive contains several:
# hot/thumbnails/, thumbnails/, and capture_XXXXXX_thumbnail.jpg inside them.
#
# Scanning them was a real defect, not a harmless extra. They are the NEWEST files (the archiver
# writes them continuously), and find_frames sorts by mtime and then truncates to --limit, so with
# --limit 3000 they made up the entire newest slice. 47 of 305 live rows were thumbnails. Some
# are unreadable at that size, and every thumbnail of a frame that is also in captures/ is the
# same screen counted a second time.
SKIP_DIR_PARTS = ('/thumbnails/', '/thumbnails')
SKIP_NAME_MARKERS = ('_thumbnail',)


def _is_derived_image(path: str) -> bool:
    """True for a thumbnail rather than a capture."""
    normalised = path.replace('\\', '/')
    if any(part in normalised for part in SKIP_DIR_PARTS):
        return True
    base = os.path.basename(normalised).lower()
    return any(marker in base for marker in SKIP_NAME_MARKERS)


# --------------------------------------------------------------------------- #
# frame discovery
# --------------------------------------------------------------------------- #
def find_frames(capture_root: str, ui: str, limit: Optional[int] = None,
                window_minutes: Optional[int] = None) -> List[str]:
    """Frame paths under ``<capture_root>/<capture_dir>``, newest first.

    ``capture_dir`` is the on-disk directory (``capture4``), which is NOT the interface name
    (``stb_tv``) — the archive is named per device slot while the tree is named per interface.

    Ordered by modification time: the archiver rotates directories, and "newest first" is what
    makes a scan useful — the screens a device is showing now are the ones worth naming.

    Thumbnails are skipped. See _is_derived_image for why including them corrupted the result.

    ``window_minutes`` bounds the scan to recent time, and is not an optimisation. A device
    showing broadcast footage shows a different promo slate every few minutes, so a scan spread
    over a whole archive finds hundreds of genuinely distinct images and reports every one of
    them as an unknown screen. The operator wants the screens the device shows *now*, which is a
    short window.

    No striding here on purpose: callers stride a *sample* for clustering, but motion has to be
    measured on contiguous frames, so both views of the list are needed.
    """
    import glob

    base = os.path.join(capture_root, ui)
    if not os.path.isdir(base):
        print(f'[scan] no capture directory at {base}')
        return []

    found: List[Tuple[float, str]] = []
    cutoff = None
    if window_minutes:
        cutoff = time.time() - window_minutes * 60
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            if name.lower().endswith(FRAME_SUFFIXES):
                path = os.path.join(dirpath, name)
                if _is_derived_image(path):
                    continue
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if cutoff is not None and mtime < cutoff:
                    continue
                found.append((mtime, path))
    found.sort(reverse=True)

    if limit:
        found = found[:limit]
    return [p for _mtime, p in found]


def contiguous_window(all_frames: Sequence[str], representative: str,
                      size: int) -> List[str]:
    """The frames immediately AFTER ``representative`` in time order.

    Motion must be measured on frames the device produced seconds apart. Taking the next entries
    of a *strided* sample instead pairs frames that are twenty minutes apart, and every
    comparison lands in the ambiguous band: the scan then reports every screen as "motion
    unclear" and the content filter never fires.
    """
    try:
        idx = all_frames.index(representative)
    except ValueError:
        return [representative] if representative else []
    window = list(all_frames[idx:idx + size])
    if len(window) < size and idx > 0:
        # Near the end of the list: take what came before rather than return too short a window.
        window = list(all_frames[max(0, idx - (size - len(window))):idx]) + window
    return window


# --------------------------------------------------------------------------- #
# clustering
# --------------------------------------------------------------------------- #
def cluster_by_dhash(hashes: Sequence[Tuple[str, str]], radius: int = CLUSTER_HAMMING
                     ) -> List[Dict[str, Any]]:
    """Greedy single-pass clustering: a frame joins the first cluster within ``radius``.

    Greedy, not hierarchical. It is O(n·k) over clusters rather than O(n²), and on this data the
    result was checked by eye against the hand-labelled tuning set, which found the same 15
    screens. First-seen wins as the centre, so the representative is a real frame rather than a
    synthetic average that may not correspond to anything the device ever showed.
    """
    clusters: List[Dict[str, Any]] = []
    for path, h in hashes:
        placed = False
        for cluster in clusters:
            if dhash_hamming(cluster['dhash'], h) <= radius:
                cluster['frames'].append(path)
                placed = True
                break
        if not placed:
            clusters.append({'dhash': h, 'frames': [path]})
    return clusters


# --------------------------------------------------------------------------- #
# motion -> content_state
# --------------------------------------------------------------------------- #
def changed_pct_series(images: Sequence[np.ndarray]) -> List[float]:
    """Fraction of pixels differing between consecutive frames, in percent.

    Same question the freeze detector asks, computed here on grayscale so it costs one resize
    per frame and no OCR. content_state() consumes these unchanged.
    """
    out: List[float] = []
    prev = None
    for img in images:
        gray = _gray(img)
        if prev is not None and prev.shape == gray.shape:
            diff = cv2_diff(prev, gray)
            out.append(diff)
        prev = gray
    return out


def cv2_diff(a: np.ndarray, b: np.ndarray, threshold: int = 12) -> float:
    import cv2

    a8 = cv2.resize(a, (160, 90), interpolation=cv2.INTER_AREA)
    b8 = cv2.resize(b, (160, 90), interpolation=cv2.INTER_AREA)
    delta = cv2.absdiff(a8, b8)
    _th, mask = cv2.threshold(delta, threshold, 255, cv2.THRESH_BINARY)
    return float(cv2.countNonZero(mask)) / float(mask.size) * 100.0


def _gray(img: np.ndarray) -> np.ndarray:
    import cv2

    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


# --------------------------------------------------------------------------- #
# the scan
# --------------------------------------------------------------------------- #
def slugify(text: str, max_words: int = 4) -> str:
    """Lowercase snake_case from free text, capped at a few words.

    Node labels have to be short and consistent -- the existing convention is
    menu_submenu / popup_A / splashscreen_1. A whole sentence would produce
    "this_is_the_home_screen_of_the_set_top_box", which nobody can scan in a table.
    """
    import re as _re

    words = _re.findall(r'[A-Za-z0-9]+', (text or '').lower())
    stop = {'the', 'a', 'an', 'of', 'on', 'in', 'is', 'and', 'for', 'to', 'with', 'this', 'that'}
    kept = [w for w in words if w not in stop][:max_words]
    return '_'.join(kept) or 'unknown'


def propose_name(dom: Dict[str, Any], screen_type: Optional[str]) -> str:
    """A node label from vision.dom output.

    Uses the returned screen_type as the prefix when it is one we recognise, so labels sort into
    families the way the existing tree does (nav_row_*, dialog_*, overlay_*). Anything else falls
    back to the prefix being omitted rather than inventing a category.
    """
    known = {'nav_row', 'dialog', 'overlay', 'keyboard', 'content', 'app_launcher', 'player'}
    summary = (dom.get('screen_summary') or '').strip()
    prefix = screen_type if screen_type in known else None
    body = slugify(summary) if summary else ''
    # The summary usually restates the type -- "Subscription expired dialog" with screen_type
    # 'dialog' would otherwise become dialog_subscription_expired_dialog.
    if prefix and body.endswith(f'_{prefix}'):
        body = body[: -(len(prefix) + 1)]
    elif prefix and body == prefix:
        body = ''
    if prefix and body:
        return f'{prefix}_{body}'
    return body or prefix or 'unknown_screen'


def classify_with_vision_dom(local_path: str, team_id: str) -> Dict[str, Any]:
    """Module-level wrapper around the LLM-driven screen classifier.

    Returns the full vision.dom dict (screen_type, screen_summary, labels,
    regions, ...).  Used by both this CLI scan and the auto-classify
    scheduler (backend_server/scripts/auto_classify_unknowns.py) so a
    propose-name call has exactly one definition.

    The model's profile/timing metadata is stripped (`_dom_meta`) — that
    is bookkeeping, not screen identity — so the stored `dom` column on
    userinterface_unknown_screens contains the screen description only.
    """
    from backend_host.src.services.ai_exploration.dom_generator import generate_dom
    try:
        dom = generate_dom(local_path, team_id=team_id)
        dom.pop('_dom_meta', None)
        return dom
    except Exception as exc:
        # Never raise: the scheduler's call site needs to keep going
        # through every candidate even if one image fails to load.
        print(f'[unknown_screen_scan.classify_with_vision_dom] {local_path}: {exc}')
        return {'screen_type': None, 'screen_summary': '', 'labels': [],
                'error': str(exc)}


class UnknownScreenScan:
    def __init__(self, args):
        self.args = args
        self.helpers = None
        self.named = 0
        self.all_frames: List[str] = []
        self.known_dhashes: List[str] = []
        self.stats: Dict[str, int] = {
            'frames_seen': 0, 'frames_read': 0, 'frames_unreadable': 0,
            'clusters': 0, 'known': 0, 'special': 0, 'content': 0, 'unknown': 0,
        }

    def load_helpers(self):
        """ImageHelpers gives us both classify_special_state and compute_fingerprint.

        Its constructor takes captures_path and av_controller. Neither is used by the two methods
        here -- both take an already-loaded image -- so av_controller is passed as None rather than
        standing up a controller this offline scan has no use for.
        """
        if self.helpers is not None:
            return self.helpers
        from backend_host.src.controllers.verification.image_helpers import ImageHelpers
        self.helpers = ImageHelpers(self.args.capture_root, None)
        return self.helpers

    def load_known_hashes(self) -> List[str]:
        """dHashes of every node already in this interface's tree.

        Read straight from the database: the host already holds the service-role key, so this
        needs no new endpoint and no round trip through the server.
        """
        if self.known_dhashes:
            return self.known_dhashes
        try:
            from shared.src.lib.utils.supabase_utils import get_supabase_client
            supabase = get_supabase_client()
            if supabase is None:
                print('[scan] no Supabase client — cannot tell known screens from unknown ones; '
                      'every cluster will be reported')
                return []

            interface = (supabase.table('userinterfaces')
                         .select('id')
                         .eq('name', self.args.userinterface)
                         .eq('team_id', self.args.team_id)
                         .limit(1)
                         .execute())
            if not interface.data:
                print(f'[scan] interface {self.args.userinterface} not found — '
                      'every cluster will be reported')
                return []

            trees = (supabase.table('navigation_trees')
                     .select('id')
                     .eq('userinterface_id', interface.data[0]['id'])
                     .eq('team_id', self.args.team_id)
                     .execute())
            tree_ids = [t['id'] for t in (trees.data or [])]
            if not tree_ids:
                return []

            nodes = (supabase.table('nodes')
                     .select('node_id,data')
                     .eq('team_id', self.args.team_id)
                     .in_('tree_id', tree_ids)
                     .execute())
            for node in (nodes.data or []):
                data = node.get('data') or {}
                fp = data.get('fingerprint') or {}
                h = fp.get('dhash') or fp.get('dhash_hex')
                if h:
                    self.known_dhashes.append(h)
            print(f'[scan] {len(self.known_dhashes)} node fingerprints loaded from '
                  f'{len(tree_ids)} tree(s)')
        except Exception as exc:                       # a scan must not die on a DB hiccup
            print(f'[scan] could not load known fingerprints: {exc}')
        return self.known_dhashes

    def is_known(self, dhash: str) -> bool:
        return any(dhash_hamming(dhash, known) <= KNOWN_HAMMING
                   for known in self.known_dhashes)

    def read_frame(self, path: str, count: bool = True) -> Optional[np.ndarray]:
        import cv2

        try:
            img = cv2.imread(path, cv2.IMREAD_COLOR)
        except Exception:
            img = None
        if img is None:
            self.stats['frames_unreadable'] += 1
            return None
        # Frames are re-read when a cluster is classified (the representative and the motion
        # window are read again). Counting those too made the summary report more reads than the
        # scan actually started from, which reads as a bug in the archive.
        if count:
            self.stats['frames_read'] += 1
        return img

    def run(self) -> List[Dict[str, Any]]:
        args = self.args
        capture_dir = args.capture_dir or args.userinterface
        all_frames = find_frames(args.capture_root, capture_dir,
                                 limit=args.limit,
                                 window_minutes=args.window_minutes)
        self.all_frames = all_frames
        if not all_frames:
            print('[scan] nothing to scan')
            return []
        window_note = f' (last {args.window_minutes} min)' if args.window_minutes else ''
        print(f'[scan] {len(all_frames)} frames under {args.capture_root}/{capture_dir}{window_note}')

        # Stride for CLUSTERING only. Motion is measured on contiguous frames via
        # contiguous_window(), never on neighbours of this strided sample.
        sample = all_frames[::args.stride] if args.stride > 1 else all_frames
        self.stats['frames_seen'] = len(sample)
        print(f'[scan] clustering on every {args.stride}th frame: {len(sample)} of {len(all_frames)}')

        # --- pass 1: hash every frame and cluster -------------------------------
        hashes: List[Tuple[str, str]] = []
        for path in sample:
            img = self.read_frame(path)
            if img is None:
                continue
            gray = _gray(img)
            hashes.append((path, dhash_hex(gray, DHASH_GRID, DHASH_BITS)))

        clusters = cluster_by_dhash(hashes)
        self.stats['clusters'] = len(clusters)
        print(f'[scan] {len(hashes)} frames -> {len(clusters)} distinct screens')

        self.load_known_hashes()

        # --- pass 2: classify each cluster --------------------------------------
        findings: List[Dict[str, Any]] = []
        for cluster in clusters:
            finding = self.classify_cluster(cluster)
            if finding:
                findings.append(finding)

        unknown = sum(1 for f in findings if f['classification'] == 'unknown')
        content = sum(1 for f in findings if f['classification'] == 'content')
        self.stats['unknown'] = unknown
        self.stats['content'] = content
        return findings

    def classify_cluster(self, cluster: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        args = self.args
        members = cluster['frames']
        representative = members[0]

        # Motion first: it is cheap and needs no extra files, and it is the single strongest
        # signal for separating footage from UI.
        # Contiguous frames from the FULL list, not the strided sample — see
        # contiguous_window() for why this distinction is the whole ballgame.
        window = contiguous_window(self.all_frames, representative, args.motion_window)
        images = []
        for path in window:
            img = self.read_frame(path, count=False)
            if img is not None:
                images.append(img)
        series = changed_pct_series(images)
        content_verdict = scv.content_state(series)

        img = self.read_frame(representative, count=False)
        if img is None:
            return None

        # Not a screen at all: black or no signal. Kept out of the list entirely — there is
        # nothing for an operator to name.
        special = self.special_state(img)
        if special:
            self.stats['special'] += 1
            return None

        if self.is_known(cluster['dhash']):
            self.stats['known'] += 1
            return None

        fingerprint = None
        try:
            fingerprint = self.load_helpers().compute_fingerprint(img)
        except Exception as exc:
            print(f'[scan] fingerprint failed for {representative}: {exc}')

        classification = 'content' if content_verdict == 'video' else 'unknown'

        # Name only the UNKNOWN clusters. Asking the model what a promo slate is costs an AI call
        # per screen to learn something we already decided -- it is content.
        dom = self.name_screen(representative, classification)
        return {
            'userinterface': args.userinterface,
            'device_model': args.device_model,
            'cluster_dhash': cluster['dhash'],
            'classification': classification,
            'frame_count': len(members),
            'signal': self.signal_text(content_verdict, series),
            'description': self.describe(classification, content_verdict, series, dom),
            'image_url': self.publish_still(img, representative, cluster['dhash']),
            'example_frames': members[:5],
            'fingerprint': fingerprint,
            'screen_type': dom.get('screen_type') if dom else None,
            'proposed_name': propose_name(dom, dom.get('screen_type')) if dom else None,
            'dom': dom,
        }

    def name_screen(self, local_path: str, classification: str) -> Optional[Dict[str, Any]]:
        """Ask vision.dom what this screen is, and keep the DOM alongside the name.

        Opt-in: every call is a real model request, so it is not something a scan should do by
        surprise. Bounded by --name-limit, which stops counting at the cap rather than selecting
        the best candidates — clusters are visited in discovery order, not ranked by frame_count.
        """
        if not self.args.name_screens or classification != 'unknown':
            return None
        if self.named >= self.args.name_limit:
            return None
        try:
            from backend_host.src.services.ai_exploration.dom_generator import generate_dom

            self.named += 1
            dom = generate_dom(local_path, team_id=self.args.team_id)
            dom.pop('_dom_meta', None)      # model/profile/timing is not part of the screen
            print(f'[scan] named: {dom.get("screen_type")} / '
                  f'{(dom.get("screen_summary") or "")[:60]}')
            return dom
        except Exception as exc:
            self.named += 1
            print(f'[scan] naming failed for {local_path}: {exc}')
            return None

    def publish_still(self, img, local_path: str, dhash: str) -> Optional[str]:
        """Upload the representative frame and return its R2 object key.

        The key is what gets stored, not a filesystem path and not a presigned URL. The host path
        means nothing to a browser — /var/www/html/stream/... is a 404 from the app's origin — and a
        presigned URL expires, so a row that outlived it would show a broken thumbnail forever.
        The frontend resolves the key through useR2Url, which mints a fresh signed URL per view.

        Keyed by the cluster hash, so re-scanning overwrites rather than accumulating copies.
        Returns None on failure: a row with no thumbnail is still a useful row, and losing the
        whole finding because one upload failed would be the wrong trade.
        """
        if not self.args.upload_stills:
            return None
        try:
            from shared.src.lib.utils.cloudflare_utils import upload_navigation_screenshot

            name = f'unknown_{dhash[:16]}.jpg'
            result = upload_navigation_screenshot(local_path, self.args.userinterface, name)
            if result.get('success'):
                return result.get('remote_path')
            print(f'[scan] still upload failed for {local_path}: {result.get("error")}')
        except Exception as exc:
            print(f'[scan] still upload error for {local_path}: {exc}')
        return None

    def special_state(self, img: np.ndarray) -> Optional[str]:
        try:
            return self.load_helpers().classify_special_state(img)
        except Exception:
            return None

    @staticmethod
    def signal_text(verdict: str, series: Sequence[float]) -> str:
        """Why this surfaced, in words. A report, not a filter input.

        The number quoted is the one content_state() actually decided on — the median of the last
        CONTENT_WINDOW_FRAMES values — not the median of the whole window. Reporting a different
        number from the one the verdict was based on makes the row unexplainable: it once showed
        "moving picture (2.7% frame change)" on a row classified as content, when 2.7 % is below
        the 5 % clear floor and cannot be the reason.
        """
        median = UnknownScreenScan._deciding_median(series)
        return {
            'video': f'moving picture ({median:.1f}% frame change) — filtered as content',
            'static': 'static picture, no node matched',
        }.get(verdict, f'motion unclear ({median:.1f}% frame change)')

    @staticmethod
    def _deciding_median(series: Sequence[float]) -> float:
        """The exact value content_state() decided on: median of the trailing window."""
        window = list(series)[-scv.CONTENT_WINDOW_FRAMES:]
        if not window:
            return 0.0
        ordered = sorted(window)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2.0

    @staticmethod
    def describe(classification: str, verdict: str, series: Sequence[float],
                 dom: Optional[Dict[str, Any]] = None) -> str:
        """One line saying what this screen is, shown on the row.

        Content rows are displayed to the operator so the filter can be audited rather than
        trusted. Without a description that list is an unauditable wall of thumbnails, so this
        names the evidence instead of just asserting the verdict.

        When vision.dom has already run on this screen, its summary leads. The model was asked what
        the screen is and wrote things like "Movie detail screen for 'Bad Boys: Ride or Die' with
        hero image and title" — and that was being discarded in favour of "static picture (0.0%
        frame change)", which says the same thing on every row and describes none of them. The
        motion figure is kept as a suffix because it is the evidence for the filter itself, which
        the model did not see.
        """
        median = UnknownScreenScan._deciding_median(series)
        summary = str((dom or {}).get('screen_summary') or '').strip()
        if classification == 'content':
            return (f'moving picture, {median:.1f}% of pixels changed per frame — '
                    f'broadcast or game footage, not a screen')
        if summary:
            return f'{summary} (static, {median:.1f}% frame change — no node matched)'
        return f'static picture ({median:.1f}% frame change) — no node in the tree matched it'


def post_findings(args, findings: List[Dict[str, Any]], batch_size: int = 25) -> bool:
    """POST the scan to the server, in batches.

    Batched because each row carries a full v6 fingerprint with its regions, and a wide scan can
    produce hundreds of rows. Posting them in one request built a multi-megabyte body that the
    server timed out on — and a timeout after the work is done is the worst possible failure,
    because the scan is reported as unrecorded when it may partly have landed.

    Returns False only if a batch actually failed; a partial success is reported and the scan is
    not silently declared clean.
    """
    import urllib.error
    import urllib.request

    if not args.server_url:
        print('[scan] no --server-url; nothing posted')
        return False
    url = args.server_url.rstrip('/') + '/server/userinterface/upsertUnknownScreens'
    token = os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or args.auth_token

    ok = True
    total = len(findings)
    for start in range(0, total, batch_size):
        chunk = findings[start:start + batch_size]
        # Only the LAST batch tells the server to retire. Retirement compares against everything
        # the scan saw, so it can only be judged once every batch has landed -- if it ran per
        # batch, each batch would retire the one before it and leave only the last 25 rows alive.
        is_last = start + batch_size >= total
        payload = {
            'team_id': args.team_id,
            'userinterface': args.userinterface,
            'screens': chunk,
            'retire_unseen': is_last,
        }
        if is_last:
            # Retirement compares against everything the scan saw, across all batches -- not just
            # the 25 rows in this request. Without this the server would judge the whole scan by
            # its final batch and retire every screen found in the earlier ones.
            payload['seen_dhashes'] = [str(f.get('cluster_dhash') or '').strip()
                                       for f in findings]
        body = json.dumps(payload).encode()

        req = urllib.request.Request(url, data=body,
                                     headers={'Content-Type': 'application/json'})
        # X-Auto-Sign, NOT "Authorization: Bearer". The bearer path goes to the JWT validator,
        # which rejects anything that is not a Supabase user session — the service-role key gets
        # "Invalid token" there, and the scan's findings were never recorded. See
        # docs/agent/validation/TESTING.md.
        auto_sign = os.environ.get('AUTO_SIGN_TOKEN') or args.auto_sign_token
        if auto_sign:
            req.add_header('X-Auto-Sign', auto_sign)
        else:
            token = os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or args.auth_token
            if token:
                req.add_header('Authorization', f'Bearer {token}')
            print('[scan] WARNING: no AUTO_SIGN_TOKEN in the environment; falling back to the '
                  'bearer token, which the server will reject.')
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode() or '{}')
                if not payload.get('success'):
                    ok = False
                print(f'[scan] batch {start // batch_size + 1}: '
                      f'{len(chunk)} rows -> {payload}')
        except urllib.error.HTTPError as exc:
            ok = False
            print(f'[scan] batch {start // batch_size + 1} rejected: HTTP {exc.code} {exc.reason}')
        except Exception as exc:
            ok = False
            print(f'[scan] batch {start // batch_size + 1} failed: {exc}')
            break
    return ok


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--capture-root', required=True,
                   help='directory holding per-interface capture folders')
    p.add_argument('--userinterface', required=True,
                   help='interface NAME as the database knows it, e.g. stb_tv')
    p.add_argument('--capture-dir', default=None,
                   help='on-disk directory under --capture-root, e.g. capture4. Defaults to '
                        '--userinterface. The archive is named per device slot, the tree per '
                        'interface, so these are usually different.')
    p.add_argument('--team-id', required=True)
    p.add_argument('--device-model', default=None,
                   help='carried on each finding; a screen from a device with no tree is a '
                        'different action (create a UI) than one from a known device')
    p.add_argument('--server-url', default=os.environ.get('VPT_SERVER_URL'),
                   help='e.g. http://192.168.0.102:8000')
    p.add_argument('--auto-sign-token', default=None,
                   help='defaults to $AUTO_SIGN_TOKEN. Sent as X-Auto-Sign — see '
                        'docs/agent/validation/TESTING.md')
    p.add_argument('--auth-token', default=None,
                   help='fallback bearer token ($SUPABASE_SERVICE_ROLE_KEY). The server rejects '
                        'a bearer that is not a Supabase user session, so this rarely works.')
    p.add_argument('--stride', type=int, default=5,
                   help='cluster on every Nth frame (default 5). Affects clustering only — '
                        'motion is always measured on contiguous frames.')
    p.add_argument('--window-minutes', type=int, default=240,
                   help='only scan frames from the last N minutes (default 240 = 4h). A device '
                        'showing broadcast shows a new image every few minutes, so an unbounded '
                        'scan finds hundreds of distinct frames and calls them all unknown.')
    p.add_argument('--limit', type=int, default=None, help='stop after N frames')
    p.add_argument('--motion-window', type=int, default=12,
                   help='frames per cluster used for the motion series (default 12)')
    p.add_argument('--apply', action='store_true',
                   help='POST the findings. Without this the scan only prints.')
    p.add_argument('--json', default=None, help='also write the findings to this path')
    p.add_argument('--name-screens', action='store_true',
                   help='ask vision.dom to name each UNKNOWN screen. One model call per screen, '
                        'so it costs money and takes time; off by default.')
    p.add_argument('--name-limit', type=int, default=50,
                   help='cap the number of vision.dom calls per scan (default 50)')
    p.add_argument('--no-upload-stills', dest='upload_stills', action='store_false',
                   default=True,
                   help='do not upload representative frames to R2; image_url stays empty and '
                        'the page shows a placeholder. Uploads are ON by default because a row '
                        'with no still cannot be identified by looking at it.')
    p.add_argument('--post-json', default=None, metavar='PATH',
                   help='skip the scan and POST a findings file written earlier by --json. '
                        'The scan costs minutes on a Pi and the POST can fail after all that work '
                        '(a server restart, a timeout), so re-posting must not mean re-scanning.')
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    started = time.time()

    if args.post_json:
        with open(args.post_json, encoding='utf-8') as fh:
            findings = json.load(fh)
        print(f'[scan] re-posting {len(findings)} rows from {args.post_json} (scan skipped)')
        if not args.apply:
            print('[scan] nothing sent — re-run with --apply')
            return 0
        return 0 if post_findings(args, findings) else 1

    scan = UnknownScreenScan(args)
    findings = scan.run()

    print('\n=== scan summary ===')
    for key in ('frames_seen', 'frames_read', 'frames_unreadable', 'clusters',
                'known', 'special', 'content', 'unknown'):
        print(f'  {key:18} {scan.stats[key]}')
    print(f'  elapsed            {time.time() - started:.1f}s')

    unknown = [f for f in findings if f['classification'] == 'unknown']
    if unknown:
        print(f'\n=== {len(unknown)} screen(s) with no node ===')
        for f in sorted(unknown, key=lambda r: -r['frame_count']):
            print(f"  {f['frame_count']:6d} frames  {f['signal']}")
    elif scan.stats['frames_seen'] == 0:
        print('\nNothing was scanned — no frames found. Check --capture-root and --userinterface.')
    else:
        print('\nNo unknown screens — every cluster matched a node, was a special state, or was '
              'classified as content.')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(findings, fh, indent=2)
        print(f'[scan] findings written to {args.json}')

    if args.apply:
        if not findings:
            print('[scan] nothing to post')
            return 0
        if post_findings(args, findings):
            print('[scan] posted')
        else:
            print('[scan] POST FAILED — findings were not recorded')
            return 1
    else:
        print('\n[dry run] nothing was sent. Re-run with --apply to record this.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())