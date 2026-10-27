"""Unknown-screen scan + storage (features/.../unknown_screen_scan.py, shared/.../unknown_screens_db.py).

Pure where it can be: clustering, motion classification and the resolve guard are all testable
without a database, a capture archive or a network. The Supabase client is faked rather than
mocked at the HTTP layer, so these assert on the calls we actually make.

Run: pytest tests/backend_host/test_unknown_screen_scan.py -v
"""
import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, '..', '..'))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from features.avq.backend_host.localize import unknown_screen_scan as scan_mod  # noqa: E402
from shared.src.lib.ai import screen_state_cv as scv                            # noqa: E402
from shared.src.lib.utils.image_hash import dhash_hex, dhash_hamming           # noqa: E402

pytestmark = pytest.mark.unit


def _args(**over):
    base = dict(capture_root='/tmp/does-not-matter', userinterface='stb-testop', auto_sign_token=None,
                team_id='00000000-0000-0000-0000-000000000000', device_model=None,
                server_url=None, auth_token=None, stride=1, limit=None,
                motion_window=12, apply=False, json=None, upload_stills=True,
                name_screens=False, name_limit=50, window_minutes=240)
    base.update(over)
    return SimpleNamespace(**base)


def _frame(seed: int, w=320, h=180, value=80):
    """A deterministic 'frame'. Different seeds look like different screens."""
    rng = np.random.RandomState(seed)
    img = np.full((h, w, 3), value, np.uint8)
    noise = rng.randint(0, 255, (h // 2, w // 2, 3), dtype=np.uint8)
    img[: h // 2, : w // 2] = noise
    return img


def _hash_of(img):
    gray = scan_mod._gray(img)
    return dhash_hex(gray, scan_mod.DHASH_GRID, scan_mod.DHASH_BITS)


# ---- clustering ---------------------------------------------------------------- #

def test_identical_frames_collapse_into_one_cluster():
    hashes = [('a.png', 'ffff0000ffff0000')] * 5
    clusters = scan_mod.cluster_by_dhash(hashes)
    assert len(clusters) == 1
    assert clusters[0]['frames'] == ['a.png'] * 5


def test_dissimilar_frames_stay_apart():
    # A dHash of all zeros and all ones differ in every bit.
    hashes = [('a.png', '0' * 64), ('b.png', 'f' * 64)]
    assert len(scan_mod.cluster_by_dhash(hashes)) == 2


def test_clustering_is_first_seen_wins_so_the_representative_is_a_real_frame():
    hashes = [('first.png', 'abcd'), ('second.png', 'abcd')]
    clusters = scan_mod.cluster_by_dhash(hashes, radius=scan_mod.CLUSTER_HAMMING)
    assert clusters[0]['frames'][0] == 'first.png'


def test_cluster_radius_is_wired_to_the_measured_value():
    """25 was measured: the 778-frame tuning set collapsed to exactly 15 screens at this radius."""
    assert scan_mod.CLUSTER_HAMMING == 25


def test_clustering_is_greedy_first_match_not_nearest():
    """A frame within range of two clusters joins the first. Documented, and pinned so a
    switch to nearest-match is a deliberate change rather than an accident."""
    hashes = [('seed1', '0000000000000000'), ('seed2', 'ffffffffffffffff'),
              ('near-both', '00000000000000f0')]
    clusters = scan_mod.cluster_by_dhash(hashes, radius=8)
    joined = [c['frames'][-1] for c in clusters if len(c['frames']) > 1]
    assert joined == ['near-both']
    assert len(clusters) == 2


# ---- motion -> content_state ---------------------------------------------------- #

def test_motion_series_is_empty_for_a_single_frame():
    assert scan_mod.changed_pct_series([_frame(1)]) == []


def test_motion_series_reports_near_zero_for_identical_frames():
    series = scan_mod.changed_pct_series([_frame(1), _frame(1), _frame(1)])
    assert series == [0.0, 0.0]


def test_a_moving_picture_reads_as_content_and_a_drawn_screen_as_unknown():
    """The whole point of the scan: separate footage from unrecognised UI."""
    # A screen that has finished drawing repeats. Note it must be the SAME frame: a different
    # frame is a different screen, and content_state() is being asked about motion, not identity.
    # Four frames, because N frames produce N-1 diffs and the window is three of them.
    drawn = scan_mod.changed_pct_series([_frame(1)] * 4)
    assert drawn == [0.0, 0.0, 0.0]
    assert scv.content_state(drawn) == 'static'

    # Two half-black / half-white frames alternate: every pixel differs each step.
    a = np.zeros((90, 160, 3), np.uint8)
    b = np.full((90, 160, 3), 255, np.uint8)
    moving = scan_mod.changed_pct_series([a, b, a, b])
    assert scv.content_state(moving) == 'video'


def test_motion_between_the_two_floors_abstains_rather_than_guessing():
    """A screen part-way through a redraw lands in the band. 'unknown' is the honest answer,
    and it is the same band that protects a real redraw from being called live video."""
    partial = np.zeros((90, 160, 3), np.uint8)
    partial[:, :80] = 255            # ~half the frame changes: between 0.8% and 5%
    series = scan_mod.changed_pct_series([np.zeros((90, 160, 3), np.uint8), partial,
                                          np.zeros((90, 160, 3), np.uint8)])
    assert scv.content_state(series) == 'unknown'


# ---- known vs unknown ----------------------------------------------------------- #

def test_a_cluster_matching_a_node_fingerprint_is_not_reported_unknown():
    scan = scan_mod.UnknownScreenScan(_args())
    scan.known_dhashes = ['ffff0000ffff0000']
    assert scan.is_known('ffff0000ffff0000') is True
    assert scan.is_known('0000000000000000') is False


def test_with_no_node_fingerprints_everything_is_reported_rather_than_silently_dropped():
    """Failing open matters: a DB hiccup must not make real screens look already-known."""
    scan = scan_mod.UnknownScreenScan(_args())
    scan.known_dhashes = []
    assert scan.is_known('ffff0000ffff0000') is False


# ---- signal text ----------------------------------------------------------------- #

def test_signal_text_describes_the_verdict_rather_than_dumping_numbers():
    assert 'moving picture' in scan_mod.UnknownScreenScan.signal_text('video', [20.0])
    assert 'static' in scan_mod.UnknownScreenScan.signal_text('static', [0.0])
    assert 'unclear' in scan_mod.UnknownScreenScan.signal_text('unknown', [2.0])


# ---- db: resolve is guarded on pending ------------------------------------------- #

class _FakeResult:
    def __init__(self, data, count=None):
        self.data = data
        self.count = len(data) if count is None else count


class _FakeTable:
    def __init__(self, owner):
        self.owner = owner

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        self.owner.filters.append(('eq', a))
        return self

    def is_(self, *a, **k):
        self.owner.filters.append(('not_is_' if self.owner.negated else 'is_', a))
        self.owner.negated = False
        return self

    # In supabase-py 2.x `.not_` is a PROPERTY returning a builder, not a method. Modelling it as
    # a callable is what let the real bug through: the production code called it as a method, the
    # test's fake happily accepted it, and the assertion below "passed" while production raised
    # TypeError and swallowed it into retired: 0.
    @property
    def not_(self):
        self.owner.negated = True
        return self

    def in_(self, *a, **k):
        self.owner.filters.append(('not_in_' if self.owner.negated else 'in_', a))
        self.owner.negated = False
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, payload):
        self.owner.updated.append(payload)
        return self

    def insert(self, payload):
        self.owner.inserted.append(payload)
        return self

    def execute(self):
        self.owner.executions += 1
        if self.owner.raises:
            raise RuntimeError('boom')
        return _FakeResult(self.owner.result_data)


class _FakeSupabase:
    def __init__(self, result_data=None, raises=False):
        self.updated = []
        self.inserted = []
        self.filters = []
        self.executions = 0
        self.result_data = result_data if result_data is not None else []
        self.negated = False
        self.raises = raises

    def table(self, name):
        self.table_name = name
        return _FakeTable(self)


def test_resolve_only_touches_a_pending_row(monkeypatch):
    """The status guard is what stops a double-click on Accept creating two nodes."""
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[{'id': 'x'}])
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)

    assert db.resolve_unknown_screen('team', 'row', 'accepted', accepted_node_id='n1') is True
    # status='pending' must be among the WHERE clauses, not just team and id
    eq_pairs = [a for kind, a in fake.filters if kind == 'eq']
    assert ('status', 'pending') in eq_pairs
    assert ('team_id', 'team') in eq_pairs
    assert ('id', 'row') in eq_pairs


