import { useMemo } from 'react';

import { featureMods } from '../../../config/features';
import { enabledMods, isModEnabled, setModChoice } from '../actions';
import { modChoicesStore, modStorageStore } from '../data/enabledMods';
import { savePreference } from '../data/modsApi';

import { useModStore } from './useModStore';

/** Every installed mod with its on/off state, and the switch. */
export const useEnabledMods = () => {
  const choices = useModStore(modChoicesStore);
  const storage = useModStore(modStorageStore);
  const installed = useMemo(() => featureMods(), []);
  const enabled = useMemo(() => enabledMods(installed, choices), [installed, choices]);

  return {
    installed,
    enabled,
    isEnabled: (id: string) => {
      const mod = installed.find((m) => m.id === id);
      return mod ? isModEnabled(mod, choices) : false;
    },
    setEnabled: (id: string, on: boolean) => {
      modChoicesStore.update((c) => setModChoice(c, id, on));
      if (storage === 'server') {
        savePreference(id, on).catch((err) => console.warn('[@mods] choice kept in this browser only', err));
      }
    },
    storage,
  };
};
