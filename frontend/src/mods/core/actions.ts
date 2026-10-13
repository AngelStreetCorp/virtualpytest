import type { ModChoices } from './data/enabledMods';
import type { ModDefinition } from './types';

/** A mod is on when the user said so, else by its default. */
export const isModEnabled = (mod: ModDefinition, choices: ModChoices): boolean => choices[mod.id] ?? mod.defaultEnabled;

export const enabledMods = (mods: ModDefinition[], choices: ModChoices): ModDefinition[] =>
  mods.filter((m) => isModEnabled(m, choices));

export const setModChoice = (choices: ModChoices, id: string, enabled: boolean): ModChoices =>
  choices[id] === enabled ? choices : { ...choices, [id]: enabled };

/**
 * Server choices win; a choice only this browser has is kept and returned in `toUpload`
 * so it is copied to the server once (the first sign-in after choices were browser-only).
 */
export const mergeChoices = (local: ModChoices, server: ModChoices): { merged: ModChoices; toUpload: [string, boolean][] } => {
  const toUpload = Object.entries(local).filter(([id]) => !(id in server));
  return { merged: { ...local, ...server }, toUpload };
};
