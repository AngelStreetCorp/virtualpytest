export const MOD_ID = 'split-view';

/** Browser memory: pane open, its page, width and recent pages, so split view survives a reload. */
export const SPLIT_STORAGE_KEY = 'virtualpytest:mods:split-view';

/** Width of the second page, in % of the area beside the page. */
export const MIN_WIDTH_PCT = 25;
export const MAX_WIDTH_PCT = 75;
export const DEFAULT_WIDTH_PCT = 50;

export const DEFAULT_PATH = '/';
export const MAX_RECENT = 5;

/** How often the pane's own page (it navigates inside the frame) is read back. */
export const PATH_READ_MS = 1500;

/** Toggle: Ctrl + Alt + S (Cmd + Alt + S on a Mac). */
export const SHORTCUT_KEY = 's';
export const SHORTCUT_LABEL = 'Ctrl + Alt + S';