def test_resolve_reports_failure_when_the_row_was_not_pending(monkeypatch):
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[])          # PostgREST returns no rows when nothing matched
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)
    assert db.resolve_unknown_screen('team', 'row', 'accepted') is False


def test_resolve_requires_team_and_row(monkeypatch):
    from shared.src.lib.database import unknown_screens_db as db

    monkeypatch.setattr(db, 'get_supabase', lambda: _FakeSupabase())
    assert db.resolve_unknown_screen('', 'row', 'accepted') is False
    assert db.resolve_unknown_screen('team', '', 'accepted') is False


def test_row_normalisation_fills_the_defaults_the_page_relies_on():
    from shared.src.lib.database.unknown_screens_db import _row_to_dict

    row = _row_to_dict({'id': 'r', 'userinterface': 'stb-testop'})
    assert row['classification'] == 'unknown'
    assert row['status'] == 'pending'
    assert row['frame_count'] == 0
    assert row['example_frames'] == []


def test_scan_fields_do_not_include_a_status_so_a_scan_cannot_resolve_a_row():
    """A host scan writes findings; it must not be able to accept or dismiss on its own."""
    from shared.src.lib.database.unknown_screens_db import _SCAN_FIELDS

    assert 'status' not in _SCAN_FIELDS
    assert 'accepted_node_id' not in _SCAN_FIELDS
    assert 'proposed_name' in _SCAN_FIELDS        # naming is the scan's job


