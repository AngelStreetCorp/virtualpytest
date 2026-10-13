import { createStore } from '../../../../../frontend/src/mods/core/data/createStore';
import type { OnlineState } from '../types';

export const onlineStore = createStore<OnlineState>(null);
