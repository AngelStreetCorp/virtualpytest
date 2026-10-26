"""TASK-159 G7: the duplicate report and the soft merge (never a DELETE)."""
import importlib.util
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
spec = importlib.util.spec_from_file_location('screen_registry_merge', os.path.join(ROOT, 'scripts/screen_registry_merge.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

FULL = 'ab' * 32
CENTER = 'cd' * 32
OTHER = '5a' * 32


def flip(hexstr, bits):
    n = int(hexstr, 16) ^ (((1 << bits) - 1) << (len(hexstr) * 4 - bits))
    return format(n, f'0{len(hexstr)}x')


def r(i, **kw):
    base = {'id': i, 'team_id': 't', 'scope': 'h/device3', 'incident_type': 'freeze', 'dhash': FULL,
            'region_center': CENTER, 'label': None, 'source': 'none', 'seen_count': 1, 'first_seen': '2026-10-01',
            'has_thumb': False}
    base.update(kw)
    return base


def test_freeze_and_abstain_rows_of_one_picture_merge_keeping_the_name():
    rows = [r('f', label='unknown_4', seen_count=17, source='none'),
            r('a', incident_type='localize_abstain', dhash=flip(FULL, 5), label='Full-screen poster', seen_count=37),
            r('x', dhash=OTHER, region_center=OTHER)]
    groups = m.plan_merges(rows)
    assert len(groups) == 1
    assert groups[0]['keep']['id'] == 'a' and [d['id'] for d in groups[0]['dups']] == ['f']


def test_a_human_label_wins_and_unknown_n_loses_to_a_name():
    u = r('u', label='unknown_2', seen_count=50)
    assert m.plan_merges([u, r('h', label='Welcome', source='human', seen_count=1)])[0]['keep']['id'] == 'h'
    assert m.plan_merges([u, r('n', label='Splash screen', seen_count=2)])[0]['keep']['id'] == 'n'


def test_scopes_never_mix():
    assert m.plan_merges([r('a'), r('b', scope='h/device2')]) == []


def test_sql_is_a_soft_merge_without_delete():
    sql = m.render_sql(m.plan_merges([r('a', seen_count=3), r('b', seen_count=2)]))
    assert 'merged_into' in sql and 'seen_count = 5' in sql
    assert 'DELETE' not in sql.upper() and 'DROP' not in sql.upper()


def test_two_named_rows_of_one_picture_are_not_merged():
    rows = [r('a', label='Splash screen', seen_count=5), r('b', label='Welcome', seen_count=3)]
    assert m.plan_merges(rows) == []
    assert len(m.plan_merges.conflicts) == 1
    rows = [r('a', label='x', source='human'), r('b', label='unknown_1')]
    assert len(m.plan_merges(rows)) == 1