# ---- arg parsing: dry run is the default ------------------------------------------- #

def test_the_scan_is_a_dry_run_unless_apply_is_given():
    args = scan_mod.parse_args(['--capture-root', '/tmp/x', '--userinterface', 'u',
                                '--team-id', 't'])
    assert args.apply is False


def test_stride_defaults_to_five_because_the_archiver_already_stores_at_five():
    args = scan_mod.parse_args(['--capture-root', '/tmp/x', '--userinterface', 'u',
                                '--team-id', 't'])
    assert args.stride == 5

# ---- include_resolved means pending, not "not dismissed" -------------------------- #

def test_default_list_returns_pending_rows_only(monkeypatch):
    """It used to return anything that was not dismissed, so an accepted row still sat under a
    heading called 'Needs a name' and disagreed with getUnknownCounts."""
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[])
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)
    db.list_unknown_screens('team', userinterface='stb-testop')

    eq_pairs = [a for kind, a in fake.filters if kind == 'eq']
    assert ('status', 'pending') in eq_pairs
    assert ('userinterface', 'stb-testop') in eq_pairs
    assert ('team_id', 'team') in eq_pairs


def test_include_resolved_drops_the_pending_filter(monkeypatch):
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[])
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)
    db.list_unknown_screens('team', userinterface='stb-testop', include_resolved=True)

    eq_pairs = [a for kind, a in fake.filters if kind == 'eq']
    assert ('status', 'pending') not in eq_pairs


# ---- description ------------------------------------------------------------------ #

def test_a_content_row_carries_a_description(monkeypatch):
    """Content rows are shown so the filter can be audited. Without a description that list is
    an unauditable wall of thumbnails."""
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[])
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)
    db.upsert_unknown_screens('team', 'stb-testop', [{'cluster_dhash': 'abc', 'description': 'live TV'}])
    assert fake.updated == []                       # no existing row, so it inserts instead

    from shared.src.lib.database.unknown_screens_db import _SCAN_FIELDS
    assert 'description' in _SCAN_FIELDS


def test_a_failed_upload_does_not_overwrite_a_stored_image_url(monkeypatch):
    """A re-scan whose R2 upload failed must not destroy a still a previous scan already
    produced. Real defect: a wrong-user run wiped the Star Trek and Bad Boys thumbnails."""
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[{'id': 'existing'}])     # row already exists
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)
    db.upsert_unknown_screens(
        'team', 'stb-testop',
        [{'cluster_dhash': 'abc', 'image_url': None, 'description': 'still up'}],
    )
    assert fake.updated, 'existing row should be updated'
    assert 'image_url' not in fake.updated[0]                 # the field was dropped
    assert fake.updated[0].get('description') == 'still up'   # other fields still update


