import { useEffect } from 'react';

import { mergeChoices } from '../actions';
import { modChoicesStore, modStorageStore } from '../data/enabledMods';
import { fetchPreferences, savePreference } from '../data/modsApi';

/**
 * Once per page: load this user's saved choices. A signed-in person switches to server
 * storage (copying up choices only this browser had); a shared login, or a server without
 * the mods feature, keeps browser storage.
 */
export const useModPreferencesSync = (active: boolean): void => {
  useEffect(() => {
    if (!active) return undefined;
    let cancelled = false;
    fetchPreferences()
      .then(async (prefs) => {
        if (cancelled || !prefs || prefs.shared) return;
        const { merged, toUpload } = mergeChoices(modChoicesStore.get(), prefs.choices);
        await Promise.all(toUpload.map(([id, on]) => savePreference(id, on)));
        if (cancelled) return;
        modChoicesStore.update(() => merged);
        modStorageStore.update(() => 'server');
      })
      .catch((err) => console.warn('[@mods] preferences not loaded; choices stay in this browser', err));
    return () => {
      cancelled = true;
    };
  }, [active]);
};
