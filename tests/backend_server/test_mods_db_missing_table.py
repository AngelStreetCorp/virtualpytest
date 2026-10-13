"""mods_db degrades gracefully when the mods tables were never created.

features/mods/db/*.sql are applied by hand, not by any deploy script, so a site can
run the mods feature against a database that has never had them. PostgREST then
answers PGRST205 ("Could not find the table ... in the schema cache"). That is a
deployment gap, not a server fault: the frontend already keeps mod choices and
widget layouts in the browser when the fetch fails, so the routes must not turn it
into a 500 that only shows up as console noise. Offline, no database.
"""

import pytest

from features.mods.lib import mods_db

pytestmark = pytest.mark.unit


class PostgrestError(Exception):
    """Shaped like the object the supabase client raises (it carries `.code`)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{{'message': {message!r}, 'code': {code!r}}}")
        self.code = code


MISSING_PREFS = PostgrestError(
    'PGRST205',
    "Could not find the table 'public.user_mod_preferences' in the schema cache",
)
MISSING_LAYOUTS = PostgrestError(
    'PGRST205',
    "Could not find the table 'public.user_widget_layouts' in the schema cache",
)
MISSING_RELATIONSHIP = PostgrestError(
    'PGRST200',
    "Could not find a relationship between 'a' and 'b' in the schema cache",
)
class TimeoutError_(Exception):
    """A transport failure: not our business to swallow, it must keep propagating."""


TIMEOUT = TimeoutError_('read timeout')


class _Query:
    """Stands in for a PostgREST query builder that raises or returns rows.

    Chainable the way the real one is (`.select().eq().eq().limit().execute()`);
    every link returns self, so a test only cares about execute().
    """

    def __init__(self, data=None, error=None):
        self._data, self._error = data, error

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def upsert(self, *a, **k):
        return self

    def execute(self):
        if self._error is not None:
            raise self._error
        return type('Result', (), {'data': self._data})()


class _TableClient:
    """Stands in for the supabase client: every table raises the same error."""

    def __init__(self, error):
        self._error = error

    def table(self, _name):
        return _Query(error=self._error)


def test_missing_table_error_is_recognised():
    assert mods_db._missing_table(MISSING_PREFS)
    assert mods_db._missing_table(MISSING_LAYOUTS)
    assert mods_db._missing_table(PostgrestError('42P01', 'relation does not exist'))


def test_other_errors_are_not_swallowed():
    # PGRST200 is a real bug (a broken query), and a timeout is a real outage:
    # both must keep propagating so the route still reports them.
    assert not mods_db._missing_table(MISSING_RELATIONSHIP)
    assert not mods_db._missing_table(TIMEOUT)


def test_a_read_of_a_missing_table_returns_no_rows():
    assert mods_db._read_rows(_Query(error=MISSING_PREFS), mods_db.TABLE) == []
    assert mods_db._read_rows(_Query(error=MISSING_LAYOUTS), mods_db.LAYOUT_TABLE) == []


def test_a_read_still_returns_real_rows():
    rows = [{'mod_id': 'run-progress', 'enabled': True}]
    assert mods_db._read_rows(_Query(data=rows), mods_db.TABLE) == rows
    assert mods_db._read_rows(_Query(data=None), mods_db.TABLE) == []


def test_a_read_of_another_error_raises():
    with pytest.raises(PostgrestError):
        mods_db._read_rows(_Query(error=MISSING_RELATIONSHIP), mods_db.TABLE)
    with pytest.raises(TimeoutError_):
        mods_db._read_rows(_Query(error=TIMEOUT), mods_db.LAYOUT_TABLE)


def test_a_write_to_a_missing_table_is_a_no_op():
    # The browser already holds the change (useEnabledMods warns), so the PUT must
    # still answer 200 instead of failing the switch the user just made.
    assert mods_db._write(_Query(error=MISSING_PREFS), mods_db.TABLE) is None
    assert mods_db._write(_Query(error=MISSING_LAYOUTS), mods_db.LAYOUT_TABLE) is None


def test_a_write_of_another_error_raises():
    with pytest.raises(TimeoutError_):
        mods_db._write(_Query(error=TIMEOUT), mods_db.TABLE)


def test_get_choices_returns_empty_when_the_table_is_missing(monkeypatch):
    """The exact 500 seen in the field: get_choices must yield {}, not blow up."""
    monkeypatch.setattr(mods_db, 'get_supabase_client', lambda: _TableClient(MISSING_PREFS))
    assert mods_db.get_choices('team-1', 'user-1') == {}


def test_get_widget_layout_returns_none_when_the_table_is_missing(monkeypatch):
    monkeypatch.setattr(mods_db, 'get_supabase_client', lambda: _TableClient(MISSING_LAYOUTS))
    assert mods_db.get_widget_layout('team-1', 'user-1', 'dashboard') is None


def test_get_choices_still_propagates_a_real_error(monkeypatch):
    monkeypatch.setattr(mods_db, 'get_supabase_client', lambda: _TableClient(TIMEOUT))
    with pytest.raises(TimeoutError_):
        mods_db.get_choices('team-1', 'user-1')


def test_get_choices_returns_real_rows(monkeypatch):
    client = type('C', (), {'table': lambda self, name: _Query(
        data=[{'mod_id': 'blast-radius', 'enabled': False}])})()
    monkeypatch.setattr(mods_db, 'get_supabase_client', lambda: client)
    assert mods_db.get_choices('team-1', 'user-1') == {'blast-radius': False}