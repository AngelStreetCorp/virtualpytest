"""ZammadProvider (features/zammad/lib) against a mocked HTTP layer (TASK-96 G2)."""

import pytest

from features.zammad.lib import Attachment, SupportError, SupportNotConfigured, TicketFields
from features.zammad.lib.model import FAMILIES, group_for, map_status, reporter_status
from features.zammad.lib.zammad import ZammadProvider

pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.responses.pop(0)


HOST_BUG = TicketFields(ticket_type='bug', family='platform', category='host', frequency='frequent',
                        priority='P0', severity='major', target_id='h1', target_label='Pi 1')


def provider(*responses):
    session = FakeSession(*responses)
    return ZammadProvider('https://z.example/', 'secret-token', session), session


def test_create_ticket_maps_group_customer_and_attachment():
    p, s = provider(FakeResponse({'id': 7, 'number': '10007', 'state': 'new', 'title': 'Boom'}))
    ref = p.create_ticket(title='Boom', body='details', fields=HOST_BUG, requester_email='a@b.io',
                          attachments=[Attachment('s.png', 'QUJD', 'image/png')])
    method, url, kw = s.calls[0]
    assert (method, url) == ('POST', 'https://z.example/api/v1/tickets')
    assert kw['headers']['Authorization'] == 'Token token=secret-token'
    assert kw['json']['group'] == 'Hosts & System'
    assert kw['json']['customer_id'] == 'guess:a@b.io'
    assert kw['json']['article']['attachments'] == [{'filename': 's.png', 'data': 'QUJD', 'mime-type': 'image/png'}]
    assert (ref.external_id, ref.number, ref.status) == ('7', '10007', 'new')
    sent = kw['json']
    assert (sent['vpt_type'], sent['vpt_family'], sent['vpt_category']) == ('bug', 'platform', 'host')
    assert (sent['vpt_severity'], sent['vpt_frequency'], sent['vpt_target']) == ('major', 'frequent', 'Pi 1 (h1)')
    assert sent['priority_id'] == 3


def test_priority_maps_to_zammad_priority_id():
    for prio, pid in (('P0', 3), ('P1', 2), ('P2', 1)):
        p, s = provider(FakeResponse({'id': 9, 'state': 'new', 'title': 't'}))
        p.create_ticket(title='t', body='b', requester_email='a@b.io', fields=TicketFields(
            ticket_type='request', family='ai', category='agent', frequency='once', priority=prio))
        assert s.calls[0][2]['json']['priority_id'] == pid


def test_request_has_no_severity_attribute():
    p, s = provider(FakeResponse({'id': 8, 'state': 'new', 'title': 't'}))
    p.create_ticket(title='t', body='b', requester_email='a@b.io', fields=TicketFields(
        ticket_type='request', family='ai', category='agent', frequency='once'))
    sent = s.calls[0][2]['json']
    assert 'vpt_severity' not in sent and 'vpt_target' not in sent and sent['group'] == 'Platform'


def test_every_family_category_has_a_group():
    expected = {
        'server': 'Hosts & System', 'host': 'Hosts & System', 'service': 'Hosts & System', 'device': 'Devices',
        'script': 'Scripts', 'campaign': 'Scripts', 'virtual_script': 'Scripts', 'testcase': 'Scripts',
        'heatmap': 'Hosts & System', 'timeline': 'Hosts & System', 'incident': 'Hosts & System',
        'grafana': 'Dashboards', 'report': 'Dashboards', 'agent': 'Platform',
    }
    got = {c: group_for(f, c) for f, cats in FAMILIES.items() for c in cats}
    assert got == expected


def test_unknown_family_rejected():
    p, _ = provider()
    with pytest.raises(SupportError):
        p.create_ticket(title='x', body='y', requester_email='a@b.io', fields=TicketFields(
            ticket_type='bug', family='nope', category='host', frequency='once', severity='minor'))


def test_zammad_states_map_to_workflow_and_reporter_words():
    assert map_status('in progress') == 'in_progress' and map_status("won't fix") == 'wont_fix'
    assert map_status('pending reminder') == 'need_info' and map_status('merged') == 'duplicate'
    assert map_status('new') == 'new'
    assert [reporter_status(x) for x in ('new', 'fixed', 'need_info', 'delivered', 'duplicate')] == [
        'open', 'in_progress', 'waiting', 'delivered', 'closed']


