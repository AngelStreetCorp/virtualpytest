import { useMemo } from 'react';

import { useMods } from '../components/ModsProvider';
import { scheduleWidgetSave, widgetLayoutStore } from '../data/widgetLayout';
import type { WidgetAreaName, WidgetDefinition, WidgetInstance, WidgetSettings } from '../types';
import { addWidget, moveWidget, placedWidgets, removeWidget, updateWidgetSettings } from '../widgetActions';

import { useModStore } from './useModStore';

const newId = () => `w-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;

/** The widgets offered by mods that are on, the ones placed in `area`, and the edits. */
export const useWidgetArea = (area: WidgetAreaName) => {
  const { registry, api } = useMods();
  const layout = useModStore(widgetLayoutStore);
  const instances = useMemo(() => layout[area] ?? [], [layout, area]);
  const placed = useMemo(() => placedWidgets(instances, registry.widgets), [instances, registry.widgets]);

  const edit = (fn: (list: WidgetInstance[]) => WidgetInstance[]) => {
    widgetLayoutStore.update((l) => ({ ...l, [area]: fn(l[area] ?? []) }));
    scheduleWidgetSave(area);
  };

  return {
    api,
    available: registry.widgets,
    placed,
    add: (def: WidgetDefinition) => edit((list) => addWidget(list, def, newId())),
    remove: (id: string) => edit((list) => removeWidget(list, id)),
    move: (id: string, step: -1 | 1) => edit((list) => moveWidget(list, id, step)),
    configure: (id: string, settings: WidgetSettings) => edit((list) => updateWidgetSettings(list, id, settings)),
  };
};
