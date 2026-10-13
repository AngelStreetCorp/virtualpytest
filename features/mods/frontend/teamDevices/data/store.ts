import { createStore } from '../../../../../frontend/src/mods/core/data/createStore';
import type { FleetState } from '../types';

export const fleetStore = createStore<FleetState>({ running: {}, errors: {} });