def test_a_successful_upload_replaces_the_stored_image_url(monkeypatch):
    """The fix above is update-only: a fresh, non-None image_url must still overwrite, otherwise
    a re-clustered screen would keep its old still forever."""
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[{'id': 'existing'}])
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)
    db.upsert_unknown_screens(
        'team', 'stb-testop',
        [{'cluster_dhash': 'abc', 'image_url': 'r2://new-still.jpg'}],
    )
    assert fake.updated[0].get('image_url') == 'r2://new-still.jpg'


def test_a_new_row_still_inserts_a_null_image_url(monkeypatch):
    """A first-time scan with a failed upload is a real screen, just one with no thumbnail yet.
    The NULL must be inserted so the row exists and the next scan can fill the column in."""
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[])          # no existing row → insert path
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)
    result = db.upsert_unknown_screens(
        'team', 'stb-testop',
        [{'cluster_dhash': 'abc', 'image_url': None, 'description': 'first sighting'}],
    )
    assert result['inserted'] == 1
    assert result['updated'] == 0
    assert result['errors'] == 0


def test_describe_names_the_evidence_for_content_rows():
    text = scan_mod.UnknownScreenScan.describe('content', 'video', [20.11, 20.11, 20.11])
    assert 'moving picture' in text
    assert '20.1' in text
    assert 'broadcast or game footage' in text


def test_describe_for_an_unknown_row_says_why_it_surfaced():
    text = scan_mod.UnknownScreenScan.describe('unknown', 'static', [0.09, 0.09, 0.09])
    assert 'no node in the tree matched' in text


def test_describe_leads_with_what_the_model_said_the_screen_was():
    """vision.dom was already being called and its answer thrown away for "static picture (0.0%
    frame change)" -- the identical string on every row, describing none of them. It wrote things
    like "Movie detail screen for 'Bad Boys: Ride or Die' with hero image and title"."""
    dom = {'screen_summary': "Movie detail screen for 'Bad Boys: Ride or Die' with hero image"}
    text = scan_mod.UnknownScreenScan.describe('unknown', 'static', [0.0, 0.0, 0.0], dom)

    assert text.startswith("Movie detail screen for 'Bad Boys: Ride or Die'")
    assert 'static' in text, 'the motion evidence for the filter is kept'


def test_describe_falls_back_when_there_is_no_dom():
    """--name-screens is opt-in, so most rows have no dom. They must not render 'None'."""
    text = scan_mod.UnknownScreenScan.describe('unknown', 'static', [0.09, 0.09, 0.09], None)
    assert 'no node in the tree matched' in text
    assert 'None' not in text


def test_content_rows_are_not_relabelled_from_the_dom():
    """A content row's description is the audit trail for the filter. Overwriting it with the
    model's guess would remove the evidence that the motion filter rejected it."""
    dom = {'screen_summary': 'A football match'}
    text = scan_mod.UnknownScreenScan.describe('content', 'video', [20.11, 20.11, 20.11], dom)
    assert 'broadcast or game footage' in text


# ---- every route reads params the same way ------------------------------------------ #

def test_all_four_routes_share_one_param_reader():
    """The read routes accepted body-or-query while the action routes read the body only, so the
    established 'POST with params in the query string' pattern silently 400'd on Accept."""
    import inspect

    from backend_server.src.routes import server_userinterface_routes as routes

    assert hasattr(routes, '_param')
    for view in (routes.get_unknown_screens, routes.get_unknown_counts,
                 routes.accept_unknown_screen, routes.dismiss_unknown_screen):
        src = inspect.getsource(view)
        # no route may reach into request.args directly any more
        assert 'request.args' not in src, f'{view.__name__} still reads request.args directly'
        assert '_param(' in src, f'{view.__name__} does not use the shared reader'


# ---- the capture dir and the interface name are different things ------------------- #

