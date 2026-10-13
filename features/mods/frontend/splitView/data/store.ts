import { createStore } from '../../../../../frontend/src/mods/core/data/createStore';
import { clampWidth, initialSplitState } from '../actions';
import { SPLIT_STORAGE_KEY } from '../constants';
import type { SplitState } from '../types';

const load = (): SplitState => {
  try {
    const raw = localStorage.getItem(SPLIT_STORAGE_KEY);
    const saved = raw ? (JSON.parse(raw) as Partial<SplitState>) : {};
    return {
      open: saved.open === true,
      path: typeof saved.path === 'string' && saved.path.startsWith('/') ? saved.path : initialSplitState.path,
      widthPct: clampWidth(typeof saved.widthPct === 'number' ? saved.widthPct : initialSplitState.widthPct),
      recent: Array.isArray(saved.recent) ? saved.recent.filter((p): p is string => typeof p === 'string') : [],
    };
  } catch {
    return initialSplitState;
  }
};

export const splitStore = createStore<SplitState>(load());

splitStore.subscribe(() => {
  try {
    localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(splitStore.get()));
  } catch {
    // Blocked storage: split view lasts for this page only.
  }
});
