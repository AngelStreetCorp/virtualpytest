/** A tiny external store for mod state: read with `useModStore`, write with `update`. */
export interface ModStore<T> {
  get: () => T;
  update: (fn: (prev: T) => T) => void;
  subscribe: (listener: () => void) => () => void;
}

export const createStore = <T>(initial: T): ModStore<T> => {
  let value = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    update: (fn) => {
      const next = fn(value);
      if (next === value) return;
      value = next;
      listeners.forEach((l) => l());
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
};
