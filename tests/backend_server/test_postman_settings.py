"""
Postman connection settings — storage behind the page's "set it up" form.

Covers backend_server/src/lib/postman_settings.py (pure stdlib, no Flask) and the source-level
guards that keep the routes wired and permission-gated. The route file cannot be imported here
— the backend_server unit job has no Flask — so the wiring is checked by AST, the same way the
GitLab feature guards its entry point. That guard is the one that matters: a settings module with
no route behind it looks perfectly healthy and silently does nothing.
"""

import ast
import json
from pathlib import Path

import pytest

from backend_server.src.lib import postman_settings

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTES_FILE = PROJECT_ROOT / 'backend_server' / 'src' / 'routes' / 'server_postman_routes.py'
PERMISSIONS_FILE = PROJECT_ROOT / 'backend_server' / 'src' / 'routes' / 'server_permissions_routes.py'


@pytest.fixture(autouse=True)
def _config_path(monkeypatch, tmp_path):
    monkeypatch.setattr(postman_settings, 'CONFIG_PATH', tmp_path / 'postman_settings.json')
    monkeypatch.delenv('POSTMAN_API_KEY', raising=False)
    yield postman_settings.CONFIG_PATH


class TestStorage:
    def test_no_file_means_no_key(self):
        assert postman_settings.load() == {}
        assert postman_settings.runtime_api_key() == ''
        assert postman_settings.source() == ''

    def test_upsert_stores_and_reads_back(self, _config_path):
        assert postman_settings.upsert({'api_key': 'PMAK-abc', 'workspace_id': 'ws-1'})
        assert postman_settings.load() == {'api_key': 'PMAK-abc', 'workspace_id': 'ws-1'}

    def test_key_file_is_not_world_readable(self, _config_path):
        postman_settings.upsert({'api_key': 'PMAK-secret'})
        assert oct(_config_path.stat().st_mode)[-3:] == '600'

    def test_empty_key_on_update_keeps_the_stored_one(self):
        """The form never sends the key back, so saving only a workspace id must not wipe it."""
        postman_settings.upsert({'api_key': 'PMAK-abc'})
        postman_settings.upsert({'workspace_id': 'ws-2'})
        assert postman_settings.load()['api_key'] == 'PMAK-abc'
        assert postman_settings.load()['workspace_id'] == 'ws-2'

    def test_stored_key_beats_the_env_var(self, monkeypatch):
        monkeypatch.setenv('POSTMAN_API_KEY', 'PMAK-env')
        postman_settings.upsert({'api_key': 'PMAK-page'})
        assert postman_settings.effective_api_key() == 'PMAK-page'
        assert postman_settings.source() == 'settings'

    def test_env_var_still_works_with_nothing_saved(self, monkeypatch):
        """A deployment that has always used env vars keeps working with nothing configured."""
        monkeypatch.setenv('POSTMAN_API_KEY', 'PMAK-env')
        assert postman_settings.effective_api_key() == 'PMAK-env'
        assert postman_settings.source() == 'environment'

    def test_public_never_carries_the_key(self):
        postman_settings.upsert({'api_key': 'PMAK-secret', 'workspace_id': 'ws-1'})
        payload = json.dumps(postman_settings.public())
        assert 'PMAK-secret' not in payload
        assert postman_settings.public()['has_key'] is True
        assert postman_settings.public()['workspace_id'] == 'ws-1'

    def test_clear_removes_the_file(self, _config_path):
        postman_settings.upsert({'api_key': 'PMAK-abc'})
        assert postman_settings.clear() is True
        assert not _config_path.exists()
        assert postman_settings.runtime_api_key() == ''

    def test_broken_file_does_not_raise(self, _config_path):
        """A hand-edited or truncated file must not take the page down."""
        _config_path.parent.mkdir(parents=True, exist_ok=True)
        _config_path.write_text('{ not json', encoding='utf-8')
        assert postman_settings.load() == {}
        assert postman_settings.effective_api_key() == ''


class TestRouteWiring:
    """The module is only useful if the routes exist and are gated. Checked by AST, not import."""

    @staticmethod
    def _routes():
        tree = ast.parse(ROUTES_FILE.read_text(encoding='utf-8'))
        found = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef,)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                if dec.func.attr != 'route':
                    continue
                found.setdefault(dec.args[0].value, []).append((node, dec))
        return found

    def test_settings_endpoint_exists(self):
        assert '/settings' in self._routes(), 'the setup form has no backend to save into'

    @staticmethod
    def _methods(dec):
        """`methods=['POST']` is a list literal in the AST, not a Constant."""
        for kw in dec.keywords:
            if kw.arg != 'methods':
                continue
            value = kw.value
            if isinstance(value, ast.List):
                return {el.value for el in value.elts if isinstance(el, ast.Constant)}
            if isinstance(value, ast.Constant):
                return {value.value}
        return set()

    def test_writing_the_key_requires_the_manage_permission(self):
        """Without this gate any viewer could overwrite the server's Postman credential."""
        for node, dec in self._routes()['/settings']:
            if self._methods(dec) == {'POST'}:
                names = {
                    d.args[0].value for d in node.decorator_list
                    if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant)
                }
                assert 'plugins.postman:manage' in names, \
                    f'POST /settings is not gated: {names}'
                return
        pytest.fail('no POST /settings route found')

    def test_manage_permission_is_in_the_catalogue(self):
        """Un-grantable in the Settings UI: the key only lives in _ALL_PERMISSIONS."""
        tree = ast.parse(PERMISSIONS_FILE.read_text(encoding='utf-8'))
        perms = {
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.startswith('plugins.postman:')
        }
        assert 'plugins.postman:manage' in perms
        assert 'plugins.postman:view' in perms

    def test_workspaces_route_reads_the_saved_key(self):
        """The env var alone must not be the only source, or the page's Save does nothing."""
        source = ROUTES_FILE.read_text(encoding='utf-8')
        assert 'effective_api_key()' in source
        assert "os.getenv('POSTMAN_API_KEY')" not in source, \
            "load_config must not read POSTMAN_API_KEY directly — the settings store owns it"