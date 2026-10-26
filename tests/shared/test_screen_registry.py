"""TASK-159: one writer for screen rows (register_screen), fuzzy identity, sighting counts, guarded names/prunes."""
import os
import sys
import types
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from shared.src.lib.database import screen_fingerprints_db as db  # noqa: E402

FULL = 'ab' * 32
CENTER = 'cd' * 32


def flip(hexstr, bits):
    """hexstr with its first ``bits`` bits inverted."""
    n = int(hexstr, 16) ^ (((1 << bits) - 1) << (len(hexstr) * 4 - bits))
    return format(n, f'0{len(hexstr)}x')


def fake_client(rows, rpc_rows=None):
    client = MagicMock()
    client.rpc.return_value.execute.return_value = types.SimpleNamespace(data=rpc_rows or [])
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = \
        types.SimpleNamespace(data=[{}])
    return client


def row(**kw):
    base = {'id': 'r1', 'dhash': FULL, 'region_center': CENTER, 'seen_count': 4, 'verdict': 'unknown', 'label': 'unknown_1'}
    base.update(kw)
    return base


def test_a_new_picture_registers_the_next_unknown_n(monkeypatch):
    client = fake_client([], rpc_rows=[{'id': 'new', 'label': 'unknown_3', 'seen_count': 1}])
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)
    monkeypatch.setattr(db, '_device_rows', lambda t, s: [])
    out = db.register_screen('t1', 'h1/device3', {'dhash': FULL, 'region_center': CENTER}, sample_image_path='data:image/x')
    assert out == {'id': 'new', 'label': 'unknown_3', 'dist': 0, 'is_new': True, 'verdict': 'unknown', 'seen': 1}
    name, args = client.rpc.call_args.args
    assert name == 'register_screen_row'     # number and insert are one DB function: no Python max+1
    assert args['p_scope'] == 'h1/device3' and args['p_dhash'] == FULL


def test_the_same_screen_within_tolerance_is_one_row_with_a_sighting(monkeypatch):
    client = fake_client([])
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)
    monkeypatch.setattr(db, '_device_rows', lambda t, s: [row()])
    near = {'dhash': flip(FULL, 6), 'region_center': flip(CENTER, 4)}   # 6 and 4 bits apart: not exact equality
    out = db.register_screen('t1', 'h1/device3', near)
    assert out['id'] == 'r1' and out['is_new'] is False and out['seen'] == 5
    assert not client.rpc.called                       # nothing created
    assert client.table.return_value.update.call_args.args[0]['seen_count'] == 5


def test_a_different_screen_gets_a_new_row(monkeypatch):
    client = fake_client([], rpc_rows=[{'id': 'n2', 'label': 'unknown_2', 'seen_count': 1}])
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)
    monkeypatch.setattr(db, '_device_rows', lambda t, s: [row()])
    far = {'dhash': flip(FULL, 80), 'region_center': flip(CENTER, 80)}
    assert db.register_screen('t1', 'h1/device3', far)['label'] == 'unknown_2'


def test_count_screen_sighting_never_creates(monkeypatch):
    client = fake_client([])
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)
    monkeypatch.setattr(db, '_device_rows', lambda t, s: [])
    assert db.count_screen_sighting('t1', 'h1/device3', {'dhash': FULL, 'region_center': CENTER}) is None
    assert not client.rpc.called and not client.table.return_value.insert.called


def test_register_never_raises(monkeypatch):
    monkeypatch.setattr(db, '_device_rows', lambda t, s: (_ for _ in ()).throw(RuntimeError('db down')))
    assert db.register_screen('t1', 's', {'dhash': FULL, 'region_center': CENTER}) is None


def test_freeze_stamp_follows_a_merged_row(monkeypatch):
    client = MagicMock()
    sel = client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute
    sel.side_effect = [types.SimpleNamespace(data=[row(id='old', merged_into='kept')]),
                       types.SimpleNamespace(data=[row(id='kept', seen_count=9)])]
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)
    out = db.count_sighting_by_id('t1', 'old')
    assert out['id'] == 'kept' and out['seen'] == 10


def test_prune_rare_goes_through_the_label_guarded_function(monkeypatch):
    client = fake_client([])
    client.rpc.return_value.execute.return_value = types.SimpleNamespace(data=2)
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)
    assert db.prune_rare() == 2
    assert client.rpc.call_args.args[0] == 'prune_rare_screens'


def test_fp_from_blob():
    assert db.fp_from_blob({'dhash': FULL, 'regions': {'center': CENTER}}) == {'dhash': FULL, 'region_center': CENTER}
    assert db.fp_from_blob({'dhash': FULL}) is None and db.fp_from_blob(None) is None