def test_capture_dir_defaults_to_the_interface_name():
    args = scan_mod.parse_args(['--capture-root', '/tmp/x', '--userinterface', 'stb-testop',
                                '--team-id', 't'])
    assert args.capture_dir is None
    args = scan_mod.parse_args(['--capture-root', '/tmp/x', '--userinterface', 'stb-testop',
                                '--team-id', 't', '--capture-dir', 'capture4'])
    assert args.capture_dir == 'capture4'


def test_a_capture_dir_that_does_not_exist_is_reported_not_crashed(capsys):
    args = scan_mod.parse_args(['--capture-root', '/nonexistent-root', '--userinterface', 'stb-testop',
                                '--team-id', 't', '--capture-dir', 'capture4'])
    assert scan_mod.find_frames(args.capture_root, args.capture_dir) == []


# ---- motion must use contiguous frames -------------------------------------------- #

def test_contiguous_window_takes_the_frames_immediately_after_the_representative():
    """The bug this pins: motion was measured over neighbours of a STRIDED sample, pairing
    frames twenty minutes apart. Every comparison then landed in the ambiguous band and the
    content filter never fired — 317 of 320 rows came back 'motion unclear'."""
    frames = [f'f{i:03d}.jpg' for i in range(20)]
    window = scan_mod.contiguous_window(frames, 'f005.jpg', 4)
    assert window == ['f005.jpg', 'f006.jpg', 'f007.jpg', 'f008.jpg']


def test_contiguous_window_preserves_the_order_it_was_given():
    """run() must hand this the FULL list, not the strided sample. The returned window is
    always consecutive in whatever list it is given, so the correctness of the result depends
    entirely on the caller passing the unstrided one."""
    frames = [f'f{i:03d}.jpg' for i in range(20)]
    full = scan_mod.contiguous_window(frames, 'f010.jpg', 3)
    assert full == ['f010.jpg', 'f011.jpg', 'f012.jpg']

    strided = frames[::5]                     # f000, f005, f010, f015
    window = scan_mod.contiguous_window(strided, 'f010.jpg', 2)
    assert window == ['f010.jpg', 'f015.jpg']        # what the strided sample would have given
    assert window != full                            # which is why run() must not pass it


def test_contiguous_window_near_the_end_reaches_backwards():
    frames = [f'f{i:03d}.jpg' for i in range(5)]
    window = scan_mod.contiguous_window(frames, 'f004.jpg', 4)
    assert len(window) == 4
    assert 'f004.jpg' in window


def test_contiguous_window_of_an_unknown_path_is_just_that_path():
    assert scan_mod.contiguous_window(['a.jpg'], 'zzz.jpg', 3) == ['zzz.jpg']


def test_the_scan_bounds_itself_in_time_by_default():
    """Broadcast shows a new image every few minutes; an unbounded scan finds hundreds of
    genuinely distinct frames and reports every one as an unknown screen."""
    args = scan_mod.parse_args(['--capture-root', '/tmp/x', '--userinterface', 'u',
                                '--team-id', 't'])
    assert args.window_minutes == 240


def test_posts_with_the_auto_sign_header_not_a_bearer(monkeypatch):
    """The server's JWT validator rejects a bearer that is not a Supabase user session, so the
    service-role key got 'Invalid token' and the findings were silently not recorded."""
    import inspect

    src = inspect.getsource(scan_mod.post_findings)
    assert 'X-Auto-Sign' in src
    assert 'AUTO_SIGN_TOKEN' in src


# ---- the displayed number must be the one the verdict used ------------------------ #

