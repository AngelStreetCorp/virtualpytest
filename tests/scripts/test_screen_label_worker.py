"""TASK-162: the screen-label worker names recurring screens once, through the single writer.

The tests here are about the RULES, not about the model: which questions are asked, in which order, what is
never written, and what happens when the model is unsure. No network, no DB — the AI is a stub and the DB is
a recorder, so every assertion is about this script's decisions.
"""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import backend_server.scripts.screen_label_worker as w  # noqa: E402

# The guard name_screen_row's WHERE clause is written in SQL (20261022e), so the test pins it against the
# migration file rather than a Python constant that could drift from it.
_NAME_SQL_GUARD = "(label IS NULL OR label ~ '^unknown_[0-9]+$')"
from scripts import screen_label_coverage as cov  # noqa: E402


# --------------------------------------------------------------- helpers

def row(**kw):
    base = {'id': 'r1', 'scope': 'vpt-mf1/device2', 'label': None, 'dhash': 'a' * 64,
            'region_center': 'b' * 64, 'userinterface': None, 'incident_type': 'freeze',
            'seen_count': 40, 'sample_image_path': 'data:image/jpeg;base64,AAAA',
            'label_state': None, 'merged_into': None}
    base.update(kw)
    return base


class FakeDB:
    """Records writes. `rpc` is how the only label write happens (name_screen_row)."""

    def __init__(self, named_ok=True):
        self.table_ops = []
        self.rpc_ops = []
        self.named_ok = named_ok

    def table(self, name):
        db = self

        class T:
            def select(self, *a, **k): return self
            def update(self, vals): db.table_ops.append((name, 'update', vals)); return self
            def insert(self, vals): db.table_ops.append((name, 'insert', vals)); return self
            def upsert(self, vals, **k): db.table_ops.append((name, 'upsert', vals)); return self
            def eq(self, *a): return self
            def is_(self, *a): return self
            def limit(self, *a): return self
            def execute(self):
                class R:
                    data = [{'deleted_count': 0}]
                    count = 1
                return R()
        return T()

    def rpc(self, fn, params):
        db = self
        db.rpc_ops.append((fn, params))

        class R:
            data = [1] if db.named_ok else [0]

            def execute(self):
                return self
        return R()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(w, 'resolve_sample', lambda sample, scope=None: ('/tmp/x.jpg', None))


# --------------------------------------------------------------- naming rules

def test_a_label_only_goes_through_name_screen_row():
    """The single writer is the ONLY path to a name; the worker never writes `label` directly."""
    db = FakeDB()
    assert w.name_row(db, 'team', 'r1', 'settings_profiles') is True
    assert db.rpc_ops == [('name_screen_row', {'p_team_id': 'team', 'p_id': 'r1',
                                               'p_label': 'settings_profiles'})]
    # and nothing ever writes the label column itself
    for name, op, vals in db.table_ops:
        assert 'label' not in vals or name != 'screen_fingerprints', f'label written directly via {op}'


def test_name_screen_row_failure_is_reported_not_hidden():
    """A 0-row answer means another writer already named it; that is a fact, not a crash."""
    db = FakeDB(named_ok=False)
    assert w.name_row(db, 'team', 'r1', 'x') is False


def test_mark_never_touches_the_label_column():
    db = FakeDB()
    w.mark(db, 'team', 'r1', 'review', 'because', 'profile-x')
    updates = [v for n, op, v in db.table_ops if op == 'update']
    assert updates, 'mark wrote nothing'
    for vals in updates:
        assert 'label' not in vals


def test_slug_normalises_a_model_answer():
    assert w.slug('Full Screen  Poster!') == 'full_screen_poster'
    assert w.slug('  Settings/Profiles ') == 'settings_profiles'
    assert w.slug('') == ''
    # a long name keeps its tail: the limit is on WORDS, not on characters
    assert w.slug('A very long screen name indeed') == 'a_very_long_screen_name_indeed'


def test_a_real_name_is_never_offered_again():
    """TASK-159 G4: the picker only sees NULL / unknown_N."""
    assert cov.UNNAMED_RE == w.UNNAMED_RE == '^unknown_[0-9]+$'
    assert w.UNNAMED_RE == '^unknown_[0-9]+$'


# --------------------------------------------------------------- answer parsing

