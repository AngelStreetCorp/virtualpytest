/** Pure rules of the split view mod. */
import { DEFAULT_PATH, DEFAULT_WIDTH_PCT, MAX_RECENT, MAX_WIDTH_PCT, MIN_WIDTH_PCT } from './constants';
import type { PageOption, SplitState } from './types';

export const initialSplitState: SplitState = { open: false, path: DEFAULT_PATH, widthPct: DEFAULT_WIDTH_PCT, recent: [] };

export const clampWidth = (pct: number) => Math.round(Math.min(MAX_WIDTH_PCT, Math.max(MIN_WIDTH_PCT, pct)));

/** The pane's width from where the divider is dragged to (the pane sits on the right). */
export const widthFromPointer = (clientX: number, rowLeft: number, rowWidth: number) =>
  rowWidth > 0 ? clampWidth(((rowLeft + rowWidth - clientX) / rowWidth) * 100) : DEFAULT_WIDTH_PCT;

export const openPage = (state: SplitState, path: string): SplitState => ({
  ...state,
  open: true,
  path,
  recent: [path, ...state.recent.filter((p) => p !== path)].slice(0, MAX_RECENT),
});

export const closeSplit = (state: SplitState): SplitState => ({ ...state, open: false });

/** Toggle from the shortcut: reopen the last page. */
export const toggleSplit = (state: SplitState): SplitState => (state.open ? closeSplit(state) : openPage(state, state.path));

/** The pane navigated by itself: follow it, without touching the recent list. */
export const followPane = (state: SplitState, path: string): SplitState =>
  state.path === path ? state : { ...state, path };

export const setWidth = (state: SplitState, pct: number): SplitState => ({ ...state, widthPct: clampWidth(pct) });

/** In-app pages only (no external links), visible in this workspace, each path once. */
export const pageOptions = (entries: PageOption[], isHidden: (path: string) => boolean): PageOption[] => {
  const seen = new Set<string>();
  return entries.filter((e) => {
    // Defensive: a malformed feature-contributed item (no `path`) used to
    // crash this filter on `e.path.startsWith` and take the whole split view
    // (and the page menu it opens) down with it. Action rows and broken
    // entries are not selectable pages; drop them silently here.
    if (typeof e.path !== 'string') return false;
    if (!e.path.startsWith('/') || isHidden(e.path) || seen.has(e.path)) return false;
    seen.add(e.path);
    return true;
  });
};

/** A router path from a frame location: drop the proxy prefix (e.g. /pi4). */
export const routerPath = (pathname: string, search: string, basename: string) => {
  const path = basename && pathname.startsWith(basename) ? pathname.slice(basename.length) || '/' : pathname;
  return `${path}${search}`;
};