def test_the_reported_median_is_the_one_content_state_decided_on():
    """It once reported the median of the whole 12-frame series while the verdict used only the
    trailing 3 — so a row could read "moving picture (2.7% frame change) — filtered as content",
    and 2.7 % is below the 5 % clear floor and cannot be the reason."""
    series = [99.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0, 2.7, 2.7, 6.0]
    median = scan_mod.UnknownScreenScan._deciding_median(series)
    assert median == scan_mod.UnknownScreenScan._deciding_median(series[-scv.CONTENT_WINDOW_FRAMES:])
    # the whole-series median would be ~94; the deciding window is ~2.7
    assert median < scv.CONTENT_CLEAR_PCT
    assert sorted(series)[len(series) // 2] > scv.CONTENT_CLEAR_PCT


def test_deciding_median_of_an_empty_series_is_zero():
    assert scan_mod.UnknownScreenScan._deciding_median([]) == 0.0


# ---- a failed POST must not cost another scan -------------------------------------- #

def test_post_json_lets_a_stale_findings_file_be_reposted_without_rescanning(tmp_path):
    path = tmp_path / 'findings.json'
    path.write_text('[{"cluster_dhash": "abc", "classification": "unknown"}]')
    args = scan_mod.parse_args(['--capture-root', '/tmp/x', '--userinterface', 'stb-testop',
                                '--team-id', 't', '--post-json', str(path)])
    assert args.post_json == str(path)
    # without --apply it must refuse to send anything
    assert scan_mod.main(['--capture-root', '/tmp/x', '--userinterface', 'stb-testop',
                          '--team-id', 't', '--post-json', str(path)]) == 0


# ---- stills are published as R2 keys, not host paths -------------------------------- #

def test_a_host_path_is_never_stored_as_the_still():
    """The bug this pins: image_url held /var/www/html/stream/... which is a 404 from the app's
    origin, so every thumbnail rendered as an empty box."""
    import inspect

    src = inspect.getsource(scan_mod.UnknownScreenScan.classify_cluster)
    assert "'image_url': representative" not in src
    assert 'publish_still' in src


def test_publish_still_returns_the_r2_key_not_a_presigned_url(monkeypatch):
    """A presigned URL expires; a row that outlived it would show a broken thumbnail forever.
    The frontend resolves the key through useR2Url and mints a fresh URL per view."""
    calls = {}

    def fake_upload(local_path, ui, name):
        calls.update(local_path=local_path, ui=ui, name=name)
        return {'success': True, 'remote_path': f'navigation/{ui}/{name}'}

    import shared.src.lib.utils.cloudflare_utils as cf
    monkeypatch.setattr(cf, 'upload_navigation_screenshot', fake_upload)

    scan = scan_mod.UnknownScreenScan(_args())
    key = scan.publish_still(None, '/var/www/html/stream/capture4/captures/x.jpg', 'abc123def456')
    assert key == 'navigation/stb-testop/unknown_abc123def456.jpg'
    assert 'signature=' not in key
    assert calls['ui'] == 'stb-testop'


def test_a_failed_upload_leaves_the_row_but_drops_the_still(monkeypatch):
    """A row with no thumbnail is still a useful row; losing the finding over an upload would be
    the wrong trade."""
    import shared.src.lib.utils.cloudflare_utils as cf
    monkeypatch.setattr(cf, 'upload_navigation_screenshot',
                        lambda *a, **k: {'success': False, 'error': 'bucket down'})
    scan = scan_mod.UnknownScreenScan(_args())
    assert scan.publish_still(None, '/tmp/x.jpg', 'deadbeef') is None


def test_uploads_can_be_switched_off():
    args = scan_mod.parse_args(['--capture-root', '/tmp/x', '--userinterface', 'u',
                                '--team-id', 't', '--no-upload-stills'])
    assert args.upload_stills is False


def test_the_still_key_is_stable_so_rescanning_overwrites():
    """Keyed by the cluster hash: a nightly rescan must not accumulate copies of every screen."""
    import inspect

    src = inspect.getsource(scan_mod.UnknownScreenScan.publish_still)
    assert "dhash[:16]" in src


# ---- proposed names ---------------------------------------------------------------- #

def test_a_name_is_built_from_the_screen_type_and_summary():
    dom = {'screen_summary': 'Subscription expired dialog', 'screen_type': 'dialog'}
    assert scan_mod.propose_name(dom, 'dialog') == 'dialog_subscription_expired'


def test_names_follow_the_existing_convention():
    """menu_submenu / popup_A / splashscreen_1 — short, prefixed by family, snake_case."""
    dom = {'screen_summary': 'Home Menu', 'screen_type': 'nav_row'}
    assert scan_mod.propose_name(dom, 'nav_row') == 'nav_row_home_menu'


def test_a_name_is_never_a_whole_sentence():
    dom = {'screen_summary': 'This is the home screen of the set top box where you pick things',
           'screen_type': 'content'}
    out = scan_mod.propose_name(dom, 'content')
    assert len(out.split('_')) <= 5


def test_an_unknown_screen_type_does_not_invent_a_category():
    dom = {'screen_summary': 'Some Screen', 'screen_type': 'gibberish'}
    assert scan_mod.propose_name(dom, 'gibberish') == 'some_screen'


def test_a_missing_summary_still_yields_a_usable_label():
    assert scan_mod.propose_name({}, 'overlay') == 'overlay'
    assert scan_mod.propose_name({'screen_summary': ''}, None) == 'unknown_screen'


def test_naming_is_off_by_default_and_bounded():
    """One model call per screen: never a surprise, and never unbounded."""
    args = scan_mod.parse_args(['--capture-root', '/tmp/x', '--userinterface', 'u',
                                '--team-id', 't'])
    assert args.name_screens is False
    assert args.name_limit == 50


def test_content_is_never_named():
    """Asking the model what a promo slate is costs a call to learn what we already decided."""
    scan = scan_mod.UnknownScreenScan(_args(name_screens=True, name_limit=50))
    assert scan.name_screen('/tmp/x.jpg', 'content') is None
    assert scan.named == 0


# ---- a scan must retire what it did not see ----------------------------------------- #

def test_rows_the_latest_scan_did_not_see_are_retired_not_left_live():
    """Scanning twice produced 356 rows then 305 more — 661 in total — because upserting on
    cluster_dhash stops a repeat duplicating a row but does nothing about rows a later scan no
    longer sees. The operator saw the same screens listed over and over."""
    import inspect

    from backend_server.src.routes import server_userinterface_routes as routes

    src = inspect.getsource(routes.upsert_unknown_screens_route)
    assert 'retire_screens_not_seen' in src
    # and it must run in the same request, after the upsert
    assert src.index('upsert_unknown_screens(') < src.index('retire_screens_not_seen(')


def test_the_list_and_the_counts_both_ignore_retired_rows(monkeypatch):
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[])
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)
    db.list_unknown_screens('team', userinterface='stb-testop')

    nulls = [a for kind, a in fake.filters if kind == 'is_']
    assert ('retired_at', 'null') in nulls


