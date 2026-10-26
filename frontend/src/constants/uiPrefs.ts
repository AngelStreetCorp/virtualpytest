/** Per-browser UI preferences for the Appearance settings (same storage style as themeStore). */
export const REDUCE_MOTION_KEY = 'virtualpytest:ui:reduceMotion';
export const NOTIFY_RUNS_KEY = 'virtualpytest:ui:notifyRuns';

export const loadFlag = (key: string): boolean => {
  try {
    return localStorage.getItem(key) === 'true';
  } catch {
    return false;
  }
};

export const saveFlag = (key: string, on: boolean): void => {
  try {
    localStorage.setItem(key, on ? 'true' : 'false');
  } catch {
    /* storage unavailable */
  }
};

/** Navbar menu icon colour (TASK-136): `default` (text colour), `theme` (the accent), `series:N`
 *  (the palette's series colour N, so it follows light / dark) or a fixed `#rrggbb`. */
export const MENU_ICON_COLOUR_KEY = 'virtualpytest:ui:menuIconColour';
export const MENU_ICON_SERIES = [1, 2, 3, 4];

export const isMenuIconColour = (v: unknown): v is string =>
  v === 'default' ||
  v === 'theme' ||
  (typeof v === 'string' && (/^#[0-9a-fA-F]{6}$/.test(v) || MENU_ICON_SERIES.some((n) => v === `series:${n}`)));

export const loadMenuIconColour = (): string => {
  try {
    const v = localStorage.getItem(MENU_ICON_COLOUR_KEY);
    return isMenuIconColour(v) ? v : 'default';
  } catch {
    return 'default';
  }
};

export const saveMenuIconColour = (v: string): void => {
  try {
    localStorage.setItem(MENU_ICON_COLOUR_KEY, v);
  } catch {
    /* storage unavailable */
  }
};
