"""Runtime-written integration state must live outside the deploy tree (BUG-0187)."""

from pathlib import Path

import pytest

from backend_server.src.lib.utils import integration_state

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_default_is_service_user_config_dir(monkeypatch):
    monkeypatch.delenv('VPT_CONFIG_DIR', raising=False)
    assert integration_state.state_path('testrail.json') == \
        Path.home() / '.config' / 'virtualpytest' / 'testrail.json'


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv('VPT_CONFIG_DIR', str(tmp_path))
    assert integration_state.state_path('jira_instances.json') == tmp_path / 'jira_instances.json'


def test_blank_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv('VPT_CONFIG_DIR', '  ')
    assert integration_state.state_dir() == Path.home() / '.config' / 'virtualpytest'


def test_writers_never_target_the_project_tree():
    # rsync --delete wipes anything under the project root that is not in git.
    from backend_server.src.integrations import slack_sync, testrail_service
    from backend_server.src.routes import server_integrations_routes as routes

    paths = [
        testrail_service._CONFIG_PATH,
        slack_sync.CONFIG_PATH,
        slack_sync.THREADS_PATH,
        routes.JIRA_CONFIG_PATH,
        routes.SLACK_CONFIG_PATH,
        routes.THREADS_PATH,
        routes.TESTRAIL_CONFIG_PATH,
    ]
    for path in paths:
        assert not path.resolve().is_relative_to(PROJECT_ROOT), path
