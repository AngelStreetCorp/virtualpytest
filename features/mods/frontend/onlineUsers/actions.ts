/** Pure rules of the Online Users mod. */
import type { PresenceEvent } from '../../../../frontend/src/mods/core/types';

import { MAX_NAMES } from './constants';

/** Names for the tooltip, the rest counted. */
export const listedNames = (e: PresenceEvent): { names: string[]; more: number } => ({
  names: e.users.slice(0, MAX_NAMES).map((u) => u.name),
  more: Math.max(0, e.users.length - MAX_NAMES),
});