def test_the_sql_guards_are_in_the_migration():
    """The guard lives in SQL (G4); the live proof ran on a lab database inside a rolled-back transaction."""
    sql = ''.join(open(os.path.join(ROOT, 'setup/db/migrations', f)).read() for f in ('20261022e_screen_registry.sql', '20261022f_screen_prune_guard.sql'))
    assert sql.count("label ~ '^unknown_[0-9]+$'") >= 3   # name_screen_row + both prunes


def test_device_rows_are_paged_and_skip_merged(monkeypatch):
    client = MagicMock()
    q = client.table.return_value.select.return_value.eq.return_value.eq.return_value.is_.return_value.order.return_value
    pages = [[{'id': str(i), 'dhash': FULL, 'region_center': CENTER} for i in range(1000)],
             [{'id': 'last', 'dhash': FULL, 'region_center': CENTER}]]
    q.range.return_value.execute.side_effect = [types.SimpleNamespace(data=p) for p in pages]
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)
    assert len(db._device_rows('t1', 's')) == 1001
    assert client.table.return_value.select.return_value.eq.return_value.eq.return_value.is_.call_args.args == ('merged_into', 'null')


def test_a_sighting_by_id_gives_a_row_without_a_picture_its_thumbnail(monkeypatch):
    import numpy as np
    client = MagicMock()
    sel = client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute
    sel.return_value = types.SimpleNamespace(data=[row(id='r9', sample_image_path='/var/www/html/stream/capture3/x.jpg')])
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)
    frame = (np.random.RandomState(1).rand(90, 160, 3) * 255).astype('uint8')
    out = db.count_sighting_by_id('t1', 'r9', frame=frame)
    assert out['seen'] == 5
    upd = client.table.return_value.update.call_args.args[0]
    assert upd['sample_image_path'].startswith('data:image/jpeg;base64,')
    # a row that already has a picture keeps it
    sel.return_value = types.SimpleNamespace(data=[row(id='r9', sample_image_path='data:image/jpeg;base64,AAAA')])
    db.count_sighting_by_id('t1', 'r9', frame=frame)
    assert 'sample_image_path' not in client.table.return_value.update.call_args.args[0]


def test_a_sighting_by_id_fills_a_missing_fingerprint_through_the_single_writer(monkeypatch):
    """A row registered before fingerprints existed keeps NULL for ever unless somebody hands it one.

    The freeze path sees the screen again, so it can fill it -- once, through ``link_screen_fingerprint``
    (never a direct write: the fingerprint has its own single writer).
    """
    client = MagicMock()
    sel = client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute
    sel.return_value = types.SimpleNamespace(data=[row(id='r9')])          # no fingerprint
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)
    blob = {'v': 6, 'dhash': FULL, 'regions': {'center': CENTER}}

    out = db.count_sighting_by_id('t1', 'r9', fingerprint=blob)

    assert out['id'] == 'r9'
    name, args = client.rpc.call_args.args
    assert name == 'link_screen_fingerprint'
    assert args['p_id'] == 'r9' and args['p_fingerprint'] == blob


def test_a_sighting_by_id_never_overwrites_a_fingerprint(monkeypatch):
    """Written once. A row that already has a fingerprint is left exactly as it is."""
    client = MagicMock()
    sel = client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute
    sel.return_value = types.SimpleNamespace(data=[row(id='r9', fingerprint={'dhash': FULL})])
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)

    db.count_sighting_by_id('t1', 'r9', fingerprint={'v': 6, 'dhash': 'ff' * 32})

    assert not client.rpc.called, 'an existing fingerprint must never be replaced'


def test_a_matched_row_without_a_thumbnail_gets_the_new_one(monkeypatch):
    client = fake_client([])
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)
    monkeypatch.setattr(db, '_device_rows', lambda t, s: [row(sample_image_path='/var/www/html/stream/capture5/x.jpg')])
    db.register_screen('t1', 'h1/capture5', {'dhash': FULL, 'region_center': CENTER},
                       sample_image_path='data:image/jpeg;base64,AAA')
    assert client.table.return_value.update.call_args.args[0]['sample_image_path'] == 'data:image/jpeg;base64,AAA'


def test_a_matched_row_keeps_its_thumbnail_and_never_takes_a_host_path(monkeypatch):
    client = fake_client([])
    monkeypatch.setattr(db, 'get_supabase_client', lambda: client)
    monkeypatch.setattr(db, '_device_rows', lambda t, s: [row(sample_image_path='data:image/jpeg;base64,OLD')])
    db.register_screen('t1', 'h1/device3', {'dhash': FULL, 'region_center': CENTER},
                       sample_image_path='data:image/jpeg;base64,NEW')
    assert 'sample_image_path' not in client.table.return_value.update.call_args.args[0]
    monkeypatch.setattr(db, '_device_rows', lambda t, s: [row(sample_image_path='/old/path.jpg')])
    db.register_screen('t1', 'h1/device3', {'dhash': FULL, 'region_center': CENTER}, sample_image_path='/new/path.jpg')
    assert 'sample_image_path' not in client.table.return_value.update.call_args.args[0]
