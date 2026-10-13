import { createStore } from '../../../../../frontend/src/mods/core/data/createStore';
import { initialPipState } from '../actions';
import { PIP_STORAGE_KEY } from '../constants';
import type { PipSelection, PipState } from '../types';

interface Saved {
  selection: PipSelection | null;
  remoteVisible: boolean;
}

const load = (): PipState => {
  try {
    const raw = localStorage.getItem(PIP_STORAGE_KEY);
    const saved = raw ? (JSON.parse(raw) as Partial<Saved>) : {};
    const selection = saved.selection?.hostName && saved.selection?.deviceId ? saved.selection : null;
    return { ...initialPipState, selection, remoteVisible: saved.remoteVisible ?? true };
  } catch {
    return initialPipState;
  }
};

export const pipStore = createStore<PipState>(load());

pipStore.subscribe(() => {
  const { selection, remoteVisible } = pipStore.get();
  try {
    localStorage.setItem(PIP_STORAGE_KEY, JSON.stringify({ selection, remoteVisible } satisfies Saved));
  } catch {
    // Blocked storage: PiP lasts for this page only.
  }
});