def test_upserting_clears_retired_at_so_a_reappearing_screen_comes_back(monkeypatch):
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[{'id': 'x'}])      # row already exists
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)
    db.upsert_unknown_screens('team', 'stb-testop', [{'cluster_dhash': 'abc'}])

    assert fake.updated, 'existing row should be updated'
    assert fake.updated[0].get('retired_at', 'MISSING') is None


def test_a_row_never_seen_by_any_scan_is_not_retired(monkeypatch):
    """A failed first scan, or a half-applied migration, must not be able to empty the table."""
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[])
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)
    db.retire_screens_not_seen('team', 'stb-testop', ['abc'])

    nots = [a for kind, a in fake.filters if kind == 'not_is_']
    assert ('last_scan_at', 'null') in nots


# ---- retirement actually retires ------------------------------------------------------ #

def test_retirement_negates_through_the_builder_property_not_by_calling_it(monkeypatch):
    """`.not_` is a property in supabase-py 2.x. Called as a method it raises
    "'SyncFilterRequestBuilder' object is not callable", the except swallowed it, and the function
    returned 0 without retiring anything -- four scans' worth, while every one reported
    "retired: 0". The fake above makes `not_` non-callable for the same reason."""
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[])
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)

    assert db.retire_screens_not_seen('team', 'stb-testop', ['abc']) == 0
    assert fake.updated, 'retirement must actually issue an UPDATE'
    assert fake.updated[0].get('retired_at')


def test_retirement_excludes_every_hash_the_scan_saw(monkeypatch):
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(result_data=[])
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)
    db.retire_screens_not_seen('team', 'stb-testop', ['aaa', 'bbb', "c'c"])

    not_ins = [a for kind, a in fake.filters if kind == 'not_in_']
    assert not_ins, 'NOT IN filter must be applied'
    # passed as a list so the client quotes it, not hand-built SQL
    assert not_ins[0][0] == 'cluster_dhash'
    assert list(not_ins[0][1]) == ['aaa', 'bbb', "c'c"]


