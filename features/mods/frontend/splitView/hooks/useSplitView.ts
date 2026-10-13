import { useModStore } from '../../../../../frontend/src/mods/core/hooks/useModStore';
import { closeSplit, followPane, openPage, setWidth, toggleSplit } from '../actions';
import { splitStore } from '../data/store';

export const useSplitView = () => {
  const state = useModStore(splitStore);
  return {
    state,
    open: (path: string) => splitStore.update((s) => openPage(s, path)),
    close: () => splitStore.update(closeSplit),
    toggle: () => splitStore.update(toggleSplit),
    follow: (path: string) => splitStore.update((s) => followPane(s, path)),
    resize: (pct: number) => splitStore.update((s) => setWidth(s, pct)),
  };
};
