"""The host's Chrome profile must not fill a saved login into a web app under test (TASK-135): the password manager
typed another account into an SSO form, and an agent built its whole tree logged in as that account."""
import importlib
import json

pu = importlib.import_module('backend_host.src.lib.utils.playwright_utils')


def _write(tmp_path, prefs):
    (tmp_path / 'Default').mkdir()
    p = tmp_path / 'Default' / 'Preferences'
    p.write_text(json.dumps(prefs))
    return p


def test_password_manager_and_autofill_are_turned_off(tmp_path):
    p = _write(tmp_path, {'credentials_enable_service': True, 'profile': {'exit_type': 'Normal', 'name': 'x'},
                          'autofill': {'profile_enabled': True}})
    pu.ChromeManager._fix_preferences(str(tmp_path))
    prefs = json.loads(p.read_text())
    assert prefs['credentials_enable_service'] is False
    assert prefs['credentials_enable_autosignin'] is False
    assert prefs['profile'] == {'exit_type': 'Normal', 'name': 'x', 'password_manager_enabled': False}
    assert prefs['autofill'] == {'profile_enabled': False, 'credit_card_enabled': False}


def test_crashed_exit_type_is_still_reset(tmp_path):
    p = _write(tmp_path, {'profile': {'exit_type': 'Crashed'}})
    pu.ChromeManager._fix_preferences(str(tmp_path))
    assert json.loads(p.read_text())['profile']['exit_type'] == 'Normal'


def test_a_broken_preferences_file_is_left_alone(tmp_path):
    (tmp_path / 'Default').mkdir()
    p = tmp_path / 'Default' / 'Preferences'
    p.write_text('{not json')
    pu.ChromeManager._fix_preferences(str(tmp_path))
    assert p.read_text() == '{not json'
