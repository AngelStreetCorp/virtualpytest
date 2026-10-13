import { useSyncExternalStore } from 'react';

import type { ModStore } from '../data/createStore';

export const useModStore = <T>(store: ModStore<T>): T => useSyncExternalStore(store.subscribe, store.get);
