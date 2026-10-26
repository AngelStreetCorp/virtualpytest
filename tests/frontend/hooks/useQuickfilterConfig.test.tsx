// @vitest-environment jsdom
/**
 * QuickfilterBadgeArea's per-user category config (TASK-120): which categories
 * the row shows, in which order. Backed by localStorage; default is
 * `['profiles']`. Sanitisation drops unknown ids and rejects empty arrays.
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  ALL_CATEGORIES,
  DEFAULT_CATEGORIES,
  useQuickfilterConfig,
} from '../../../frontend/src/hooks/useQuickfilterConfig';

const STORAGE_KEY = 'vpt_quickfilter_config_v1';

afterEach(() => window.localStorage.clear());
beforeEach(() => window.localStorage.clear());

describe('useQuickfilterConfig', () => {
  it('starts with the default (profiles only) on a fresh storage', () => {
    const { result } = renderHook(() => useQuickfilterConfig());
    expect(result.current.categories).toEqual(DEFAULT_CATEGORIES);
  });

  it('persists the category list under the storage key', () => {
    const { result } = renderHook(() => useQuickfilterConfig());
    act(() => {
      result.current.toggleCategory('models');
      result.current.toggleCategory('favorites');
    });
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? 'null');
    expect(stored).toEqual(['profiles', 'models', 'favorites']);
  });

  it('toggles a category on and off', () => {
    const { result } = renderHook(() => useQuickfilterConfig());
    act(() => result.current.toggleCategory('models'));
    expect(result.current.categories).toEqual(['profiles', 'models']);
    act(() => result.current.toggleCategory('models'));
    expect(result.current.categories).toEqual(['profiles']);
  });

  it('allows the user to remove the last category, leaving the array empty (the bolt stays visible so the user can re-enable)', () => {
    const { result } = renderHook(() => useQuickfilterConfig());
    act(() => result.current.toggleCategory('profiles'));
    expect(result.current.categories).toEqual([]);
  });

  it('clear empties the category list', () => {
    const { result } = renderHook(() => useQuickfilterConfig());
    act(() => {
      result.current.toggleCategory('models');
      result.current.toggleCategory('favorites');
    });
    act(() => result.current.clear());
    expect(result.current.categories).toEqual([]);
  });

  it('reorders within bounds', () => {
    const { result } = renderHook(() => useQuickfilterConfig());
    act(() => {
      result.current.toggleCategory('models');
      result.current.toggleCategory('favorites');
    });
    expect(result.current.categories).toEqual(['profiles', 'models', 'favorites']);
    act(() => result.current.reorder(0, 2));
    expect(result.current.categories).toEqual(['models', 'favorites', 'profiles']);
  });

  it('reorder is a no-op when from === to or out of bounds', () => {
    const { result } = renderHook(() => useQuickfilterConfig());
    act(() => {
      result.current.toggleCategory('models');
      result.current.toggleCategory('favorites');
    });
    const before = [...result.current.categories];
    act(() => result.current.reorder(1, 1));
    expect(result.current.categories).toEqual(before);
    act(() => result.current.reorder(-1, 0));
    expect(result.current.categories).toEqual(before);
    act(() => result.current.reorder(0, 99));
    expect(result.current.categories).toEqual(before);
  });

  it('sanitises a malformed stored payload — drops unknown ids, keeps the rest', () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(['models', 'bogus', 'favorites']));
    const { result } = renderHook(() => useQuickfilterConfig());
    expect(result.current.categories).toEqual(['models', 'favorites']);
  });

  it('falls back to default when the stored payload is not an array', () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ hack: true }));
    const { result } = renderHook(() => useQuickfilterConfig());
    expect(result.current.categories).toEqual(DEFAULT_CATEGORIES);
  });

  it('keeps an empty array when the stored array is empty — the user can re-enable from the bolt', () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([]));
    const { result } = renderHook(() => useQuickfilterConfig());
    expect(result.current.categories).toEqual([]);
  });

  it('exposes ALL_CATEGORIES in the canonical order', () => {
    expect(ALL_CATEGORIES).toEqual(['profiles', 'models', 'tags', 'favorites']);
  });
});