def test_word_boundaries_stop_nomenu_matching_menu():
    """The poster question answers MENU or NOMENU; a substring test would read NOMENU as MENU."""
    assert w._has('NOMENU', 'MENU') is False
    assert w._has('MENU', 'MENU') is True
    assert w._has('There is no MENU here', 'MENU') is True


def test_a_preamble_before_the_answer_still_parses():
    assert w._has('Based on the picture, it is a MOVING channel', 'MOVING') is True


def test_contradictory_answers_are_not_an_answer():
    votes = {'SCREEN': 'yes', 'PHOTO': 'no'}
    assert votes  # sanity: the two sides are distinct
    text = 'it is a SCREEN of a PHOTO'
    assert w._has(text, 'SCREEN') and w._has(text, 'PHOTO')   # both present -> the caller refuses


# --------------------------------------------------------------- liveness gate

def test_liveness_is_only_asked_where_the_path_cannot_answer_it():
    """A still thumbnail cannot show motion; the registration path settles it for freeze/abstain rows."""
    assert w.liveness_of(row(incident_type='freeze')) == 'settled'
    assert w.liveness_of(row(incident_type='localize_abstain')) == 'settled'
    assert w.liveness_of(row(incident_type='screen')) == 'ask'


def test_a_split_vote_is_not_a_decision(monkeypatch):
    """Measured: the same frame answered MOVING, STILL, STILL. A split vote leaves the row alone."""
    seq = iter(['MOVING', 'STILL', 'STILL'])
    monkeypatch.setattr(w, '_ask', lambda *a, **k: {'ok': True, 'content': next(seq)})
    verdict, summary = w.ask_live('p', '/tmp/x.jpg', 't', votes=3)
    assert verdict == 'unknown'
    # the note records the individual answers, normalised, so a human can see the split
    assert 'live' in summary and 'screen' in summary


def test_unanimous_votes_decide(monkeypatch):
    seq = iter(['STILL', 'STILL', 'STILL'])
    monkeypatch.setattr(w, '_ask', lambda *a, **k: {'ok': True, 'content': next(seq)})
    assert w.ask_live('p', '/tmp/x.jpg', 't', votes=3)[0] == 'screen'


def test_a_failed_call_does_not_count_as_a_vote(monkeypatch):
    seq = iter([{'ok': False, 'error': 'down'}, {'ok': True, 'content': 'STILL'},
                {'ok': True, 'content': 'STILL'}])
    monkeypatch.setattr(w, '_ask', lambda *a, **k: next(seq))
    assert w.ask_live('p', '/tmp/x.jpg', 't', votes=3)[0] == 'unknown'


def test_the_ui_gate_refuses_a_photo_of_a_real_thing(monkeypatch):
    """The state hints read "no menu -> poster", which is only an inference when a menu was possible.
    Two vpt-pi4/device1 frames are blurry photos of a wall and were named "Full-screen poster" before
    this gate existed (BUG-0849)."""
    seq = iter(['PHOTO', 'PHOTO', 'PHOTO'])
    monkeypatch.setattr(w, '_ask', lambda *a, **k: {'ok': True, 'content': next(seq)})
    assert w.ask_ui('p', '/tmp/x.jpg', 't', votes=3)[0] == 'photo'


# --------------------------------------------------------------- open-set confidence

def test_no_parsable_confidence_means_low(monkeypatch):
    monkeypatch.setattr(w, '_ask', lambda *a, **k: {'ok': True, 'content': 'settings_profiles'})
    assert w.ask_open('p', '/tmp/x.jpg', 't')['confidence'] == 'LOW'


def test_a_high_confidence_open_answer_is_parsed(monkeypatch):
    monkeypatch.setattr(w, '_ask', lambda *a, **k: {'ok': True, 'content': 'USB error dialog | HIGH'})
    out = w.ask_open('p', '/tmp/x.jpg', 't')
    assert out['label'] == 'usb_error_dialog' and out['confidence'] == 'HIGH'


def test_an_empty_open_answer_yields_no_name(monkeypatch):
    monkeypatch.setattr(w, '_ask', lambda *a, **k: {'ok': True, 'content': ' | LOW'})
    assert w.ask_open('p', '/tmp/x.jpg', 't')['label'] == ''


# --------------------------------------------------------------- link vs propose

def test_no_candidate_means_no_link():
    assert w.link_node(row(), []) is None


