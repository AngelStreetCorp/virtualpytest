import { describe, expect, it } from 'vitest';

import type { WidgetDefinition, WidgetInstance } from './types';
import { addWidget, moveWidget, pickLayout, placedWidgets, removeWidget, resolvedSettings, updateWidgetSettings } from './widgetActions';

const def: WidgetDefinition = {
  id: 'w',
  name: 'W',
  description: '',
  size: 'small',
  settings: [{ key: 'show', label: 'Show', type: 'select', default: 'all' }],
  Component: () => null,
};

describe('widget areas', () => {
  it('adds with default settings, moves, configures and removes', () => {
    let list = addWidget([], def, 'a');
    list = addWidget(list, def, 'b');
    expect(list[0].settings).toEqual({ show: 'all' });
    list = moveWidget(list, 'b', -1);
    expect(list.map((w) => w.id)).toEqual(['b', 'a']);
    expect(moveWidget(list, 'b', -1)).toBe(list);
    list = updateWidgetSettings(list, 'a', { show: 'active' });
    expect(list[1].settings.show).toBe('active');
    expect(removeWidget(list, 'b').map((w) => w.id)).toEqual(['a']);
  });

  it('hides widgets whose mod is off and fills missing settings', () => {
    const list: WidgetInstance[] = [
      { id: 'a', widgetId: 'w', settings: { stale: true } },
      { id: 'b', widgetId: 'gone', settings: {} },
    ];
    const placed = placedWidgets(list, [def]);
    expect(placed.map((p) => p.instance.id)).toEqual(['a']);
    expect(placed[0].settings).toEqual({ show: 'all' });
    expect(resolvedSettings(def, { show: 'x' })).toEqual({ show: 'x' });
  });

  it('lets the account layout win, and copies a browser layout up once', () => {
    const local: WidgetInstance[] = [{ id: 'a', widgetId: 'w', settings: {} }];
    const server: WidgetInstance[] = [{ id: 'b', widgetId: 'w', settings: {} }];
    expect(pickLayout(local, server)).toEqual({ layout: server, upload: false });
    expect(pickLayout(local, null)).toEqual({ layout: local, upload: true });
    expect(pickLayout([], null)).toEqual({ layout: [], upload: false });
  });
});
