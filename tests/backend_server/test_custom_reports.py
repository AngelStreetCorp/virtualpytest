"""Custom reports: private to creator within team, versioned + revalidated definitions."""

import os
import sys

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.backend_server import _task42_services_common as common  # noqa: E402
from backend_server.src.routes.server_custom_reports_routes import server_custom_reports_bp  # noqa: E402

pytestmark = pytest.mark.unit

VIEW = ['reports.tests:view']
BODY = {'name': 'Failures this week', 'filter': {'schema_version': 1, 'tql': 'status:failed since:7d'},
        'columns': ['script_name', 'status'], 'chart': {'type': 'status_share'}}


def client_for(monkeypatch, fake=None, user=common.USER_A):
    fake = fake or common.install(monkeypatch)
    return fake, common.make_app(server_custom_reports_bp, user_id=user, permissions=VIEW).test_client()


def test_create_stores_versioned_definition_for_creator(monkeypatch):
    fake, client = client_for(monkeypatch)
    resp = client.post('/server/custom-reports', json={'team_id': common.TEAM_A, **BODY})
    assert resp.status_code == 201
    stored = fake.tables['custom_reports'][0]
    assert stored['team_id'] == common.TEAM_A and stored['created_by'] == common.USER_A
    assert stored['schema_version'] == 1
    assert stored['filter']['tql'] == 'status:failed since:7d'
    body = resp.get_json()
    assert body['valid'] is True and body['filter'] == {'schema_version': 1, 'tql': 'status:failed since:7d'}
    assert body['chart'] == {'type': 'status_share'}


def test_another_user_of_the_same_team_cannot_read_update_or_delete(monkeypatch):
    fake, owner = client_for(monkeypatch)
    report_id = owner.post('/server/custom-reports', json={'team_id': common.TEAM_A, **BODY}).get_json()['id']
    _, other = client_for(monkeypatch, fake=fake, user=common.USER_B)
    assert other.get('/server/custom-reports', query_string={'team_id': common.TEAM_A}).get_json()['items'] == []
    assert other.get(f'/server/custom-reports/{report_id}', query_string={'team_id': common.TEAM_A}).status_code == 404
    assert other.patch(f'/server/custom-reports/{report_id}', json={'team_id': common.TEAM_A, 'name': 'x'}).status_code == 404
    assert other.delete(f'/server/custom-reports/{report_id}', query_string={'team_id': common.TEAM_A}).status_code == 404
    assert fake.tables['custom_reports'][0]['name'] == 'Failures this week'


def test_cross_team_id_does_not_match(monkeypatch):
    fake, client = client_for(monkeypatch)
    report_id = client.post('/server/custom-reports', json={'team_id': common.TEAM_A, **BODY}).get_json()['id']
    assert client.get(f'/server/custom-reports/{report_id}', query_string={'team_id': common.TEAM_B}).status_code == 404


@pytest.mark.parametrize('change', [
    {'filter': {'schema_version': 1, 'tql': 'drop:table'}},
    {'columns': ['script_name', 'logs_r2_url']},
    {'chart': {'type': 'sql'}},
    {'name': ''},
    {'name': 'x' * 121},
])
def test_invalid_definitions_are_rejected(monkeypatch, change):
    _, client = client_for(monkeypatch)
    assert client.post('/server/custom-reports', json={'team_id': common.TEAM_A, **BODY, **change}).status_code == 400


def test_patch_merges_and_revalidates(monkeypatch):
    fake, client = client_for(monkeypatch)
    report_id = client.post('/server/custom-reports', json={'team_id': common.TEAM_A, **BODY}).get_json()['id']
    resp = client.patch(f'/server/custom-reports/{report_id}', json={
        'team_id': common.TEAM_A, 'chart': {'type': 'status_by_group', 'group_by': 'device_name'}})
    assert resp.status_code == 200
    assert resp.get_json()['chart'] == {'type': 'status_by_group', 'group_by': 'device_name'}
    assert resp.get_json()['filter']['tql'] == 'status:failed since:7d'
    assert client.patch(f'/server/custom-reports/{report_id}', json={'team_id': common.TEAM_A, 'sql': 'x'}).status_code == 400


def test_stored_definition_that_no_longer_validates_is_flagged_on_load(monkeypatch):
    fake, client = client_for(monkeypatch)
    fake.tables['custom_reports'] = [{
        'id': common.new_id(), 'team_id': common.TEAM_A, 'created_by': common.USER_A, 'name': 'old',
        'schema_version': 0, 'filter': {'tql': 'status:failed'}, 'columns': [], 'chart': {'type': 'none'},
    }]
    item = client.get('/server/custom-reports', query_string={'team_id': common.TEAM_A}).get_json()['items'][0]
    assert item['valid'] is False
    assert item['validation_error']['field'] == 'filter.schema_version'