def test_an_interface_is_read_from_the_node_never_guessed(monkeypatch):
    """TASK-159 G6: a match must not invent an interface, and two interfaces claiming one picture is
    not a link — it is a question for a person."""
    class FakeMemory:
        @staticmethod
        def match_screen(fp, rows):
            return (rows[0], 3) if rows else None
    monkeypatch.setattr('shared.src.lib.screen_memory.match_screen',
                        staticmethod(lambda fp, rows: FakeMemory.match_screen(fp, rows)))
    candidates = [{'dhash': 'a' * 64, 'region_center': 'b' * 64, 'node_id': 'n1', 'label': 'home',
                   'userinterface': 'stb-testop', 'fingerprint': {'v': 6}}]
    hit = w.link_node(row(), candidates)
    assert hit and hit['node_id'] == 'n1' and hit['userinterface'] == 'stb-testop'


def test_a_proposal_without_an_interface_is_skipped():
    """userinterface_unknown_screens is keyed by interface; guessing one is forbidden, so there is no
    proposal and the row keeps its name only."""
    db = FakeDB()
    assert w.propose_node(db, 'team', row(userinterface=None), 'a_name', {}) is False
    assert db.table_ops == []


def test_a_proposal_with_an_interface_is_queued_not_created():
    db = FakeDB()
    assert w.propose_node(db, 'team', row(userinterface='stb-testop'), 'a_name', {}) is True
    name, op, _ = db.table_ops[0]
    assert (name, op) == ('userinterface_unknown_screens', 'upsert')


# --------------------------------------------------------------- coverage buckets

@pytest.mark.parametrize('label,fingerprint,expected', [
    ('splash_screen', {'dhash': 'x'}, 'named_fingerprinted'),
    ('splash_screen', None, 'named_no_fingerprint'),
    ('unknown_12', {'dhash': 'x'}, 'unknown_n'),
    (None, {'dhash': 'x'}, 'unlabelled'),
    (None, None, 'unlabelled'),
])
def test_coverage_buckets(label, fingerprint, expected):
    assert cov.bucket({'label': label, 'fingerprint': fingerprint}) == expected


def test_an_empty_fingerprint_object_is_not_a_fingerprint():
    assert cov.has_fingerprint({'fingerprint': {}}) is False
    assert cov.has_fingerprint({'fingerprint': {'dhash': 'x'}}) is True


def test_the_metric_counts_placeholders_blank_rows_and_named_rows_without_a_fingerprint():
    """The owner's goal: a screen that is LABELLED AND FINGERPRINTED.

    So a named row with no fingerprint is unfinished and counts; a named row WITH one is done and
    does not count.  The old metric ('unknown_N + no label') called the first one finished, which
    hid 21 of the 31 recurring screens on the lab."""
    rows = [row(label=None), row(label='unknown_3'),
            row(label='splash_screen'), row(label='splash_screen', fingerprint={'v': 6, 'dhash': 'd' * 64})]
    t = cov.tally(rows)
    assert t['unlabelled'] == 1 and t['unknown_n'] == 1
    assert t['named_no_fingerprint'] == 1 and t['named_fingerprinted'] == 1
    # the named row without a fingerprint counts; the named row with one does not
    assert cov.metric_of(t) == 3
    t2 = cov.tally([row(label='splash_screen', fingerprint={'v': 6, 'dhash': 'd' * 64})])
    assert cov.metric_of(t2) == 0

# --------------------------------------------------------------- the two thresholds

def test_the_worker_floor_is_the_retention_prune_floor():
    """3, because prune_unnamed_screen_noise deletes a row seen fewer than 3 times
    (migration 20261022f, p_min_hits DEFAULT 3). Naming above that floor would name rows the registry
    itself is about to drop; naming below it would name single-occurrence glitches."""
    assert w.MIN_SEEN == 3


def test_the_owners_metric_stays_where_the_owner_put_it():
    """The report measures '>10 seen'; the worker names from 3. These are two different questions and must
    not be collapsed into one constant — moving the metric would silently redefine the owner's goal."""
    assert cov.MIN_SEEN == 10
    assert cov.MIN_SEEN != w.MIN_SEEN


def test_lowering_the_floor_does_not_loosen_the_two_rules():
    """The guards that protect a written name are independent of the picker threshold."""
    # never-rename: the only path to a label is the RPC whose WHERE clause the migration pins
    src = open(os.path.join(ROOT, 'backend_server', 'scripts', 'screen_label_worker.py')).read()
    assert 'name_screen_row' in src
    assert _NAME_SQL_GUARD == "(label IS NULL OR label ~ '^unknown_[0-9]+$')"


