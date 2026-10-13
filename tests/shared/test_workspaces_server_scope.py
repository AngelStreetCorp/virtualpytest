"""Workspaces belong to a server: servers sharing one database list only their own.

vpt-pi1's RPI1-server reads the same Supabase as Awesomation, so before `server_name` existed
both servers listed every workspace. Every workspace has an owner; there is no "shared" one.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from shared.src.lib.database import workspaces_db  # noqa: E402

ROWS = [
    {'id': 'mine', 'name': 'TV', 'slug': 'tv', 'server_name': 'Awesomation',
     'created_at': 't', 'updated_at': 't'},
    {'id': 'theirs', 'name': 'Pi', 'slug': 'pi', 'server_name': 'RPI1-server',
     'created_at': 't', 'updated_at': 't'},
    {'id': 'mine2', 'name': 'Streams', 'slug': 'streams', 'server_name': 'Awesomation',
     'created_at': 't', 'updated_at': 't'},
]


class _Result:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _Query:
    def __init__(self, client, table):
        self.client, self.table, self.filters, self.payload, self.op = client, table, {}, None, 'select'
        self._single = False

    def select(self, *_a, **_kw):
        return self

    def order(self, *_a, **_kw):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def single(self):
        self._single = True
        return self

    def insert(self, payload):
        self.op, self.payload = 'insert', payload
        return self

    def update(self, payload):
        self.op, self.payload = 'update', payload
        return self

    def execute(self):
        if self.table == 'workspace_members':
            return _Result([], count=0)
        if self.op in ('insert', 'update'):
            self.client.writes.append((self.op, dict(self.payload)))
            return _Result([{**ROWS[0], **self.payload}])
        rows = [r for r in ROWS if all(r.get(k) == v for k, v in self.filters.items())]
        if self._single:
            return _Result(rows[0] if rows else None)
        return _Result(rows)


class _Client:
    def __init__(self):
        self.writes = []

    def table(self, name):
        return _Query(self, name)


@pytest.fixture
def client(monkeypatch):
    c = _Client()
    monkeypatch.setattr(workspaces_db, 'get_supabase', lambda: c)
    monkeypatch.setenv('SERVER_NAME', 'Awesomation')
    return c


def test_list_shows_own_only(client):
    assert [w['id'] for w in workspaces_db.get_all_workspaces()] == ['mine', 'mine2']


def test_another_servers_workspace_reads_as_missing(client):
    assert workspaces_db.get_workspace('theirs') is None
    assert workspaces_db.get_workspace('mine')['server_name'] == 'Awesomation'


def test_server_without_a_name_sees_nothing_and_cannot_create(client, monkeypatch):
    monkeypatch.delenv('SERVER_NAME')
    assert workspaces_db.get_all_workspaces() == []
    with pytest.raises(workspaces_db.NoServerNameError):
        workspaces_db.create_workspace({'name': 'New'})
    assert client.writes == []


def test_create_belongs_to_this_server_whatever_the_caller_sends(client):
    workspaces_db.create_workspace({'name': 'New'})
    workspaces_db.create_workspace({'name': 'Sneaky', 'server_name': 'RPI1-server', 'shared': True})
    assert [w['server_name'] for _, w in client.writes] == ['Awesomation', 'Awesomation']


def test_update_never_changes_the_owner(client):
    workspaces_db.update_workspace('mine', {'name': 'Renamed', 'server_name': 'RPI1-server', 'shared': True})
    assert 'server_name' not in client.writes[0][1]


def test_duplicate_slug_is_per_server():
    """Only the (server_name, slug) constraint means "taken": another server may reuse the slug."""
    taken_here = Exception("{'code': '23505', 'message': 'duplicate key value violates unique "
                           "constraint \"workspaces_server_name_slug_key\"'}")
    assert workspaces_db._is_duplicate_slug(taken_here)
    assert 'on this server' in str(workspaces_db.DuplicateSlugError('streams'))