def test_a_broken_retirement_reports_failure_instead_of_looking_like_nothing_to_do(monkeypatch):
    """0 is a real answer meaning "nothing needed retiring". Returning 0 on an exception is what
    made four scans report retired: 0 and look healthy while 308 stale rows stayed live."""
    from shared.src.lib.database import unknown_screens_db as db

    fake = _FakeSupabase(raises=True)
    monkeypatch.setattr(db, 'get_supabase', lambda: fake)

    assert db.retire_screens_not_seen('team', 'stb-testop', ['abc']) == db.RETIRE_FAILED


def test_retirement_runs_once_per_scan_not_once_per_batch():
    """A scan posts in batches of 25. Retiring per batch would have batch 2 retire batch 1, and
    the table would keep only the last 25 rows of the whole scan."""
    import inspect

    from backend_server.src.routes import server_userinterface_routes as routes

    src = inspect.getsource(routes.upsert_unknown_screens_route)
    assert 'retire_unseen' in src, 'retirement must be gated on the client saying it is the last batch'


def test_the_last_batch_carries_the_hash_list_for_the_whole_scan():
    """The final request only holds the last chunk of rows. If the server judged the scan by those
    alone it would retire every screen the earlier batches had just written."""
    import inspect

    from backend_server.src.routes import server_userinterface_routes as routes

    src = inspect.getsource(routes.upsert_unknown_screens_route)
    assert 'seen_dhashes' in src

    scan_src = inspect.getsource(scan_mod.post_findings)
    assert 'seen_dhashes' in scan_src, 'the scan must send every hash, not just the last batch'


def test_only_the_final_batch_asks_for_retirement(monkeypatch):
    import json as _json
    import urllib.request as _urlreq

    calls = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"success": true}'

    def fake_urlopen(req, timeout=None):
        calls.append(_json.loads(req.data.decode()))
        return _Resp()

    # post_findings does `import urllib.request` inside the function body, so patching the module
    # attribute is what takes effect.
    monkeypatch.setattr(_urlreq, 'urlopen', fake_urlopen)

    args = _args(team_id='t', userinterface='stb-testop', server_url='http://x')
    findings = [{'cluster_dhash': f'h{i}'} for i in range(5)]
    scan_mod.post_findings(args, findings, batch_size=2)

    assert len(calls) == 3, '5 rows at batch_size 2 is 3 requests'
    assert [c['retire_unseen'] for c in calls] == [False, False, True]
    assert len(calls[-1]['seen_dhashes']) == 5, 'last batch must carry all 5 hashes'
    assert 'seen_dhashes' not in calls[0]


# ---- thumbnails are not captures ---------------------------------------------------- #

def test_thumbnail_directories_are_skipped():
    """47 of 305 live rows were thumbnails. find_frames sorts by mtime and truncates to --limit,
    and the archiver writes thumbnails continuously -- so they were the entire newest slice."""
    for p in ('/var/www/html/stream/capture4/hot/thumbnails/capture_000155198_thumbnail.jpg',
              '/var/www/html/stream/capture4/thumbnails/x.jpg'):
        assert scan_mod._is_derived_image(p), p


def test_thumbnail_filenames_are_skipped_even_inside_captures():
    assert scan_mod._is_derived_image('/a/b/captures/capture_000123_thumbnail.jpg')
    assert scan_mod._is_derived_image('/a/b/CAPTURE_9_THUMBNAIL.JPG')


def test_real_captures_are_not_skipped():
    """The whole scan is worthless if this is wrong in the other direction."""
    for p in ('/var/www/html/stream/capture4/captures/capture_000051176.jpg',
              '/var/www/html/stream/capture4/captures/13/capture_999999.jpg',
              '/var/www/html/stream/capture4/hot/captures/capture_123.jpg'):
        assert not scan_mod._is_derived_image(p), p


def test_find_frames_skips_thumbnails(tmp_path):
    root = tmp_path / 'capture'
    (root / 'captures').mkdir(parents=True)
    (root / 'hot' / 'thumbnails').mkdir(parents=True)
    (root / 'captures' / 'capture_000001.jpg').write_bytes(b'x')
    (root / 'hot' / 'thumbnails' / 'capture_000002_thumbnail.jpg').write_bytes(b'x')
    found = scan_mod.find_frames(str(tmp_path), 'capture')
    assert all('thumbnail' not in f for f in found)
    assert len(found) == 1
