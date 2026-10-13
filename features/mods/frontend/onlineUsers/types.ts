import type { PresenceEvent } from '../../../../frontend/src/mods/core/types';

/** The latest presence, or null before the first one arrives. */
export type OnlineState = PresenceEvent | null;
