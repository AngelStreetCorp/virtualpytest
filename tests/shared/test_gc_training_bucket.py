"""Object GC for the AI training bucket (TASK-69 §5, step 6).

Pure: the DB read and the training storage client are in-memory fakes, so no test
touches the network or the database. The fake bucket paginates like S3 does
(1000 keys per page) and the fake table pages like PostgREST does (max-rows cap),
because both caps are what would silently turn a large bucket into "delete
everything".

Run: pytest tests/shared/test_gc_training_bucket.py -v
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

sys.path.insert(0, os.path.join(_repo_root, "scripts"))

import gc_training_bucket as gc  # noqa: E402
from shared.src.lib.utils import cloudflare_utils  # noqa: E402

TEAM = "11111111-1111-1111-1111-111111111111"
OTHER_TEAM = "22222222-2222-2222-2222-222222222222"
TRAINING_ENVS = ("MINIO_TRAINING_ENDPOINT", "MINIO_TRAINING_ACCESS_KEY",
                 "MINIO_TRAINING_SECRET_KEY", "MINIO_TRAINING_BUCKET",
                 "R2_TRAINING_BUCKET", "CLOUDFLARE_R2_ENDPOINT",
                 "CLOUDFLARE_R2_ACCESS_KEY_ID", "CLOUDFLARE_R2_SECRET_ACCESS_KEY")


class FakeS3:
    """S3 double: a dict of key -> size, paginated 1000 keys per page like S3."""

    PAGE = 1000

    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.deleted = []
        self.paginate_calls = 0
        self.delete_calls = 0

    def get_paginator(self, name):
        assert name == 'list_objects_v2'
        return self

    def paginate(self, Bucket=None, Prefix=''):
        self.paginate_calls += 1
        keys = sorted(k for k in self.objects if k.startswith(Prefix or ''))
        pages = [keys[i:i + self.PAGE] for i in range(0, len(keys), self.PAGE)] or [[]]
        for page in pages:
            yield {'Contents': [{'Key': k, 'Size': self.objects[k]} for k in page]}

    def delete_objects(self, Bucket=None, Delete=None):
        self.delete_calls += 1
        keys = [o['Key'] for o in Delete.get('Objects', [])]
        assert len(keys) <= 1000, "delete_objects caps at 1000 keys per call"
        for k in keys:
            self.objects.pop(k, None)
        self.deleted.extend(keys)
        return {'Deleted': [{'Key': k} for k in keys]}


class FakeStorage:
    def __init__(self, objects=None, bucket_name='vpt-training'):
        self.s3_client = FakeS3(objects)
        self.bucket_name = bucket_name


class FakeQuery:
    """PostgREST double: ``range()`` pages, max-rows caps the first response."""

    MAX_ROWS = 1000

    def __init__(self, rows):
        self.rows = rows
        self.team_id = None
        self.page_sizes = []

    def select(self, *columns):
        assert 'object_key' in columns
        return self

    def eq(self, column, value):
        self.team_id = value
        return self

    def range(self, start, end):
        self.page_sizes.append(end - start + 1)
        window = [r for r in self.rows if not self.team_id or r['team_id'] == self.team_id]
        chunk = window[start:end + 1]
        return type('Res', (), {'data': chunk, 'execute': lambda _self=None: _self})()

    def execute(self):  # pragma: no cover - range() returns the result directly
        return type('Res', (), {'data': self.rows})()


def _install_db(monkeypatch, rows):
    monkeypatch.setattr(gc.samples_db, 'get_supabase',
                        lambda: type('S', (), {'table': lambda _self, _t: FakeQuery(rows)})())


def _keys(*specs):
    """``[(team, family, device_model, month, name), ...]`` -> object_keys + rows."""
    rows = []
    for team, family, model, month, name in specs:
        key = f"{team}/{family}/{model}/{month}/{name}.jpg"
        rows.append({'team_id': team, 'object_key': key})
    return rows


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in TRAINING_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MINIO_TRAINING_ENDPOINT", "http://minio.invalid:9100")
    monkeypatch.setenv("MINIO_TRAINING_ACCESS_KEY", "k")
    monkeypatch.setenv("MINIO_TRAINING_SECRET_KEY", "s")
    monkeypatch.setenv("MINIO_TRAINING_BUCKET", "vpt-training")


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(cloudflare_utils, "get_training_storage", lambda: fake)
    return fake


def test_reconcile_finds_orphans_and_missing():
    rows = _keys((TEAM, 'screen-id', 'stb', '2026-10', 'a'),
                 (TEAM, 'screen-id', 'stb', '2026-10', 'b'))
    objects = [(r['object_key'], 10) for r in rows] + [('orphan', 20)]
    result = gc.reconcile(objects, {r['object_key'] for r in rows})
    assert result['orphans'] == [('orphan', 20)]
    assert result['missing'] == []
    assert result['listed'] == 3


def test_reconcile_reports_reverse_drift_without_acting():
    keys = {f"{TEAM}/screen-id/stb/2026-10/{n}.jpg" for n in ('a', 'gone')}
    result = gc.reconcile([(f"{TEAM}/screen-id/stb/2026-10/a.jpg", 10)], keys)
    assert result['orphans'] == []
    assert result['missing'] == [f"{TEAM}/screen-id/stb/2026-10/gone.jpg"]


def test_reconcile_never_marks_a_matching_object_an_orphan():
    """The DB is the authority: a row with its image is untouched, however old."""
    key = f"{TEAM}/focus/stb/2019-01/old.jpg"
    result = gc.reconcile([(key, 999)], {key})
    assert result['orphans'] == []
    assert result['missing'] == []


def test_reconcile_prefix_scopes_the_reverse_direction():
    keys = {f"{TEAM}/screen-id/stb/2026-10/a.jpg", f"{OTHER_TEAM}/screen-id/stb/2026-10/b.jpg"}
    result = gc.reconcile([(f"{TEAM}/screen-id/stb/2026-10/a.jpg", 10)], keys,
                          prefix=f"{TEAM}/")
    # The other team's row is outside the prefix: invisible to this run, not missing.
    assert result['missing'] == []
    assert result['listed'] == 1


def test_list_bucket_objects_paginates_past_1000(storage):
    for i in range(2500):
        storage.s3_client.objects[f"{TEAM}/screen-id/stb/2026-10/{i}.jpg"] = i + 1
    listed = gc.list_bucket_objects(storage)
    assert len(listed) == 2500
    assert storage.s3_client.paginate_calls == 1
    assert sorted(s for _k, s in listed)[:3] == [1, 2, 3]


def test_list_bucket_objects_honours_prefix(storage):
    storage.s3_client.objects = {
        f"{TEAM}/screen-id/stb/2026-10/a.jpg": 10,
        f"{TEAM}/focus/stb/2026-10/b.jpg": 20,
        f"{OTHER_TEAM}/screen-id/stb/2026-10/c.jpg": 30,
    }
    listed = gc.list_bucket_objects(storage, f"{TEAM}/screen-id/")
    assert [k for k, _s in listed] == [f"{TEAM}/screen-id/stb/2026-10/a.jpg"]


def test_fetch_db_object_keys_pages_past_the_max_rows_cap(monkeypatch):
    """A truncated key set would make every object past the cap look like an orphan."""
    rows = [{'team_id': TEAM, 'object_key': f"{TEAM}/screen-id/stb/2026-10/{i}.jpg"}
            for i in range(1500)]
    query = FakeQuery(rows)
    monkeypatch.setattr(gc.samples_db, 'get_supabase',
                        lambda: type('S', (), {'table': lambda _self, _t: query})())
    keys = gc.fetch_db_object_keys(page_size=1000)
    assert len(keys) == 1500
    assert query.page_sizes == [1000, 1000]


def test_fetch_db_object_keys_can_scope_one_team(monkeypatch):
    rows = _keys((TEAM, 'screen-id', 'stb', '2026-10', 'a'),
                 (OTHER_TEAM, 'screen-id', 'stb', '2026-10', 'b'))
    _install_db(monkeypatch, rows)
    keys = gc.fetch_db_object_keys(team_id=TEAM)
    assert keys == {f"{TEAM}/screen-id/stb/2026-10/a.jpg"}


def test_delete_objects_batches_at_1000(storage):
    keys = [f"{TEAM}/screen-id/stb/2026-10/{i}.jpg" for i in range(2300)]
    for k in keys:
        storage.s3_client.objects[k] = 10
    deleted, errors = gc.delete_objects(storage, keys)
    assert (deleted, errors) == (2300, [])
    assert storage.s3_client.delete_calls == 3
    assert storage.s3_client.objects == {}


def test_delete_objects_reports_per_key_failures(storage):
    storage.s3_client.objects = {f"{TEAM}/a.jpg": 1}
    storage.s3_client.delete_objects = lambda Bucket=None, Delete=None: {
        'Errors': [{'Key': o['Key'], 'Code': 'AccessDenied', 'Message': 'nope'}
                   for o in Delete['Objects']]}
    deleted, errors = gc.delete_objects(storage, [f"{TEAM}/a.jpg"])
    assert deleted == 0
    assert errors == [f"{TEAM}/a.jpg: AccessDenied nope"]


def test_main_dry_run_deletes_nothing(monkeypatch, storage, capsys):
    kept = f"{TEAM}/screen-id/stb/2026-10/kept.jpg"
    orphan = f"{TEAM}/screen-id/stb/2026-10/orphan.jpg"
    storage.s3_client.objects = {kept: 10, orphan: 20}
    _install_db(monkeypatch, [{'team_id': TEAM, 'object_key': kept}])

    assert gc.main([]) == 0
    out = capsys.readouterr().out
    assert 'DRY RUN' in out
    assert 'orphans (no row) : 1' in out
    assert storage.s3_client.deleted == []
    assert set(storage.s3_client.objects) == {kept, orphan}


def test_main_apply_deletes_only_the_orphans(monkeypatch, storage, capsys):
    kept = f"{TEAM}/screen-id/stb/2026-10/kept.jpg"
    orphan = f"{TEAM}/screen-id/stb/2026-10/orphan.jpg"
    storage.s3_client.objects = {kept: 10, orphan: 20}
    _install_db(monkeypatch, [{'team_id': TEAM, 'object_key': kept}])

    assert gc.main(['--apply']) == 0
    assert storage.s3_client.deleted == [orphan]
    assert set(storage.s3_client.objects) == {kept}


def test_main_refuses_past_max_delete(monkeypatch, storage, capsys):
    rows = [{'team_id': TEAM, 'object_key': f"{TEAM}/x.jpg"}]
    storage.s3_client.objects = {f"{TEAM}/{i}.jpg": 1 for i in range(5)}
    _install_db(monkeypatch, rows)

    assert gc.main(['--apply', '--max-delete', '2']) == 1
    assert storage.s3_client.deleted == []
    assert 'refusing to delete' in capsys.readouterr().out


def test_main_reports_reverse_drift_and_still_exits_clean(monkeypatch, storage, capsys):
    kept = f"{TEAM}/screen-id/stb/2026-10/kept.jpg"
    missing = f"{TEAM}/screen-id/stb/2026-10/gone.jpg"
    storage.s3_client.objects = {kept: 10}
    _install_db(monkeypatch, [{'team_id': TEAM, 'object_key': kept},
                              {'team_id': TEAM, 'object_key': missing}])

    assert gc.main([]) == 0
    out = capsys.readouterr().out
    assert 'missing objects  : 1' in out
    assert 'reported, never acted on' in out
    assert storage.s3_client.deleted == []


def test_main_refuses_when_training_storage_is_unconfigured(monkeypatch, capsys):
    for name in TRAINING_ENVS:
        monkeypatch.delenv(name, raising=False)
    assert gc.main(['--apply']) == 1
    assert 'training storage is not configured' in capsys.readouterr().out


def test_main_never_queries_the_database_when_unconfigured(monkeypatch):
    """The guard runs before anything else, so a dry run cannot touch the DB either."""
    for name in TRAINING_ENVS:
        monkeypatch.delenv(name, raising=False)

    def _boom():
        raise AssertionError("database must not be read when storage is unconfigured")

    monkeypatch.setattr(gc.samples_db, 'get_supabase', _boom)
    assert gc.main([]) == 1