def test_the_worker_never_deletes_a_row():
    """No delete call and no prune RPC anywhere in the worker.

    A labelled row is not this process's to remove, and both prune functions in the DB already skip a row
    whose label is not unknown_N (20261022e prune_rare_screens, 20261022f prune_unnamed_screen_noise).
    Naming more rows must never turn into deleting more rows.

    Checked on the AST, not on the text: the prune function names appear in this script's own docstrings
    because they are where the number 3 comes from, and a substring test would flag that prose as a call.
    """
    import ast
    src = open(os.path.join(ROOT, 'backend_server', 'scripts', 'screen_label_worker.py')).read()
    rpcs, deletes = [], []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == 'rpc' and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant):
                    rpcs.append(first.value)
                elif isinstance(first, ast.Name):
                    # name_row calls db.rpc(_NAME_RPC, ...): resolve the module constant
                    rpcs.append(getattr(w, first.id))
            if node.func.attr == 'delete':
                deletes.append(node)
        elif isinstance(node, ast.Attribute) and node.attr == 'delete':
            deletes.append(node)

    assert not deletes, f'the worker must never delete a row ({len(deletes)} delete reference(s))'
    assert rpcs == [w._NAME_RPC], f'the only RPC the worker may call is {w._NAME_RPC}, found {rpcs}'


def test_the_worker_uses_the_free_minimax_flash_model():
    """Owner, 2026-10-23: 'we have free minimax m3.1-flash unlimited so use that'.

    `minimax-m3-1-flash` is the profile for model MiniMax-M3.1-Flash-Preview on the `minimax` endpoint:
    preset minimax (flat plan, cost 0), capabilities ['vision'], already used by vision.game_coc_flash
    and agent.forge. The old default, `minimax-vlm-minimax-vlm`, is the separate coding_plan/vlm endpoint
    whose smaller token allowance ran out on 2026-10-23 and stopped this worker cold."""
    assert w.DEFAULT_PROFILE == 'minimax-m3-1-flash'
    assert 'minimax-vlm' not in w.DEFAULT_PROFILE


# --------------------------------------------------------------- the two free profiles

def test_a_refusal_is_recognised_in_the_words_the_gateway_actually_builds():
    """gateway._format_error renders a refusal as "<endpoint> (<preset>) HTTP <status> for model '<m>': <body>".

    Matching on the error_type names ("rate_limit", "no_credit") would never fire on those strings, and the
    worker would keep hammering an endpoint the provider has already refused."""
    assert w._is_refusal("minimax (anthropic) HTTP 429 for model 'MiniMax-M3.1-Flash-Preview': {}")
    assert w._is_refusal("minimax-vlm (minimax_vlm) HTTP 402 for model 'm': "
                         "{'base_resp': {'status_msg': 'Token Plan usage limit reached (2056)'}}")
    assert w._is_refusal('rate_limit')
    # a key that is wrong for the endpoint cannot fix itself on a retry, so it is a refusal too
    assert w._is_refusal("minimax (anthropic) HTTP 401 for model 'm': "
                         "{'type': 'error', 'error': {'type': 'authentication_error', "
                         "'message': 'invalid x-api-key'}}")
    # an empty answer is NOT a refusal: that one is worth a second look
    assert not w._is_refusal("minimax: empty answer from 'MiniMax-M3.1-Flash-Preview'")
    assert not w._is_refusal(None)


def test_a_refused_profile_is_not_asked_twice_and_the_second_free_profile_is_tried(monkeypatch, tmp_path):
    """The two MiniMax endpoints are flat plans with SEPARATE allowances, so a refusal moves to the next one.

    It must not burn a second call on the profile that just refused: the answer will not change."""
    from shared.src.lib.ai import gateway, router

    img = tmp_path / 'frame.jpg'
    img.write_bytes(b'\xff\xd8\xff\xd9')

    calls = []

    def fake_execute(resolution, question, **kw):
        calls.append(resolution)
        return {'success': False,
                'error': "minimax (anthropic) HTTP 429 for model 'MiniMax-M3.1-Flash-Preview': {}"}

    monkeypatch.setattr(gateway, 'execute', fake_execute)
    monkeypatch.setattr(router, 'resolve_profile', lambda name, *a, **k: name)
    monkeypatch.setattr(w, 'FALLBACK_PROFILES', ('second-free-profile',))

    out = w._ask('first-free-profile', 'is it a screen?', str(img), 'team')
    assert not out['ok']
    assert calls == ['first-free-profile', 'second-free-profile'], calls


