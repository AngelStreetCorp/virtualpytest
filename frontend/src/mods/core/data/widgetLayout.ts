/** Placed widgets per area, kept in this browser. */
import { WIDGET_LAYOUT_STORAGE_KEY, WIDGET_SAVE_DELAY_MS } from '../constants';
import type { WidgetAreaName, WidgetInstance } from '../types';

import { createStore } from './createStore';
import { saveWidgetLayout } from './modsApi';

export type WidgetLayout = Partial<Record<WidgetAreaName, WidgetInstance[]>>;

const load = (): WidgetLayout => {
  try {
    const raw = localStorage.getItem(WIDGET_LAYOUT_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? (parsed as WidgetLayout) : {};
  } catch {
    return {};
  }
};

export const widgetLayoutStore = createStore<WidgetLayout>(load());

widgetLayoutStore.subscribe(() => {
  try {
    localStorage.setItem(WIDGET_LAYOUT_STORAGE_KEY, JSON.stringify(widgetLayoutStore.get()));
  } catch {
    // Blocked storage: the layout lasts for this page only.
  }
});

/** Where layouts are saved: this browser only, or the user's account (signed-in person). */
export const widgetStorageStore = createStore<'browser' | 'server'>('browser');

const pendingSaves = new Map<WidgetAreaName, ReturnType<typeof setTimeout>>();

/** Save an area to the account shortly after the last edit (several quick edits = one request). */
export const scheduleWidgetSave = (area: WidgetAreaName) => {
  if (widgetStorageStore.get() !== 'server') return;
  clearTimeout(pendingSaves.get(area));
  pendingSaves.set(
    area,
    setTimeout(() => {
      pendingSaves.delete(area);
      saveWidgetLayout(area, widgetLayoutStore.get()[area] ?? []).catch((err) =>
        console.warn('[@mods] widget layout kept in this browser only', err),
      );
    }, WIDGET_SAVE_DELAY_MS),
  );
};
