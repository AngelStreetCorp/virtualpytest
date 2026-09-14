"""
Pure-python tests for the fingerprint ranking logic in ai_userinterface_db
(_rank_fingerprint_matches and friends). No DB, no supabase package — the
supabase_utils import is stubbed, so this runs anywhere:

    python3 shared/src/lib/database/test_ai_userinterface_resolve.py

Covers the deterministic resolve rule documented in
docs/agent/navigation/AI_USERINTERFACE.md:
  1. most literal characters wins;
  2. tie-break fewest wildcards;
  3. tie-break newest added_at.
"""

import importlib.util
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Import ai_userinterface_db with its only external dependency stubbed out.
# ---------------------------------------------------------------------------

for _name in ('shared', 'shared.src', 'shared.src.lib', 'shared.src.lib.utils'):
    if _name not in sys.modules:
        sys.modules[_name] = types.ModuleType(_name)
_stub = types.ModuleType('shared.src.lib.utils.supabase_utils')
_stub.get_supabase_client = lambda: None
sys.modules['shared.src.lib.utils.supabase_utils'] = _stub

_spec = importlib.util.spec_from_file_location(
    'ai_userinterface_db_under_test',
    Path(__file__).resolve().parent / 'ai_userinterface_db.py',
)
db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db)


def _row(pattern, added_at='2026-01-01T00:00:00+00:00', ui='A'):
    return {'pattern': pattern, 'added_at': added_at, 'ai_userinterface_id': ui}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_specificity_most_literals_wins():
    rows = [
        _row('EXSTB001-*', ui='broad'),
        _row('EXSTB001-FWR-PRD-04.02-*', ui='specific'),
    ]
    ranked = db._rank_fingerprint_matches(rows, 'EXSTB001-FWR-PRD-04.02-163-AL-AL-x')
    assert [r['ai_userinterface_id'] for r in ranked] == ['specific', 'broad'], ranked


def test_order_independence():
    """Ranking must not depend on DB row order (the original bug)."""
    rows = [
        _row('EXSTB001-FWR-PRD-04.02-*', ui='specific'),
        _row('EXSTB001-*', ui='broad'),
    ]
    ranked = db._rank_fingerprint_matches(rows, 'EXSTB001-FWR-PRD-04.02-163')
    assert ranked[0]['ai_userinterface_id'] == 'specific', ranked


def test_tiebreak_fewest_wildcards():
    # Both have 4 literal chars; 'ABCD*' has 1 wildcard, 'AB*CD*' has 2.
    rows = [_row('AB*CD*', ui='two_wc'), _row('ABCD*', ui='one_wc')]
    ranked = db._rank_fingerprint_matches(rows, 'ABCDX')
    assert [r['ai_userinterface_id'] for r in ranked] == ['one_wc', 'two_wc'], ranked


def test_tiebreak_newest_added_at():
    rows = [
        _row('ABCD*', added_at='2026-01-01T00:00:00+00:00', ui='old'),
        _row('ABCD*', added_at='2026-06-01T00:00:00+00:00', ui='new'),
    ]
    ranked = db._rank_fingerprint_matches(rows, 'ABCDX')
    assert [r['ai_userinterface_id'] for r in ranked] == ['new', 'old'], ranked


def test_no_match_returns_empty():
    rows = [_row('EXSTB001-*'), _row('XYZ-*')]
    assert db._rank_fingerprint_matches(rows, 'HUMAX-1.0') == []


def test_equality_mode_ignores_globs():
    rows = [_row('com.netflix.*', ui='globby'), _row('com.netflix.ninja', ui='exact')]
    ranked = db._rank_fingerprint_matches(rows, 'com.netflix.ninja', glob=False)
    assert [r['ai_userinterface_id'] for r in ranked] == ['exact'], ranked


def test_literal_and_wildcard_counts():
    assert db._pattern_literal_count('EXSTB001-*') == 9
    assert db._pattern_wildcard_count('EXSTB001-*') == 1
    assert db._pattern_literal_count('A?B[xy]*') == 4   # A, B, x, y
    assert db._pattern_wildcard_count('A?B[xy]*') == 4  # ? [ ] *


def test_prefix_overlap_near_miss():
    value = 'EXSTB001-FWR-PRD-05.01-163'
    # Literal prefix of the pattern is 'EXSTB001-FWR-PRD-04.02-';
    # common prefix with value is 'EXSTB001-FWR-PRD-0' = 18 chars.
    assert db._prefix_overlap(value, 'EXSTB001-FWR-PRD-04.02-*') == 18
    assert db._prefix_overlap(value, 'XYZ-*') == 0
    # Exact-match pattern (no wildcard): whole pattern is the literal prefix.
    assert db._prefix_overlap('com.netflix.ninja', 'com.netflix.ninja') == len('com.netflix.ninja')


def test_near_miss_ordering_matches_doc():
    """Closest literal-prefix overlap should sort first (as the verbose path does)."""
    value = 'EXSTB001-FWR-PRD-05.01-163'
    rows = [_row('XYZ-*', ui='far'), _row('EXSTB001-FWR-PRD-04.02-*', ui='close'), _row('EXSTB001-*', ui='mid')]
    scored = sorted(rows, key=lambda r: (-db._prefix_overlap(value, r['pattern']), r['pattern']))
    assert [r['ai_userinterface_id'] for r in scored] == ['close', 'mid', 'far'], scored


if __name__ == '__main__':
    failures = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for t in tests:
        try:
            t()
            print(f'PASS  {t.__name__}')
        except AssertionError as e:
            failures += 1
            print(f'FAIL  {t.__name__}: {e}')
    print(f'\n{len(tests) - failures}/{len(tests)} passed')
    sys.exit(1 if failures else 0)
