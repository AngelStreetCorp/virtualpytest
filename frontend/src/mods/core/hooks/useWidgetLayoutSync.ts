import { useEffect } from 'react';

import { WIDGET_AREAS } from '../constants';
import { saveWidgetLayout, fetchWidgetLayout } from '../data/modsApi';
import { widgetLayoutStore, widgetStorageStore } from '../data/widgetLayout';
import { pickLayout } from '../widgetActions';

/**
 * Once per page: load this user's widget layouts. A signed-in person switches to account
 * storage (copying up a browser layout the first time); a shared login, or a server without
 * the mods feature, keeps browser storage.
 */
export const useWidgetLayoutSync = (active: boolean): void => {
  useEffect(() => {
    if (!active) return undefined;
    let cancelled = false;
    void (async () => {
      try {
        const results = await Promise.all(WIDGET_AREAS.map((area) => fetchWidgetLayout(area)));
        if (cancelled || results.some((r) => !r || r.shared)) return;
        const local = widgetLayoutStore.get();
        const next = { ...local };
        await Promise.all(
          WIDGET_AREAS.map(async (area, i) => {
            const { layout, upload } = pickLayout(local[area] ?? [], results[i]?.layout ?? null);
            next[area] = layout;
            if (upload) await saveWidgetLayout(area, layout);
          }),
        );
        if (cancelled) return;
        widgetLayoutStore.update(() => next);
        widgetStorageStore.update(() => 'server');
      } catch (err) {
        console.warn('[@mods] widget layouts not loaded; they stay in this browser', err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [active]);
};
