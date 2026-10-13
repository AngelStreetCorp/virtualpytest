"""
tests/backend_host/test_exploration_home_screenshot.py — AI generation gives the start node its screenshot.

The generation creates the screens it found and saves each one's screenshot; the start node
(`home`) already exists, so no suggestion carries it, although Start took and uploaded its
screenshot. Approving the node verifications now attaches that screenshot to `home` when it has
none, so every node of the built tree shows one (TASK-40).
"""
import threading

import pytest

vm = pytest.importorskip('backend_host.src.services.ai_exploration.phases.verification_manager')


class Executor:
    def __init__(self):
        self._lock = threading.Lock()
        self.exploration_state = {
            'status': 'awaiting_node_verification',
            'tree_id': 'tree',
            'userinterface_name': 'ui',
            'home_id': 'home',
            'current_analysis': {'screenshot': 'navigation/ui/home_initial.jpg'},
        }


@pytest.fixture
def db(monkeypatch):
    nodes = {
        'home': {'node_id': 'home', 'label': 'home', 'data': {}},
        'search': {'node_id': 'search', 'label': 'search', 'data': {}},
    }
    saved = []
    monkeypatch.setattr(vm, 'get_node_by_id', lambda tree, nid, team: {'success': True, 'node': dict(nodes[nid])})
    monkeypatch.setattr(vm, 'save_nodes_batch', lambda tree, batch, team: saved.extend(batch) or {'success': True})
    return nodes, saved


def approve(screenshot='navigation/ui/search.jpg'):
    return vm.approve_node_verifications(
        Executor(), [{'node_id': 'search', 'verification': None, 'screenshot_url': screenshot}], 'team')


def test_home_gets_the_start_screenshot(db):
    _, saved = db
    approve()
    by_id = {n['node_id']: n for n in saved}
    assert by_id['search']['data']['screenshot'] == 'navigation/ui/search.jpg'
    assert by_id['home']['data']['screenshot'] == 'navigation/ui/home_initial.jpg'


def test_home_keeps_its_own_screenshot(db):
    nodes, saved = db
    nodes['home']['data'] = {'screenshot': 'navigation/ui/home.jpg'}
    approve()
    assert [n['node_id'] for n in saved] == ['search']
