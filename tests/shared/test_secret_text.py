import pytest

from shared.src.lib.utils.secret_text import has_secret_placeholder, resolve_secret_text


def test_resolves_app_login_and_password(monkeypatch):
    monkeypatch.setenv('XTEL_APP_LOGIN', '0600000000')
    value, shown = resolve_secret_text('{env:XTEL_APP_LOGIN}')
    assert value == '0600000000' and shown == '{env:XTEL_APP_LOGIN}'


def test_other_names_stay_literal(monkeypatch):
    monkeypatch.setenv('API_KEY', 'secret')
    assert resolve_secret_text('{env:API_KEY}') == ('{env:API_KEY}', '{env:API_KEY}')
    assert not has_secret_placeholder('{env:API_KEY}')


def test_missing_name_raises_name_only(monkeypatch):
    monkeypatch.delenv('XTEL_APP_PASSWORD', raising=False)
    with pytest.raises(KeyError) as err:
        resolve_secret_text('{env:XTEL_APP_PASSWORD}')
    assert err.value.args[0] == 'XTEL_APP_PASSWORD'
