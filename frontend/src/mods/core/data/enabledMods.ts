/**
 * Which mods this browser turned on or off. Only explicit choices are stored;
 * a mod never touched follows its `defaultEnabled`.
 */
import { ENABLED_MODS_STORAGE_KEY } from '../constants';

import { createStore } from './createStore';

export type ModChoices = Record<string, boolean>;

const load = (): ModChoices => {
  try {
    const raw = localStorage.getItem(ENABLED_MODS_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? (parsed as ModChoices) : {};
  } catch {
    return {};
  }
};

export const modChoicesStore = createStore<ModChoices>(load());

modChoicesStore.subscribe(() => {
  try {
    localStorage.setItem(ENABLED_MODS_STORAGE_KEY, JSON.stringify(modChoicesStore.get()));
  } catch {
    // Private window or blocked storage: the choice lasts for this page only.
  }
});

/** Where choices are saved: this browser only, or the user's server row (signed-in person). */
export type ModChoiceStorage = 'browser' | 'server';
export const modStorageStore = createStore<ModChoiceStorage>('browser');
