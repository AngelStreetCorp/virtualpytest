import { createStore } from '../../../../../frontend/src/mods/core/data/createStore';
import { initialPipState } from '../actions';
import { PIP_STORAGE_KEY } from '../constants';
import type { PipPosition, PipSelection, PipState } from '../types';

interface Saved {
  selection: PipSelection | null;
  remoteVisible: boolean;
  collapsed: boolean;
  position: PipPosition | null;
}

const isPosition = (value: unknown): value is PipPosition =>
  !!value &&
  typeof value === 'object' &&
  typeof (value as { x?: unknown }).x === 'number' &&
  typeof (value as { y?: unknown }).y === 'number' &&
  Number.isFinite((value as PipPosition).x) &&
  Number.isFinite((value as PipPosition).y);

const load = (): PipState => {
  try {
    const raw = localStorage.getItem(PIP_STORAGE_KEY);
    const saved = raw ? (JSON.parse(raw) as Partial<Saved>) : {};
    const selection = saved.selection?.hostName && saved.selection?.deviceId ? saved.selection : null;
    return {
      ...initialPipState,
      selection,
      remoteVisible: saved.remoteVisible ?? true,
      collapsed: saved.collapsed ?? false,
      position: isPosition(saved.position) ? saved.position : null,
    };
  } catch {
    return initialPipState;
  }
};

export const pipStore = createStore<PipState>(load());

pipStore.subscribe(() => {
  const { selection, remoteVisible, collapsed, position } = pipStore.get();
  try {
    localStorage.setItem(
      PIP_STORAGE_KEY,
      JSON.stringify({ selection, remoteVisible, collapsed, position } satisfies Saved),
    );
  } catch {
    // Blocked storage: PiP lasts for this page only.
  }
});