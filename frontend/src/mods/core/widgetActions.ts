/** Pure rules for widget areas: add, remove, move, configure, and drop widgets no longer offered. */
import type { WidgetDefinition, WidgetInstance, WidgetSettings } from './types';

export const defaultSettings = (def: WidgetDefinition): WidgetSettings =>
  Object.fromEntries((def.settings ?? []).map((f) => [f.key, f.default]));

/** Missing keys take the field default; keys no longer declared are dropped. */
export const resolvedSettings = (def: WidgetDefinition, settings: WidgetSettings): WidgetSettings => ({
  ...defaultSettings(def),
  ...Object.fromEntries(Object.entries(settings).filter(([k]) => (def.settings ?? []).some((f) => f.key === k))),
});

export const addWidget = (instances: WidgetInstance[], def: WidgetDefinition, id: string): WidgetInstance[] => [
  ...instances,
  { id, widgetId: def.id, settings: defaultSettings(def) },
];

export const removeWidget = (instances: WidgetInstance[], id: string): WidgetInstance[] =>
  instances.filter((w) => w.id !== id);

/** Move one place left (-1) or right (+1); unchanged at the ends. */
export const moveWidget = (instances: WidgetInstance[], id: string, step: -1 | 1): WidgetInstance[] => {
  const i = instances.findIndex((w) => w.id === id);
  const j = i + step;
  if (i < 0 || j < 0 || j >= instances.length) return instances;
  const next = [...instances];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
};

export const updateWidgetSettings = (instances: WidgetInstance[], id: string, settings: WidgetSettings): WidgetInstance[] =>
  instances.map((w) => (w.id === id ? { ...w, settings } : w));

/** Placed widgets whose mod is on, with their definition; the rest stay saved for when it comes back. */
export const placedWidgets = (instances: WidgetInstance[], defs: WidgetDefinition[]) =>
  instances.flatMap((w) => {
    const def = defs.find((d) => d.id === w.widgetId);
    return def ? [{ instance: w, def, settings: resolvedSettings(def, w.settings) }] : [];
  });

/**
 * On load: the account's layout wins; with none saved yet, the browser's is kept and copied up
 * (when it has anything to copy).
 */
export const pickLayout = (local: WidgetInstance[], server: WidgetInstance[] | null): { layout: WidgetInstance[]; upload: boolean } =>
  server === null ? { layout: local, upload: local.length > 0 } : { layout: server, upload: false };
