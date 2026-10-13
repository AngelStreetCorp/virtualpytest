"""Variant name->id memo semantics (BUG-0203 regression guard).

Runs without a DB: `variant_name_id_map` is replaced, and every call is counted.
What is pinned is the trade the memo makes — fewer round trips, bounded staleness:

* repeated scoped reads hit the memo instead of the database;
* a base run never resolves anything at all (no DB call, the common path);
* an empty/failed read is NOT cached, or one blip would key every run by name;
* the TTL expires;
* invalidating the graph cache invalidates the map with it, so a rename or a
  delete cannot be served from a stale map for the rest of the TTL.
"""
import importlib

import pytest


@pytest.fixture
def cache(monkeypatch):
    mod = importlib.import_module('shared.src.lib.utils.navigation_cache')
    ui_db = importlib.import_module('shared.src.lib.database.userinterface_db')

    calls = {'n': 0}
    state = {'map': {'variant1': 'id-1', 'base_5.30': 'id-2'}}

    def fake_map(team_id, ui_id):
        calls['n'] += 1
        return dict(state['map'])

    monkeypatch.setattr(ui_db, 'variant_name_id_map', fake_map)
    # the tree -> userinterface lookup is a separate (permanent) memo; pre-seed it
    # so these tests never touch the database for it either
    monkeypatch.setitem(mod._tree_ui_memo, 'tree-1', 'ui-1')
    mod.clear_variant_map_memo()
    return mod, calls, state


@pytest.mark.unit
def test_repeated_scoped_reads_hit_the_memo(cache):
    mod, calls, _ = cache
    keys = [mod._make_cache_key('tree-1', 'team-1', 'variant1') for _ in range(15)]

    assert calls['n'] == 1, 'one navigation step should cost one lookup, not 15'
    assert len(set(keys)) == 1, 'the key must be stable across reads'
    assert keys[0].endswith('_id-1'), 'keyed by variant id, not name'


@pytest.mark.unit
def test_base_run_never_resolves(cache):
    """The common path: no variant, no DB call, the __base__ sentinel."""
    mod, calls, _ = cache
    key = mod._make_cache_key('tree-1', 'team-1', None)

    assert calls['n'] == 0
    assert key.endswith('___base__')


@pytest.mark.unit
def test_empty_result_is_not_cached(cache):
    """A failed read must not pin every later run to a name-based key."""
    mod, calls, state = cache
    state['map'] = {}

    first = mod._make_cache_key('tree-1', 'team-1', 'variant1')
    second = mod._make_cache_key('tree-1', 'team-1', 'variant1')

    assert calls['n'] == 2, 'an empty map must be retried, not memoized'
    # unknown component -> documented fallback to the canonical NAME key
    assert first.endswith('_variant1') and first == second


@pytest.mark.unit
def test_ttl_expires(cache, monkeypatch):
    mod, calls, _ = cache
    mod._make_cache_key('tree-1', 'team-1', 'variant1')
    assert calls['n'] == 1

    now = mod._time.monotonic()
    monkeypatch.setattr(mod._time, 'monotonic',
                        lambda: now + mod._VARIANT_MAP_TTL_SECONDS + 0.01)
    mod._make_cache_key('tree-1', 'team-1', 'variant1')
    assert calls['n'] == 2


@pytest.mark.unit
def test_graph_invalidation_also_drops_the_map(cache):
    """A rename arrives as a cache invalidation; the map must not outlive it."""
    mod, calls, state = cache
    mod._make_cache_key('tree-1', 'team-1', 'variant1')
    assert calls['n'] == 1

    state['map'] = {'variant1_renamed': 'id-1'}
    mod.clear_unified_cache()

    key = mod._make_cache_key('tree-1', 'team-1', 'variant1_renamed')
    assert calls['n'] == 2, 'clear_unified_cache must drop the memo'
    assert key.endswith('_id-1'), 'the renamed variant resolves to the same stable id'