def test_list_articles_hides_internal_notes():
    p, _ = provider(FakeResponse([
        {'id': 1, 'from': 'Ann', 'body': 'hi', 'sender': 'Customer', 'internal': False, 'attachments': []},
        {'id': 2, 'from': 'Agent', 'body': 'secret', 'sender': 'Agent', 'internal': True},
        {'id': 3, 'from': 'Agent', 'body': 'answer', 'sender': 'Agent', 'internal': False,
         'attachments': [{'id': 9, 'filename': 'log.txt', 'size': '12'}]},
    ]))
    articles = p.list_articles('7')
    assert [a.id for a in articles] == ['1', '3']
    assert articles[0].from_customer and not articles[1].from_customer
    assert articles[1].attachments[0]['filename'] == 'log.txt'


def test_add_reply_posts_customer_article():
    p, s = provider(FakeResponse({'id': 11, 'body': 'thanks'}))
    article = p.add_reply('7', body='thanks', author_email='a@b.io')
    payload = s.calls[0][2]['json']
    assert payload['ticket_id'] == 7 and payload['sender'] == 'Customer' and payload['internal'] is False
    assert article.id == '11' and article.from_customer


def test_close_and_status_mapping():
    p, s = provider(FakeResponse({'id': 7, 'state': 'closed', 'title': 't'}))
    assert p.close('7').status == 'closed'
    assert s.calls[0][2]['json'] == {'state': 'closed'}


def test_http_error_does_not_leak_token_or_body():
    p, _ = provider(FakeResponse({'error': 'secret-token echoed'}, 401))
    with pytest.raises(SupportError) as err:
        p.get_ticket('1')
    assert 'secret-token' not in str(err.value) and err.value.status == 401


def test_not_configured(monkeypatch):
    monkeypatch.delenv('ZAMMAD_URL', raising=False)
    monkeypatch.delenv('ZAMMAD_API_TOKEN', raising=False)
    with pytest.raises(SupportNotConfigured):
        ZammadProvider('', '').get_ticket('1')


def test_set_status_uses_workflow_state_and_gives_need_info_a_reminder():
    p, s = provider(FakeResponse({'id': 7, 'state': 'need info'}), FakeResponse({'id': 7, 'state': 'in progress'}))
    assert p.set_status('7', 'need_info').status == 'need_info'
    assert s.calls[0][2]['json']['state'] == 'need info' and 'pending_time' in s.calls[0][2]['json']
    p.set_status('7', 'in_progress')
    assert s.calls[1][2]['json'] == {'state': 'in progress'}
    with pytest.raises(SupportError):
        p.set_status('7', 'bogus')


def test_list_tickets_skips_failures():
    p, _ = provider(FakeResponse({'id': 1, 'state': 'open', 'title': 'a'}), FakeResponse({}, 404))
    assert [r.external_id for r in p.list_tickets(['1', '2'])] == ['1']


@pytest.mark.skipif(not (__import__('os').getenv('ZAMMAD_URL') and __import__('os').getenv('ZAMMAD_API_TOKEN')),
                    reason='ZAMMAD_URL / ZAMMAD_API_TOKEN not set')
def test_live_create_reply_read_close():
    p = ZammadProvider(__import__('os').environ['ZAMMAD_URL'], __import__('os').environ['ZAMMAD_API_TOKEN'])
    assert p.whoami().get('email')
    fields = TicketFields(ticket_type='bug', family='scripting', category='script', frequency='once',
                          severity='minor', target_id='live_test', target_label='live test script')
    ref = p.create_ticket(title='VPT live test (safe to close)', body='created by the unit test',
                          fields=fields, requester_email='vpt-live-test@example.com')
    try:
        p.add_reply(ref.external_id, body='reply from the test', author_email='vpt-live-test@example.com')
        bodies = [a.body for a in p.list_articles(ref.external_id)]
        assert 'reply from the test' in bodies
        assert ref.status == 'new'
        # the vpt_* attributes and the workflow states exist on the instance (setup_zammad.py)
        row = p._request('GET', f'/tickets/{ref.external_id}')
        assert (row['vpt_type'], row['vpt_family'], row['vpt_category']) == ('bug', 'scripting', 'script')
        assert (row['vpt_severity'], row['vpt_frequency']) == ('minor', 'once')
        assert row['priority_id'] == 2
        for status in ('in_progress', 'need_info', 'fixed', 'delivered', 'wont_fix'):
            assert p.set_status(ref.external_id, status).status == status
    finally:
        assert p.close(ref.external_id).status == 'closed'