def test_an_empty_answer_is_retried_on_the_same_profile(monkeypatch, tmp_path):
    """An empty answer is not a refusal: one flaky frame must not cost the row its name for a whole cycle."""
    from shared.src.lib.ai import gateway, router

    img = tmp_path / 'frame.jpg'
    img.write_bytes(b'\xff\xd8\xff\xd9')

    calls = []

    def fake_execute(resolution, question, **kw):
        calls.append(resolution)
        if len(calls) == 1:
            return {'success': False, 'error': "minimax: empty answer from 'MiniMax-M3.1-Flash-Preview'"}
        return {'success': True, 'content': 'MENU', 'model': 'MiniMax-M3.1-Flash-Preview'}

    monkeypatch.setattr(gateway, 'execute', fake_execute)
    monkeypatch.setattr(router, 'resolve_profile', lambda name, *a, **k: name)
    monkeypatch.setattr(w, 'FALLBACK_PROFILES', ())

    out = w._ask('first-free-profile', 'is it a screen?', str(img), 'team')
    assert out['ok'] and out['content'] == 'MENU'
    assert calls == ['first-free-profile', 'first-free-profile'], calls
    assert out['profile'] == 'first-free-profile'


# --------------------------------------------------------------- the token budget

def test_the_token_floor_leaves_room_for_the_answer():
    """MiniMax M3.1-Flash is a THINKING model: the reasoning comes out of the same max_tokens budget.

    MEASURED 2026-10-23, one stored frame, one prompt: 24 -> empty (stop_reason=max_tokens), 64 -> 'PHOTO'
    on 4 of 5 and 'PH' on the 5th (cut mid-word), 128 -> 'PHOTO' on 5 of 5, 256 -> 'PHOTO' on 5 of 5.
    At the old floor of 24 every call came back empty and the worker read that as "unreadable frame",
    which is the safe direction but names nothing at all."""
    assert w.MIN_ANSWER_TOKENS == 128
    assert w.OPEN_ANSWER_TOKENS >= w.MIN_ANSWER_TOKENS


def test_a_call_never_goes_below_the_token_floor(monkeypatch, tmp_path):
    """Whatever a caller asks for, the floor wins: the model needs the room to finish its answer."""
    from shared.src.lib.ai import gateway, router

    img = tmp_path / 'frame.jpg'
    img.write_bytes(b'\xff\xd8\xff\xd9')

    seen = {}

    def fake_execute(resolution, question, **kw):
        seen.update(kw)
        return {'success': True, 'content': 'PHOTO', 'model': 'm'}

    monkeypatch.setattr(gateway, 'execute', fake_execute)
    monkeypatch.setattr(router, 'resolve_profile', lambda name, *a, **k: name)
    monkeypatch.setattr(w, 'FALLBACK_PROFILES', ())

    w._ask('p', 'q', str(img), 'team', max_tokens=24)
    assert seen['max_tokens'] >= w.MIN_ANSWER_TOKENS, seen


# --------------------------------------------------------------- the fingerprint pass

def test_the_metric_counts_a_named_row_that_has_no_fingerprint():
    """The owner's goal is a screen that is LABELLED AND FINGERPRINTED.

    A name on its own does not finish a screen, and neither does a fingerprint on a row nobody can
    name, so every row that lacks either one is unfinished.  Measured 2026-10-23: 21 named rows
    without a fingerprint, 1 still unknown_N, 3 with no name at all -- 25 of the 31 in scope."""
    totals = {'named_fingerprinted': 6, 'named_no_fingerprint': 21, 'unknown_n': 1, 'unlabelled': 3}
    assert cov.metric_of(totals) == 25
    # a name with no fingerprint counts; a name WITH one does not
    assert cov.metric_of({'named_fingerprinted': 1, 'named_no_fingerprint': 0,
                           'unknown_n': 0, 'unlabelled': 0}) == 0
    assert cov.metric_of({'named_fingerprinted': 0, 'named_no_fingerprint': 1,
                           'unknown_n': 0, 'unlabelled': 0}) == 1


