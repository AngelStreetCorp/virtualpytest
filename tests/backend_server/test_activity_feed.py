"""TASK-127 G6: the activity feed merges, filters and counts rows from the audit sources."""
from datetime import datetime, timedelta, timezone

from shared.src.lib.database import activity_db


def _row(event, actor, ago_h, target='t'):
    at = (datetime.now(timezone.utc) - timedelta(hours=ago_h)).isoformat()
    return {'at': at, 'event': event, 'tone': 'ok', 'target': target, 'details': '', 'actor': actor, 'source': 'x'}


def test_filters_counts_and_order(monkeypatch):
    monkeypatch.setattr(activity_db, 'masterchief_events',
                        lambda t, c: [_row('Elevated op done', 'a@x', 5), _row('Elevated op refused', 'b@x', 1, 'restart')])
    monkeypatch.setattr(activity_db, 'localize_events', lambda t, c: [_row('Localize corrected', 'a@x', 3)])
    out = activity_db.list_activity('team')
    assert [r['event'] for r in out['rows']] == ['Elevated op refused', 'Localize corrected', 'Elevated op done']
    assert out['actors'] == ['a@x', 'b@x']
    only_a = activity_db.list_activity('team', actor='a@x', event='Localize corrected')
    assert len(only_a['rows']) == 1 and only_a['counts'] == {'Elevated op done': 1, 'Localize corrected': 1}
    assert len(activity_db.list_activity('team', q='RESTART')['rows']) == 1


def test_since_is_capped_and_bad_values_fall_back():
    now = datetime.now(timezone.utc)
    assert now - activity_db.parse_since('999d') < timedelta(days=91)
    assert now - activity_db.parse_since('nonsense') < timedelta(days=31)


def test_missing_source_is_skipped(monkeypatch):
    def boom(t, c):
        raise RuntimeError("PGRST205 Could not find the table 'public.masterchief_audit'")
    monkeypatch.setattr(activity_db, 'masterchief_events', boom)
    monkeypatch.setattr(activity_db, 'localize_events', lambda t, c: [_row('Localize corrected', 'a@x', 3)])
    # `audit` joined list_activity's sources; leaving it unstubbed let the real query run, and on
    # a database without the table it raised PGRST205 too and landed in skipped_sources, so the
    # assertion below was really testing which tables this machine happens to have. Stub every
    # source the test reasons about.
    monkeypatch.setattr(activity_db, 'audit_events', lambda t, c: [])
    out = activity_db.list_activity('team')
    assert out['skipped_sources'] == ['masterchief'] and len(out['rows']) == 1