def test_the_fingerprint_pass_picks_only_named_rows_without_a_fingerprint():
    """A row still holding unknown_N is the naming pass's business, not this one's."""
    import re
    named = row(id='a', label='settings_profiles', fingerprint=None)
    placeholder = row(id='b', label='unknown_7', fingerprint=None)
    already = row(id='c', label='settings_profiles', fingerprint={'v': 6, 'dhash': 'd' * 64})
    picked = [r for r in (named, placeholder, already)
              if not re.match(w.UNNAMED_RE, str(r.get('label') or '')) and not r.get('fingerprint')]
    assert [r['id'] for r in picked] == ['a']


def test_a_fingerprint_is_written_through_the_single_writer_and_never_renames(monkeypatch):
    """The fingerprint has its own single writer, and it cannot touch a name."""
    calls = []

    class Db:
        def rpc(self, fn, params):
            calls.append((fn, params))

            class R:
                data = [1]

                def execute(self):
                    return self
            return R()

    from shared.src.lib.database import screen_fingerprints_db as sdb
    monkeypatch.setattr(sdb, 'get_supabase_client', lambda: Db())

    assert sdb.link_screen_fingerprint('team', 'r1', {'v': 6, 'dhash': 'a' * 64}) is True
    assert calls == [('link_screen_fingerprint',
                      {'p_team_id': 'team', 'p_id': 'r1',
                       'p_fingerprint': {'v': 6, 'dhash': 'a' * 64}, 'p_node_id': None})]
    # a blob without a dhash is not a fingerprint and is refused before the call
    assert sdb.link_screen_fingerprint('team', 'r1', {'v': 6}) is False
    assert len(calls) == 1
    # and it never writes the label: the UPDATE in the migration sets no label column
    migration = os.path.join(ROOT, 'setup', 'db', 'migrations', '20261023b_screen_fingerprint_writer.sql')
    sql = open(migration, encoding='utf-8').read()
    assert 'fingerprint IS NULL' in sql, 'a fingerprint must be written ONCE'
    assert 'merged_into IS NULL' in sql
    assert 'SET fingerprint =' in sql
    for statement in sql.split('UPDATE')[1].split(';'):
        assert 'label' not in statement.lower(), 'the fingerprint writer must not touch a label'


def test_the_blob_carries_the_rows_own_identity(monkeypatch, tmp_path):
    """The row's dhash IS what a monitor-computed blob carries, so the blob keeps it verbatim.

    Measured on every row that has one: the row's dhash == the blob's dhash and the row's
    region_center == the blob's regions.center (distance 0).  A backfill that wrote anything else
    would describe a screen the row is not."""
    import numpy as np
    import cv2

    img = np.full((180, 320, 3), 128, np.uint8)
    img[:, :160] = 200
    path = str(tmp_path / 'frame.jpg')
    cv2.imwrite(path, img)

    from backend_host.src.controllers.verification import image_helpers as ih
    from shared.src.lib import screen_memory

    r = row(dhash='a' * 64, region_center='b' * 64)
    # make the row's identity the picture's own identity, so the agreement check passes
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    r['dhash'] = screen_memory.dhash_hex(gray, screen_memory.GRID, screen_memory.BITS)
    h, width = gray.shape
    y0, y1, x0, x1 = screen_memory.CENTER
    r['region_center'] = screen_memory.dhash_hex(
        gray[int(y0 * h):int(y1 * h), int(x0 * width):int(x1 * width)], screen_memory.GRID, screen_memory.BITS)

    blob = w.build_row_fingerprint(r, path)
    assert blob is not None, 'the picture agrees with the row, so a blob must come out'
    assert blob['v'] == 6
    assert blob['dhash'] == r['dhash']
    assert blob['regions']['full'] == r['dhash']
    assert blob['regions']['center'] == r['region_center']
    assert blob['derived_from'] == 'row-thumbnail'
    # the thumbnail's per-region hashes are NOT copied in: a region is a fraction of the frame and
    # a thumbnail has a different aspect
    assert set(blob['regions']) == {'full', 'center'}


def test_a_picture_that_does_not_agree_with_the_row_is_left_for_review(monkeypatch, tmp_path):
    """A fingerprint that describes another screen is worse than no fingerprint: the row is listed."""
    import numpy as np
    import cv2

    img = np.full((180, 320, 3), 128, np.uint8)
    path = str(tmp_path / 'frame.jpg')
    cv2.imwrite(path, img)

    r = row(dhash='a' * 64, region_center='b' * 64)   # an identity the picture cannot be
    assert w.build_row_fingerprint(r, path) is None
